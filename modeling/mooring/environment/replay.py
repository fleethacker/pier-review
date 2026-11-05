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

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from mooring.core.schemas import EnvironmentMetadata, EnvironmentSnapshot

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
                         r.get("wind_reference_height_m"), r.get("source"), r.get("current_depth_ft"), r.get("current_bin"), original)
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
        return EnvironmentSnapshot(
            valid_at_utc=t, source=self.source_kind, wind_speed_kt=v["wind_speed_kt"], wind_gust_kt=max(v["wind_gust_kt"], v["wind_speed_kt"]),
            wind_from_true_deg=v["wind_from_true_deg"] % 360, current_speed_kt=v["current_speed_kt"], current_set_true_deg=v["current_set_true_deg"] % 360,
            water_level_mllw_ft=v["water_level_ft"],
            metadata=EnvironmentMetadata(basis=self.basis, source=rec_meta.source or self.station, issued_at_utc=lo.t, valid_from_utc=lo.t, valid_to_utc=hi.t,
                                         wind_averaging_s=rec_meta.wind_averaging_s, gust_duration_s=rec_meta.gust_duration_s,
                                         wind_reference_height_m=rec_meta.wind_reference_height_m, vertical_datum="MLLW", quality=worst, age_s=max(age, 0.0),
                                         current_depth_ft=rec_meta.current_depth_ft, current_bin=rec_meta.current_bin,
                                         original=rec_meta.original))

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
        _FIXTURE_SOURCE = ReplaySource(raw, max_gap_s=900, stale_after_s=10**9, station="recorded_fixture", source_kind="replay")
    return _FIXTURE_SOURCE
