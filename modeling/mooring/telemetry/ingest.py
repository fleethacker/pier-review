"""Validating telemetry ingest (S20a/S20b): decode, check, store with provenance; rejected input influences nothing.

Checks per record: NMEA framing/checksum/field validity (nmea.py); load cells against a sensor registry (sensor and vessel
identity, line binding, calibration revision and validity period, units, physical bounds); duplicate/replayed sequence
numbers; out-of-order and future timestamps; receipt freshness. Independent channels are stored independently, bounded in
memory. Read-only: telemetry never produces vessel control outputs.

Source arbitration (`arbitrate`) decides which environment snapshot a consumer may use: an explicit scenario or verified
manual input outranks everything; a sensor reading is adopted only when fresh and good quality, and it never silently
replaces a qualified forecast: where it disagrees with one beyond the stated tolerance the conflict is reported and the
higher-priority source wins.
"""

import json
import os
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from mooring.core.envelopes import utcnow
from mooring.core import access
from mooring.core.schemas import EnvironmentSnapshot, TelemetryAccepted, TelemetryBatch, TelemetryRecord, TelemetryRejection

from . import nmea

MAX_BATCH = int(os.environ.get("MOORING_TELEMETRY_MAX_BATCH", "500"))
MAX_SKEW_FUTURE_S = 60.0
MAX_AGE_S = 600.0
HISTORY = 100
SEEN_LIMIT = 10_000
MAX_CHANNELS = 4096
MAX_AUTH_CONFIG_CHARS = 65_536
MAX_AUTH_PRINCIPALS = 512
MAX_VESSELS_PER_PRINCIPAL = 256
MAX_ID_LENGTH = 128

ChannelKey = tuple[str, str | None, str]  # authenticated principal, vessel, source/channel


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def _vessel_authorization(owner: str) -> tuple[frozenset[str] | None, tuple[str, str] | None]:
    """Fail closed under API authentication; local-demo identity is not verified."""
    if not access.enforced.get():
        return None, None
    raw = os.environ.get("MOORING_TELEMETRY_VESSELS", "")
    try:
        if not raw or len(raw) > MAX_AUTH_CONFIG_CHARS:
            raise ValueError()
        mapping = json.loads(raw, object_pairs_hook=_unique_keys)
        if not isinstance(mapping, dict) or len(mapping) > MAX_AUTH_PRINCIPALS:
            raise ValueError()
        for principal, vessels in mapping.items():
            if (not isinstance(principal, str) or not 0 < len(principal) <= MAX_ID_LENGTH
                    or not isinstance(vessels, list) or len(vessels) > MAX_VESSELS_PER_PRINCIPAL
                    or any(not isinstance(vessel, str) or not 0 < len(vessel) <= MAX_ID_LENGTH for vessel in vessels)):
                raise ValueError()
        return frozenset(mapping.get(owner, [])), None
    except (ValueError, TypeError, RecursionError):
        # Never echo environment configuration, parser fragments or other owners.
        return None, ("AUTHORIZATION_UNAVAILABLE", "Telemetry vessel authorization is not configured correctly")


@dataclass(frozen=True)
class Sensor:
    sensor_id: str
    vessel_id: str
    line_number: int
    calibration_rev: str
    calibration_valid_from: datetime
    calibration_valid_until: datetime
    min_lbf: float = 0.0
    max_lbf: float = 1_000_000.0


@dataclass
class Adopted:
    record: TelemetryRecord
    received: datetime
    quality: str
    provenance: str
    decoded: object | None = None


