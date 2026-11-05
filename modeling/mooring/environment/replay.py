"""Deterministic replay of recorded environment observations (S04a).

Takes observation records exactly as a provider would deliver them (any timezone offset, any order, duplicates, missing
fields, quality flags, a declared vertical datum) and produces normalized `EnvironmentSnapshot`s at requested times.
Nothing here touches the network or the wall clock: results depend only on the records and the injected `at` times, so a
replay is identical across clocks and machines.

Policies (each tested):
* Times are normalized to UTC; records without a timezone are rejected, not guessed.
* Records are sorted; exact duplicates are dropped; conflicting duplicates at the same time keep the better quality and are
  reported, never silently averaged.
* Direction is interpolated on the circle (359 and 1 degrees give 0), speeds linearly, only between two records closer than
  `max_gap_s`. Across a larger gap the value is unavailable: there is no interpolation across unqualified gaps and no
  synthetic substitute.
* A datum other than MLLW is rejected unless the record says so explicitly and a conversion offset is supplied.
* Records marked bad quality are excluded; missing required fields exclude the record and are reported.
* Wind averaging and gust duration are never inferred from the reporting interval; they come from the record metadata or
  stay unknown.
* A request outside the recorded horizon, or older than `stale_after_s` since the last record, returns unavailable.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mooring.core.schemas import EnvironmentComponentProvenance, EnvironmentMetadata, EnvironmentSnapshot
from .providers import canonical_fixture_bytes

REQUIRED = ("wind_speed_kt", "wind_gust_kt", "wind_from_true_deg", "current_speed_kt", "current_set_true_deg", "water_level_ft")
QUALITY_RANK = {"good": 3, "unknown": 2, "suspect": 1, "poor": 0}


class ReplayError(ValueError):
    """Invalid recorded input (HTTP 422 when it arrives through an API)."""


@dataclass
class Record:
    t: datetime
    values: dict
    quality: str = "unknown"
    datum: str = "MLLW"
    wind_averaging_s: float | None = None
    gust_duration_s: float | None = None
    wind_reference_height_m: float | None = None
    source: str | None = None
    current_depth_ft: float | None = None
    current_bin: str | None = None
    original: dict[str, float | str] | None = None
    components: list[dict] | None = None


@dataclass
class Unavailable:
    reason: str


@dataclass
class ReplayReport:
    dropped: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def parse_time(value: str | datetime) -> datetime:
    t = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if t.tzinfo is None:
        raise ReplayError(f"timestamp {value!r} has no timezone; refusing to guess")
    return t.astimezone(UTC)


def circular_lerp_deg(a: float, b: float, w: float) -> float:
    """Interpolate along the short way around the circle."""
    d = (b - a + 180.0) % 360.0 - 180.0
    return round((a + w * d) % 360.0, 9) % 360.0


def _component_provenance(lo: Record, hi: Record) -> list[EnvironmentComponentProvenance] | Unavailable:
    lower = [EnvironmentComponentProvenance.model_validate(item) for item in (lo.components or [])]
    if lo.t == hi.t:
        return lower
    upper = {item.component: item for item in (
        EnvironmentComponentProvenance.model_validate(raw) for raw in (hi.components or [])
    )}
    out = []
    for item in lower:
        other = upper.get(item.component)
        endpoints_valid = other is not None and all(
            (meta.valid_from_utc is None or meta.valid_from_utc <= at)
            and (meta.valid_to_utc is None or at <= meta.valid_to_utc)
            for meta, at in ((item, lo.t), (other, hi.t))
        )
        if not endpoints_valid or (item.source, item.basis) != (other.source, other.basis):
            # Never repair invalid input metadata by enlarging its interval.
            return Unavailable(f"{item.component} replay interpolation requires matching sources and valid endpoint intervals")
        note = (f"Interpolated between aligned replay values at {lo.t.isoformat()} and {hi.t.isoformat()}; "
                "speeds/level are linear and directions circular. Both endpoint observations are retained in metadata.original; "
                "this interval describes replay interpolation, not provider-declared observation validity.")
        out.append(item.model_copy(update={
            "valid_from_utc": lo.t,
            "valid_to_utc": hi.t,
            "quality": min((item.quality, other.quality), key=QUALITY_RANK.__getitem__),
            "limitations": list(dict.fromkeys([*item.limitations, *other.limitations, note])),
        }))
    return out


class ReplaySource:
    def __init__(self, raw: list[dict], *, max_gap_s: float = 1800.0, stale_after_s: float = 3600.0, datum_offset_ft: dict[str, float] | None = None,
                 station: str = "replay", source_kind: str = "replay", basis: str = "observation"):
        self.max_gap_s, self.stale_after_s, self.station = max_gap_s, stale_after_s, station
        self.source_kind, self.basis = source_kind, basis
        self.report = ReplayReport()
        self.records = self._normalize(raw, datum_offset_ft or {})

    def _normalize(self, raw: list[dict], offsets: dict[str, float]) -> list[Record]:
        out: dict[datetime, Record] = {}
        for i, r in enumerate(raw):
            t = parse_time(r["t"])
            vals = {k: r.get(k) for k in REQUIRED}
            quality = r.get("quality", "unknown")
            datum = r.get("datum", "MLLW")
            if quality == "poor":
                self.report.dropped.append(f"{t.isoformat()}: poor quality")
                continue
            missing = [k for k, v in vals.items() if v is None]
            if missing:
                self.report.dropped.append(f"{t.isoformat()}: missing {', '.join(missing)}")
                continue
            if any(not math.isfinite(float(v)) for v in vals.values()):
                self.report.dropped.append(f"{t.isoformat()}: non-finite value")
                continue
            if datum != "MLLW":
                if datum not in offsets:
                    raise ReplayError(f"record at {t.isoformat()} is in datum {datum!r}; supply datum_offset_ft[{datum!r}] to convert to MLLW")
                vals["water_level_ft"] = float(vals["water_level_ft"]) + offsets[datum]
            original = r.get("original") or {k: v for k, v in r.items() if isinstance(v, (float, int, str))}
            rec = Record(t, {k: float(v) for k, v in vals.items()}, quality, "MLLW", r.get("wind_averaging_s"), r.get("gust_duration_s"),
                         r.get("wind_reference_height_m"), r.get("source"), r.get("current_depth_ft"), r.get("current_bin"), original,
                         r.get("components"))
            if t in out:
                old = out[t]
                if old.values == rec.values:
                    self.report.dropped.append(f"{t.isoformat()}: exact duplicate")
                    continue
                keep = rec if QUALITY_RANK[rec.quality] > QUALITY_RANK[old.quality] else old
                self.report.conflicts.append(f"{t.isoformat()}: conflicting duplicate; kept the {'new' if keep is rec else 'earlier'} record by quality")
                out[t] = keep
                continue
            out[t] = rec
        return [out[k] for k in sorted(out)]

    @property
    def coverage(self) -> tuple[datetime, datetime] | None:
        return (self.records[0].t, self.records[-1].t) if self.records else None

    def at(self, t: datetime, *, now: datetime | None = None) -> EnvironmentSnapshot | Unavailable:
        """Snapshot at `t`. `now` is the injected clock used only for the staleness policy (default: t itself)."""
        t = parse_time(t)
        if not self.records:
            return Unavailable("no usable records")
        if t < self.records[0].t or t > self.records[-1].t:
            return Unavailable(f"{t.isoformat()} is outside the recorded horizon {self.records[0].t.isoformat()}..{self.records[-1].t.isoformat()}")
        clock = parse_time(now) if now is not None else t
        newest = max((r.t for r in self.records if r.t <= t), default=None)
        if newest is not None and (clock - newest).total_seconds() > self.stale_after_s:
            return Unavailable(f"latest record is {(clock - newest).total_seconds():.0f} s old; stale after {self.stale_after_s:g} s")
        lo = max((r for r in self.records if r.t <= t), key=lambda r: r.t)
        hi = min((r for r in self.records if r.t >= t), key=lambda r: r.t)
        if lo.t == hi.t:
            v, rec_meta = dict(lo.values), lo
            age = (clock - lo.t).total_seconds()
        else:
            if (hi.t - lo.t).total_seconds() > self.max_gap_s:
                return Unavailable(f"records {lo.t.isoformat()} and {hi.t.isoformat()} are further apart than {self.max_gap_s:g} s; not interpolated")
            w = (t - lo.t).total_seconds() / (hi.t - lo.t).total_seconds()
            v = {k: lo.values[k] + w * (hi.values[k] - lo.values[k]) for k in REQUIRED}
            for k in ("wind_from_true_deg", "current_set_true_deg"):
                v[k] = circular_lerp_deg(lo.values[k], hi.values[k], w)
            rec_meta, age = lo, (clock - lo.t).total_seconds()
        worst = min((lo, hi), key=lambda r: QUALITY_RANK[r.quality]).quality
        # Record time establishes observation/validity time, not an independent provider issue time.
        components = _component_provenance(lo, hi)
        if isinstance(components, Unavailable):
            return components
        original = rec_meta.original
        if lo.t != hi.t and components:
            original = {
                **(lo.original or {}),
                **{f"interpolation_upper_{key}": value for key, value in (hi.original or {}).items()},
                "interpolation_lower_time_utc": lo.t.isoformat(),
                "interpolation_upper_time_utc": hi.t.isoformat(),
            }
        return EnvironmentSnapshot(
            valid_at_utc=t, source=self.source_kind, wind_speed_kt=v["wind_speed_kt"], wind_gust_kt=max(v["wind_gust_kt"], v["wind_speed_kt"]),
            wind_from_true_deg=v["wind_from_true_deg"] % 360, current_speed_kt=v["current_speed_kt"], current_set_true_deg=v["current_set_true_deg"] % 360,
            water_level_mllw_ft=v["water_level_ft"],
            metadata=EnvironmentMetadata(basis=self.basis, source=rec_meta.source or self.station, components=components,
                                         valid_from_utc=lo.t, valid_to_utc=hi.t,
                                         wind_averaging_s=rec_meta.wind_averaging_s, gust_duration_s=rec_meta.gust_duration_s,
                                         wind_reference_height_m=rec_meta.wind_reference_height_m, vertical_datum="MLLW", quality=worst, age_s=max(age, 0.0),
                                         current_depth_ft=rec_meta.current_depth_ft, current_bin=rec_meta.current_bin,
                                         original=original))

    def series(self, start: datetime, end: datetime, step: timedelta, *, now: datetime | None = None):
        """(time, snapshot | Unavailable) on a regular grid. Unavailable entries stay in place: gaps are never filled."""
        t, out = parse_time(start), []
        end = parse_time(end)
        while t <= end:
            out.append((t, self.at(t, now=now)))
            t += step
        return out


_FIXTURE_SOURCE = None


def recorded_fixture_source() -> "ReplaySource":
    """The bundled recorded-format sample (synthetic values in the recorded format), used by replay scenarios."""
    global _FIXTURE_SOURCE
    if _FIXTURE_SOURCE is None:
        import json
        from pathlib import Path
        raw = json.loads((Path(__file__).parent / "fixtures" / "replay_sample.json").read_text())
        _FIXTURE_SOURCE = ReplaySource(raw, max_gap_s=900, stale_after_s=10**9, station="synthetic recorded-format fixture", source_kind="replay", basis="scenario")
    return _FIXTURE_SOURCE


RECORDED_REAL_PACKAGE = (
    Path(__file__).parent
    / "fixtures"
    / "recorded_real"
    / "noaa-coops-norfolk-2026-01-01-v1"
)


@dataclass(frozen=True)
class RecordedReplayPackage:
    manifest: dict
    source: ReplaySource

    @property
    def package_id(self) -> str:
        return self.manifest["package_id"]

    def supports_berth(self, berth_id: str) -> bool:
        return berth_id in self.manifest["applicable_berth_ids"]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_recorded_real_package(path: Path = RECORDED_REAL_PACKAGE) -> RecordedReplayPackage:
    """Load and verify a recorded-observation package before any value is served."""
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"recorded replay manifest is unreadable: {exc}") from None
    if manifest.get("schema_version") != "recorded-replay-v1" or manifest.get("kind") != "recorded_observation":
        raise ReplayError("recorded replay manifest has an unsupported schema or kind")
    data_info = manifest.get("data")
    if not isinstance(data_info, dict):
        raise ReplayError("recorded replay manifest has no data object")
    relative = data_info.get("path")
    if not isinstance(relative, str) or Path(relative).name != relative:
        raise ReplayError("recorded replay data path must be one package-local file")
    data_path = path / relative
    try:
        data = data_path.read_bytes()
    except OSError as exc:
        raise ReplayError(f"recorded replay observations are unreadable: {exc}") from None
    digest = _sha256(data)
    if digest != data_info.get("sha256"):
        raise ReplayError("recorded replay observations do not match the manifest SHA-256")
    revision_payload = {key: value for key, value in manifest.items() if key != "revision"}
    if manifest.get("revision") != f"sha256:{_sha256(canonical_fixture_bytes(revision_payload))}":
        raise ReplayError("recorded replay revision does not match the package manifest")
    source_files = manifest.get("source_files")
    if not isinstance(source_files, list) or len(source_files) != 3:
        raise ReplayError("recorded replay manifest must bind all three source fixtures")
    for item in source_files:
        try:
            source_path = (path / item["path"]).resolve()
            source_path.relative_to((Path(__file__).parent / "fixtures").resolve())
            source_data = source_path.read_bytes()
        except (KeyError, OSError, TypeError, ValueError):
            raise ReplayError("recorded replay source fixture is missing or outside the fixture directory") from None
        if _sha256(source_data) != item.get("sha256"):
            raise ReplayError(f"recorded replay source fixture hash mismatch: {item.get('path')}")
    try:
        raw = json.loads(data)
    except json.JSONDecodeError:
        raise ReplayError("recorded replay observations are not valid JSON") from None
    coverage = manifest.get("coverage")
    if not isinstance(coverage, dict):
        raise ReplayError("recorded replay manifest has no coverage object")
    if not isinstance(raw, list) or len(raw) != coverage.get("record_count"):
        raise ReplayError("recorded replay record count does not match the manifest")
    try:
        source = ReplaySource(
            raw,
            max_gap_s=float(coverage["max_interpolation_gap_s"]),
            stale_after_s=10**12,
            station=manifest["package_id"],
            source_kind="replay",
            basis="observation",
        )
        actual = source.coverage
        expected = (parse_time(coverage["start_utc"]), parse_time(coverage["end_utc"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayError(f"recorded replay manifest or observations are malformed: {exc}") from None
    if actual != expected:
        raise ReplayError("recorded replay coverage does not match the manifest")
    applicable = manifest.get("applicable_berth_ids")
    if (not isinstance(applicable, list) or not applicable
            or any(not isinstance(berth_id, str) or not berth_id for berth_id in applicable)):
        raise ReplayError("recorded replay manifest has no applicable berths")
    return RecordedReplayPackage(manifest, source)


_RECORDED_REAL_PACKAGE: RecordedReplayPackage | None = None


def recorded_real_package() -> RecordedReplayPackage:
    global _RECORDED_REAL_PACKAGE
    if _RECORDED_REAL_PACKAGE is None:
        _RECORDED_REAL_PACKAGE = load_recorded_real_package()
    return _RECORDED_REAL_PACKAGE


def recorded_real_source() -> ReplaySource:
    return recorded_real_package().source