class Ingest:
    def __init__(self, sensors: list[Sensor] | None = None, clock=utcnow):
        self.sensors = {s.sensor_id: s for s in (sensors or [])}
        self.clock = clock
        self.lock = threading.Lock()
        self.latest: dict[ChannelKey, Adopted] = {}
        self.history: dict[ChannelKey, deque] = {}
        self.seen: OrderedDict[tuple[ChannelKey, int], None] = OrderedDict()
        self.last_t: dict[ChannelKey, datetime] = {}

    def _reject(self, rej: list[TelemetryRejection], i: int, code: str, msg: str) -> None:
        rej.append(TelemetryRejection(index=i, code=code, message=msg))

    def ingest(self, batch: TelemetryBatch) -> TelemetryAccepted:
        now = self.clock()
        rej: list[TelemetryRejection] = []
        accepted = 0
        if len(batch.records) > MAX_BATCH:
            raise BatchTooLarge(f"batch of {len(batch.records)} records exceeds the limit of {MAX_BATCH}")
        owner = access.principal.get()
        allowed, authorization_error = _vessel_authorization(owner)
        with self.lock:
            for i, r in enumerate(batch.records):
                if authorization_error:
                    self._reject(rej, i, *authorization_error)
                    continue
                if allowed is not None and r.vessel_id not in allowed:
                    self._reject(rej, i, "VESSEL_NOT_AUTHORIZED", "An explicitly authorized vessel_id is required")
                    continue
                channel = f"ship_nmea:{(r.sentence or '')[3:6]}" if r.source == "ship_nmea" else f"{r.source}:{r.sensor_id}"
                key = (owner, r.vessel_id, channel)
                code_msg = self._check(r, now, key)
                if code_msg:
                    self._reject(rej, i, *code_msg)
                    continue
                if key not in self.latest and len(self.latest) >= MAX_CHANNELS:
                    self._reject(rej, i, "CHANNEL_LIMIT", "Telemetry channel capacity is exhausted")
                    continue
                adopted = self._adopt(r, now)
                self.latest[key] = adopted
                self.history.setdefault(key, deque(maxlen=HISTORY)).append(adopted)
                self.last_t[key] = r.t_utc
                if r.seq is not None:
                    self.seen[(key, r.seq)] = None
                    if len(self.seen) > SEEN_LIMIT:
                        self.seen.popitem(last=False)
                accepted += 1
        return TelemetryAccepted(accepted=accepted, rejected=len(rej), errors=[f"record {x.index}: {x.code}: {x.message}" for x in rej], rejections=rej)

    # ----- checks -----
    def _check(self, r: TelemetryRecord, now: datetime, key: ChannelKey) -> tuple[str, str] | None:
        t = r.t_utc if r.t_utc.tzinfo else None
        if t is None:
            return "NAIVE_TIMESTAMP", "t_utc needs a timezone"
        if (t - now).total_seconds() > MAX_SKEW_FUTURE_S:
            return "FUTURE_TIMESTAMP", f"event time is more than {MAX_SKEW_FUTURE_S:g} s in the future"
        if (now - t).total_seconds() > MAX_AGE_S:
            return "STALE_RECORD", f"event time is more than {MAX_AGE_S:g} s old"
        if r.source == "ship_nmea":
            if not r.sentence:
                return "MISSING_SENTENCE", "ship_nmea records need a sentence"
            try:
                nmea.decode(r.sentence)
            except nmea.NmeaError as e:
                return e.code, str(e)
            return self._order(r, key, t)
        if r.source == "load_cell":
            return self._load_cell(r, t, now, key)
        if r.source == "ais":
            return "AIS_UNSUPPORTED", "AIS decoding is not supported"
        return "UNKNOWN_SOURCE", f"unknown source {r.source!r}"

    def _order(self, r: TelemetryRecord, key: ChannelKey, t: datetime) -> tuple[str, str] | None:
        if r.seq is not None:
            if (key, r.seq) in self.seen:
                return "DUPLICATE_OR_REPLAY", f"sequence {r.seq} already received on {key}"
        last = self.last_t.get(key)
        if last is not None and t < last:
            return "OUT_OF_ORDER", f"{t.isoformat()} is older than the last accepted reading {last.isoformat()} on {key}"
        return None

    def _load_cell(self, r: TelemetryRecord, t: datetime, now: datetime, key: ChannelKey):
        if r.sensor_id is None or r.vessel_id is None or r.tension_lbf is None or r.calibration_rev is None:
            return "MISSING_FIELDS", "load_cell records need sensor_id, vessel_id, calibration_rev and tension_lbf"
        s = self.sensors.get(r.sensor_id)
        if s is None:
            return "UNKNOWN_SENSOR", f"sensor {r.sensor_id!r} is not registered"
        if r.vessel_id != s.vessel_id:
            return "WRONG_VESSEL", f"sensor {s.sensor_id} belongs to {s.vessel_id}, not {r.vessel_id}"
        if r.line_number is not None and r.line_number != s.line_number:
            return "WRONG_CHANNEL", f"sensor {s.sensor_id} is on line {s.line_number}, not {r.line_number}"
        if r.units != "lbf":
            return "BAD_UNITS", f"units {r.units!r}; only 'lbf' is accepted (no silent conversion)"
        if r.calibration_rev != s.calibration_rev:
            return "CALIBRATION_MISMATCH", f"reading is under calibration {r.calibration_rev}, registry has {s.calibration_rev}"
        if not s.calibration_valid_from <= t <= s.calibration_valid_until:
            return "CALIBRATION_EXPIRED", "reading time is outside the calibration validity period"
        if not (s.min_lbf <= r.tension_lbf <= s.max_lbf):
            return "OUT_OF_BOUNDS", f"{r.tension_lbf:g} lbf is outside [{s.min_lbf:g}, {s.max_lbf:g}]"
        return self._order(r, key, t)

    def _adopt(self, r: TelemetryRecord, now: datetime):
        if r.source == "ship_nmea":
            decoded = nmea.decode(r.sentence)
            return Adopted(r.model_copy(update={"received_utc": now}), now, "good", f"NMEA 0183 {r.sentence[3:6]} checksum verified", decoded)
        s = self.sensors[r.sensor_id]
        return Adopted(r.model_copy(update={"received_utc": now}), now, "good", f"sensor {s.sensor_id} calibration {s.calibration_rev}")


class BatchTooLarge(ValueError):
    pass


# ---------- arbitration ----------

PRIORITY = {"scenario": 0, "manual": 0, "forecast": 1, "observation": 2}   # lower wins; sensor readings never outrank a forecast


@dataclass
class Candidate:
    kind: str                       # scenario | manual | forecast | observation
    snapshot: EnvironmentSnapshot
    qualified: bool = True
    age_s: float = 0.0
    quality: str = "good"
    label: str = ""


@dataclass
class Decision:
    chosen: Candidate | None
    notes: list[str] = field(default_factory=list)


def arbitrate(candidates: list[Candidate], *, max_age_s: float = MAX_AGE_S, wind_tolerance_kt: float = 5.0) -> Decision:
    """Pick the environment a consumer may use. Rejected candidates are listed with the reason and cannot influence it."""
    notes, usable = [], []
    for c in candidates:
        if c.kind not in PRIORITY:
            notes.append(f"{c.label or c.kind}: unknown source kind, rejected")
        elif c.kind == "observation" and (c.age_s > max_age_s or c.quality != "good"):
            notes.append(f"{c.label or c.kind}: rejected ({'stale' if c.age_s > max_age_s else 'quality ' + c.quality})")
        elif c.kind == "forecast" and not c.qualified:
            notes.append(f"{c.label or c.kind}: unqualified forecast, rejected")
        else:
            usable.append(c)
    if not usable:
        return Decision(None, notes + ["no usable source"])
    best = min(usable, key=lambda c: (PRIORITY[c.kind], c.age_s))
    for c in usable:
        if c is not best and abs(c.snapshot.wind_speed_kt - best.snapshot.wind_speed_kt) > wind_tolerance_kt:
            notes.append(f"conflict: {c.label or c.kind} wind {c.snapshot.wind_speed_kt:.0f} kt vs chosen {best.label or best.kind} {best.snapshot.wind_speed_kt:.0f} kt; "
                         f"the higher-priority source was kept")
    return Decision(best, notes)


DEFAULT = Ingest()


def ingest(batch: TelemetryBatch) -> TelemetryAccepted:
    return DEFAULT.ingest(batch)
