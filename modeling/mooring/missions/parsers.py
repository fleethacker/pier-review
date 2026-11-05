"""Track file parsers: CSV, GPX, NMEA 0183 (RMC/GGA) and GeoJSON.

Each parser returns a ParseResult. A bad record is rejected and counted with a line/record number, never repaired:
naive timestamps need `utc_offset_min`, out-of-range coordinates are rejected, invalid GPS fixes are rejected.
Nothing here touches storage.
"""

import csv
import io
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone

from mooring.core.schemas.missions import TrackFix

from .geo import KT_MS, to_utc

MAX_ERRORS = 50
MAX_EPOCH_S = 4_102_444_800  # 2100-01-01; larger numbers are almost certainly milliseconds
MIN_PLAUSIBLE_EPOCH_S = 946_684_800  # 2000-01-01: lower bound of the 10-digit plausibility rule
MAX_JSON_DEPTH = 64  # GeoJSON nesting beyond this is refused (real tracks nest about 6 deep)


class TrackParseError(ValueError):
    """The file as a whole cannot be read (wrong format, malformed container)."""


class TrackLimitError(ValueError):
    """The file holds more distinct fixes than a mission may hold (aborted during parsing)."""


@dataclass
class ParseResult:
    fixes: list[TrackFix] = field(default_factory=list)
    rejected: int = 0
    errors: list[str] = field(default_factory=list)
    max_fixes: int | None = None  # abort parsing once more distinct timestamps than this have been seen
    duplicates: int = 0  # same-timestamp fixes dropped at parse time (first kept) so memory stays bounded
    _seen: set = field(default_factory=set, repr=False)

    def add(self, fix: TrackFix) -> None:
        if fix.t_utc in self._seen:
            self.duplicates += 1
            return
        self._seen.add(fix.t_utc)
        if self.max_fixes is not None and len(self._seen) > self.max_fixes:
            raise TrackLimitError(f"a mission holds at most {self.max_fixes} fixes; the file has more distinct "
                                  f"timestamps than that (parsing stopped)")
        self.fixes.append(fix)

    def warn(self, message: str) -> None:
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(message)

    def reject(self, where: str, why: str) -> None:
        self.rejected += 1
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(f"{where}: {why}")


def quality_from_hdop(hdop: float | None) -> str:
    """good: HDOP <= 2.0; degraded: above; unknown: not recorded."""
    if hdop is None:
        return "unknown"
    return "good" if hdop <= 2.0 else "degraded"


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TrackParseError(f"file is not valid UTF-8 text ({exc.reason} at byte {exc.start})") from exc


_COMPACT = re.compile(r"(\d{4})(\d\d)(\d\d)[T ]?(\d\d)(\d\d)(\d\d)(\.\d+)?(Z|[+-]\d\d(?::?\d\d)?)?", re.I)
_NUMERIC = re.compile(r"\s*-?\d+(\.\d+)?\s*")


def _epoch(sec: float, shown) -> datetime:
    if not math.isfinite(sec) or sec < 0 or sec > MAX_EPOCH_S:
        raise ValueError(f"epoch seconds out of range ({str(shown)[:24]}); milliseconds are not accepted")
    return to_utc(datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=round(sec * 1e6)))


def _compact_iso(s: str, utc_offset_min: int | None) -> datetime | None:
    """YYYYMMDD[T]HHMMSS[.fff][Z|+hh[:mm]] (basic ISO-8601). None if `s` is not of that shape."""
    m = _COMPACT.fullmatch(s)
    if not m:
        return None
    y, mo, d, h, mi, sec = (int(m[i]) for i in range(1, 7))
    try:
        dt = datetime(y, mo, d, h, mi, sec, round(float(m[7] or 0) * 1e6))
    except ValueError as exc:
        raise ValueError(f"invalid compact date-time '{s[:24]}'") from exc
    z = m[8]
    if z is None:
        if utc_offset_min is None:
            raise ValueError(f"naive timestamp '{s[:24]}' and no utc_offset_min given")
        return dt.replace(tzinfo=timezone(timedelta(minutes=utc_offset_min)))
    if z.upper() == "Z":
        return dt.replace(tzinfo=UTC)
    digits = z[1:].replace(":", "")
    hh, mm = int(digits[:2]), int(digits[2:] or 0)
    if hh > 23 or mm > 59:
        raise ValueError(f"bad UTC offset in '{s[:24]}'")
    return dt.replace(tzinfo=timezone((1 if z[0] == "+" else -1) * timedelta(hours=hh, minutes=mm)))


def parse_time(value, utc_offset_min: int | None, *, epoch_column: bool = False) -> datetime:
    """Time -> aware UTC datetime within 1970..2100. Raises ValueError (never OverflowError).

    Accepted: ISO-8601 (naive needs utc_offset_min); compact ISO `YYYYMMDD[T]HHMMSS` with Z/offset or utc_offset_min;
    epoch seconds only (a) when the value is a JSON number, (b) in an explicitly named epoch column (`epoch`, `unix`,
    `time_s`, ...: `epoch_column=True`), or (c) as a plain 10-digit string (optional fraction) within 2000..2100.
    Other digit-only strings are never epoch seconds: 14 digits are compact ISO, 8 digits (a bare date) and 13 digits
    (milliseconds) are rejected.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError("missing time")
    if isinstance(value, (int, float)):
        return _epoch(float(value), value)
    s = str(value).strip()
    if not s:
        raise ValueError("missing time")
    if _NUMERIC.fullmatch(s):
        digits = s.lstrip("-").split(".")[0]
        if epoch_column:
            return _epoch(float(s), s)
        if len(digits) == 10:
            sec = float(s)
            if MIN_PLAUSIBLE_EPOCH_S <= sec < MAX_EPOCH_S:
                return _epoch(sec, s)
            raise ValueError(f"numeric time '{s[:24]}' is not plausible epoch seconds (2000..2100)")
        if "." not in s and len(digits) in (14,):
            dt = _compact_iso(s, utc_offset_min)
            if dt is not None:
                return to_utc(dt)
        if len(digits) == 13:
            raise ValueError(f"numeric time '{s[:24]}' looks like milliseconds; milliseconds are not accepted")
        raise ValueError(f"numeric time '{s[:24]}' is ambiguous; epoch seconds are accepted only in an explicit epoch "
                         f"column (epoch, unix, time_s) or as 10 digits")
    dt = _compact_iso(s, utc_offset_min)
    if dt is None:
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as exc:
            raise ValueError(f"unparseable time '{s[:40]}'") from exc
        if dt.tzinfo is None:
            if utc_offset_min is None:
                raise ValueError(f"naive timestamp '{s[:40]}' and no utc_offset_min given")
            dt = dt.replace(tzinfo=timezone(timedelta(minutes=utc_offset_min)))
    return to_utc(dt)


def _num(value, name, lo=None, hi=None, optional=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None
        raise ValueError(f"missing {name}")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a number ('{str(value)[:20]}')") from exc
    if not math.isfinite(x):
        raise ValueError(f"{name} is not finite")
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise ValueError(f"{name} {x} out of range")
    return x


def _angle(value, name):
    x = _num(value, name, 0.0, 360.0, optional=True)
    return None if x is None else (0.0 if x == 360.0 else x)


def make_fix(t: datetime, lat, lon, *, heading=None, cog=None, sog_kt=None, hdop=None, source: str) -> TrackFix:
    """Validate raw values and build a TrackFix. Raises ValueError with a readable message."""
    kw = dict(t_utc=t, lat=_num(lat, "lat", -90, 90), lon=_num(lon, "lon", -180, 180),
              heading_true_deg=_angle(heading, "heading"), cog_true_deg=_angle(cog, "cog"),
              sog_kt=_num(sog_kt, "sog", 0.0, optional=True), hdop=_num(hdop, "hdop", 0.0, optional=True))
    kw["quality"] = quality_from_hdop(kw["hdop"])
    # Every field was range-checked above, so per-row pydantic validation is skipped (it dominates the cost of a large
    # file). All fields are passed explicitly, which keeps the set of "set" fields identical to a validated model.
    return TrackFix.model_construct(source=source, **kw)


# ---------------------------------------------------------------- CSV

def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


_EPOCH_NAMES = {"epoch", "epoch_s", "epoch_sec", "epoch_time", "unix", "unix_s", "unix_time", "time_s"}
_ALIASES = {
    "time": {"time", "timestamp", "datetime", "date_time", "time_utc", "utc", "t_utc", "utc_time", "gps_time"} | _EPOCH_NAMES,
    "lat": {"lat", "latitude", "lat_deg", "latitude_deg"},
    "lon": {"lon", "lng", "long", "longitude", "lon_deg", "longitude_deg"},
    "heading": {"heading", "hdg", "heading_deg", "heading_true_deg", "hdt", "true_heading"},
    "cog": {"cog", "cog_deg", "cog_true_deg", "course", "course_over_ground"},
    "sog": {"sog", "sog_kt", "sog_kts", "sog_kn", "sog_knots", "speed_kt", "speed_kts", "speed_kn", "speed_knots", "knots"},
    "hdop": {"hdop"},
}


def parse_csv(data: bytes, utc_offset_min: int | None = None, max_fixes: int | None = None) -> ParseResult:
    """Header row required. Speeds are knots, angles degrees true. Time is ISO-8601, compact ISO, or epoch seconds
    (explicit epoch column or 10 digits; see parse_time). A bare `speed` column has no stated unit and is ignored
    with one warning; use sog, sog_kt, speed_kt, speed_kn or knots."""
    text = decode(data)
    lines = text.splitlines()
    head_no = next((i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")), None)
    if head_no is None:
        raise TrackParseError("CSV file is empty")
    sample = lines[head_no]
    delim = max(",;\t", key=sample.count) if any(d in sample for d in ",;\t") else ","
    reader = csv.reader(io.StringIO("\n".join(lines[head_no:])), delimiter=delim)
    header = next(reader)
    cols: dict[str, int] = {}
    epoch_col = False
    for i, h in enumerate(header):
        for key, names in _ALIASES.items():
            if _norm(h) in names and key not in cols:
                cols[key] = i
                if key == "time":
                    epoch_col = _norm(h) in _EPOCH_NAMES
    missing = [k for k in ("time", "lat", "lon") if k not in cols]
    if missing:
        raise TrackParseError(f"CSV header (line {head_no + 1}) lacks a recognised column for: {', '.join(missing)}")
    out = ParseResult(max_fixes=max_fixes)
    if "sog" not in cols and any(_norm(h) == "speed" for h in header):
        out.warn("column 'speed' ignored: its unit is not stated; name it sog, sog_kt, speed_kt, speed_kn or knots (knots)")
    for row in reader:
        lineno = head_no + reader.line_num
        if not row or all(not c.strip() for c in row) or row[0].lstrip().startswith("#"):
            continue
        def cell(k):
            i = cols.get(k)
            return row[i] if i is not None and i < len(row) else None
        try:
            if len(row) < max(cols.values()) + 1:
                raise ValueError(f"expected at least {max(cols.values()) + 1} columns, found {len(row)}")
            t = parse_time(cell("time"), utc_offset_min, epoch_column=epoch_col)
            fix = make_fix(t, cell("lat"), cell("lon"), heading=cell("heading"), cog=cell("cog"),
                           sog_kt=cell("sog"), hdop=cell("hdop"), source="csv")
        except ValueError as exc:
            out.reject(f"line {lineno}", str(exc))
            continue
        out.add(fix)
    return out


# ---------------------------------------------------------------- GPX

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


_BOMS = (b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00")
_XML_ENC = re.compile(rb"""<\?xml[^>]{0,300}?encoding\s*=\s*["']([A-Za-z0-9._:-]+)["']""", re.I)


def _gpx_text(data: bytes) -> str:
    """Only UTF-8 GPX is accepted (so the DOCTYPE/ENTITY check below sees exactly what the XML parser will see)."""
    if data.startswith(_BOMS) or (len(data) >= 4 and b"\x00" in data[:4]):
        raise TrackParseError("GPX must be UTF-8; UTF-16/UTF-32 input is refused")
    m = _XML_ENC.search(data[:512])
    if m and m[1].lower().replace(b"_", b"-") not in (b"utf-8", b"utf8"):
        raise TrackParseError(f"GPX must be UTF-8; declared encoding '{m[1].decode('ascii')[:20]}' is refused")
    return decode(data)


def parse_gpx(data: bytes, utc_offset_min: int | None = None, max_fixes: int | None = None) -> ParseResult:
    """trkpt, rtept and wpt with a <time>. Points without time are rejected. <speed> is m/s, <course> is COG.
    Input must be UTF-8 (BOM or XML declaration naming another encoding is refused) and must not contain
    `<!DOCTYPE` or `<!ENTITY` anywhere (case-insensitive); both are checked before any XML parsing."""
    text = _gpx_text(data)
    low = text.lower()
    if "<!doctype" in low or "<!entity" in low:
        raise TrackParseError("GPX with a DOCTYPE or entity declaration is refused")
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise TrackParseError(f"GPX is not well-formed XML: {exc}") from exc
    if _local(root.tag) != "gpx":
        raise TrackParseError("root element is not <gpx>")
    out, n = ParseResult(max_fixes=max_fixes), 0
    for el in root.iter():
        kind = _local(el.tag)
        if kind not in ("trkpt", "rtept", "wpt"):
            continue
        n += 1
        child = {_local(c.tag): (c.text or "").strip() for c in el}
        where = f"{kind} #{n}"
        try:
            if not child.get("time"):
                raise ValueError("no <time>")
            t = parse_time(child["time"], utc_offset_min)
            speed = child.get("speed")
            sog = None if not speed else _num(speed, "speed", 0.0) / KT_MS
            fix = make_fix(t, el.get("lat"), el.get("lon"), cog=child.get("course") or None,
                           sog_kt=sog, hdop=child.get("hdop") or None, source="gpx")
        except ValueError as exc:
            out.reject(where, str(exc))
            continue
        out.add(fix)
    if n == 0:
        raise TrackParseError("GPX has no trkpt, rtept or wpt")
    return out


# ---------------------------------------------------------------- NMEA 0183

def nmea_checksum_ok(line: str) -> bool | None:
    """None if the sentence carries no checksum, else whether it matches."""
    if "*" not in line:
        return None
    body, _, tail = line[1:].partition("*")
    tail = tail.strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{2}", tail):  # exactly two hex digits, nothing else
        return False
    want = int(tail, 16)
    got = 0
    for ch in body:
        got ^= ord(ch)
    return got == want


def _latlon(v: str, hemi: str, deg_digits: int, name: str, neg: str, pos: str) -> float:
    if not v or not hemi:
        raise ValueError(f"empty {name}")
    if not re.fullmatch(rf"\d{{{deg_digits}}}\d\d\.\d+|\d{{{deg_digits}}}\d\d", v):
        raise ValueError(f"malformed {name} '{v}'")
    deg, minutes = int(v[:deg_digits]), float(v[deg_digits:])
    if minutes >= 60:
        raise ValueError(f"{name} minutes >= 60")
    if hemi not in (pos, neg):
        raise ValueError(f"bad hemisphere '{hemi}' for {name} (expected {pos} or {neg})")
    x = deg + minutes / 60
    return -x if hemi == neg else x


def _tod(v: str) -> timedelta:
    m = re.fullmatch(r"(\d\d)(\d\d)(\d\d)(\.\d+)?", v or "")
    if not m or int(m[1]) > 23 or int(m[2]) > 59 or int(m[3]) > 59:
        raise ValueError(f"malformed time '{v}'")
    return timedelta(hours=int(m[1]), minutes=int(m[2]), seconds=int(m[3]) + float(m[4] or 0))


def parse_nmea(data: bytes, nmea_date: date | None = None, max_fixes: int | None = None) -> ParseResult:
    """RMC (date, time, position, SOG, COG) and GGA (time, position, HDOP). Checksums are required (`*` plus exactly
    two hex digits) and verified.

    RMC status V is rejected, and so is any RMC whose mode indicator (field 12, when present) is not A (autonomous)
    or D (differential): E estimated, S simulator, M manual input and N not valid are refused. A missing mode field
    (pre-NMEA 2.3 talkers) is accepted. GGA quality 0 is rejected. Latitude must carry N/S and longitude E/W, and
    seconds must be 00..59. A GGA takes its date from the latest RMC, else `nmea_date`; with neither it is rejected.
    The date advances by one day whenever the time of day (from RMC or GGA) jumps back by more than 12 h, so a
    GGA-only file crossing midnight rolls over correctly. An RMC and a GGA with the same timestamp merge into one fix.
    """
    out = ParseResult(max_fixes=max_fixes)
    cur_date: date | None = nmea_date
    last_tod: timedelta | None = None
    by_time: dict[datetime, tuple[set[str], int]] = {}
    for lineno, raw in enumerate(decode(data).splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line[0] not in "$!":
            out.reject(f"line {lineno}", "not an NMEA sentence")
            continue
        kind = line[3:6] if line[0] == "$" and len(line) > 6 else ""
        if kind not in ("RMC", "GGA"):
            continue  # other sentences (and AIS) carry no fix we use
        try:
            ok = nmea_checksum_ok(line)
            if ok is None:
                raise ValueError("missing checksum")
            if not ok:
                raise ValueError("checksum mismatch")
            f = line[1:].partition("*")[0].split(",")
            if kind == "RMC":
                if len(f) < 10:
                    raise ValueError("too few fields")
                if f[2] != "A":
                    raise ValueError(f"RMC status '{f[2] or 'empty'}' (not a valid fix)")
                if len(f) > 12 and f[12] not in ("A", "D", ""):
                    raise ValueError(f"RMC mode '{f[12]}' (only A autonomous and D differential are accepted)")
                m = re.fullmatch(r"(\d\d)(\d\d)(\d\d)", f[9])
                if not m:
                    raise ValueError(f"malformed date '{f[9]}'")
                yy = int(m[3])
                try:
                    d = date(2000 + yy if yy < 80 else 1900 + yy, int(m[2]), int(m[1]))
                except ValueError as exc:
                    raise ValueError(f"invalid date '{f[9]}'") from exc
                tod = _tod(f[1])
                lat, lon = _latlon(f[3], f[4], 2, "latitude", "S", "N"), _latlon(f[5], f[6], 3, "longitude", "W", "E")
                extra = dict(sog_kt=f[7] or None, cog=f[8] or None)
                new_state = (d, tod)  # an RMC date is authoritative, but only once the sentence is accepted
            else:
                if len(f) < 9:
                    raise ValueError("too few fields")
                if f[6] in ("", "0"):
                    raise ValueError(f"GGA quality '{f[6] or 'empty'}' (no fix)")
                if f[6] not in ("1", "2", "3", "4", "5"):
                    raise ValueError(f"GGA quality '{f[6] or 'empty'}' is not a measured fix (accepted 1 GPS, 2 DGPS, "
                                     f"3 PPS, 4 RTK, 5 float RTK; 0 no fix, 6 estimated, 7 manual, 8 simulation refused)")
                tod = _tod(f[1])
                if cur_date is None:
                    raise ValueError("GGA has no date: no preceding RMC and no nmea_date")
                d = cur_date
                if last_tod is not None and tod < last_tod - timedelta(hours=12):
                    d = cur_date + timedelta(days=1)  # midnight crossed
                new_state = (d, tod)
                lat, lon = _latlon(f[2], f[3], 2, "latitude", "S", "N"), _latlon(f[4], f[5], 3, "longitude", "W", "E")
                extra = dict(hdop=f[8] or None)
            t = to_utc(datetime(d.year, d.month, d.day, tzinfo=UTC) + tod)
            fix = make_fix(t, lat, lon, source="nmea", **extra)
        except ValueError as exc:
            out.reject(f"line {lineno}", str(exc))
            continue
        cur_date, last_tod = new_state  # committed only for accepted sentences
        seen = by_time.get(t)
        if seen and kind not in seen[0]:
            seen[0].add(kind)
            prev = out.fixes[seen[1]]
            upd = {k: getattr(fix, k) for k in ("sog_kt", "cog_true_deg", "hdop") if getattr(prev, k) is None and getattr(fix, k) is not None}
            if upd:
                if "hdop" in upd:
                    upd["quality"] = quality_from_hdop(upd["hdop"])
                out.fixes[seen[1]] = prev.model_copy(update=upd)
            continue
        if not seen:
            by_time[t] = ({kind}, len(out.fixes))
        out.add(fix)
    return out


# ---------------------------------------------------------------- GeoJSON

_TIME_KEYS = ("time", "timestamp", "datetime")


def _props_extra(props: dict) -> dict:
    g = lambda *ks: next((props[k] for k in ks if props.get(k) is not None), None)
    return dict(heading=g("heading", "heading_true_deg", "hdg"), cog=g("cog", "cog_true_deg"),
                sog_kt=g("sog", "sog_kt", "speed_kt"), hdop=g("hdop"))


def _depth_ok(text: str) -> bool:
    """Cheap bracket-depth scan (ignoring brackets inside strings) so hostile nesting never reaches the JSON decoder."""
    depth = deepest = 0
    in_str = esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
            if depth > deepest:
                deepest = depth
                if deepest > MAX_JSON_DEPTH:
                    return False
        elif ch in "]}":
            depth -= 1
    return True


def parse_geojson(data: bytes, utc_offset_min: int | None = None, max_fixes: int | None = None) -> ParseResult:
    """Point features with a time/timestamp/datetime property; LineString (or MultiLineString) with per-vertex
    `coordTimes` or `times` (also `coordinateProperties.times`). Other geometries are ignored, as are the image/report
    event markers of this service's own storyboard export, so an export can be re-imported."""
    text = decode(data)
    if not _depth_ok(text):
        raise TrackParseError(f"GeoJSON is nested deeper than {MAX_JSON_DEPTH} levels")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TrackParseError(f"GeoJSON is not valid JSON: {exc}") from exc
    except RecursionError as exc:
        raise TrackParseError("GeoJSON is nested too deeply") from exc
    if not isinstance(doc, dict):
        raise TrackParseError("GeoJSON root must be an object")
    if doc.get("type") == "FeatureCollection":
        feats = doc.get("features")
        if not isinstance(feats, list):
            raise TrackParseError("FeatureCollection has no features array")
    elif doc.get("type") == "Feature":
        feats = [doc]
    else:
        raise TrackParseError("GeoJSON must be a FeatureCollection or Feature")
    out = ParseResult(max_fixes=max_fixes)

    def add(where, t, pos, props):
        try:
            if not isinstance(pos, list) or len(pos) < 2:
                raise ValueError("bad coordinates")
            fix = make_fix(parse_time(t, utc_offset_min), pos[1], pos[0], source="geojson", **_props_extra(props))
        except ValueError as exc:
            out.reject(where, str(exc))
            return
        out.add(fix)

    for fi, feat in enumerate(feats, 1):
        geom = (feat or {}).get("geometry") if isinstance(feat, dict) else None
        props = (feat.get("properties") or {}) if isinstance(feat, dict) else {}
        if not isinstance(geom, dict) or not isinstance(props, dict):
            out.reject(f"feature {fi}", "no geometry or properties")
            continue
        gt, coords = geom.get("type"), geom.get("coordinates")
        if props.get("kind") in ("image", "report"):
            continue  # storyboard event markers exported by this service are not track fixes
        if gt == "Point":
            t = next((props[k] for k in _TIME_KEYS if props.get(k) is not None), None)
            if t is None:
                out.reject(f"feature {fi}", "Point has no time property")
            else:
                add(f"feature {fi}", t, coords, props)
        elif gt in ("LineString", "MultiLineString"):
            times = next((props[k] for k in ("coordTimes", "times") if k in props), None)
            if times is None:
                times = (props.get("coordinateProperties") or {}).get("times") if isinstance(props.get("coordinateProperties"), dict) else None
            lines, tlines = ([coords], [times]) if gt == "LineString" else (coords, times)
            if not isinstance(lines, list) or not isinstance(tlines, list) or len(lines) != len(tlines):
                out.reject(f"feature {fi}", "LineString needs per-vertex coordTimes/times of matching shape")
                continue
            for li, (line, tl) in enumerate(zip(lines, tlines), 1):
                tag = f"feature {fi}" + (f" line {li}" if gt == "MultiLineString" else "")
                if not isinstance(line, list) or not isinstance(tl, list) or len(line) != len(tl):
                    out.reject(tag, f"{len(line) if isinstance(line, list) else '?'} coordinates but "
                                    f"{len(tl) if isinstance(tl, list) else 'no'} times")
                    out.rejected += max(0, (len(line) if isinstance(line, list) else 1) - 1)  # every vertex is a rejected record
                    continue
                for vi, (pos, t) in enumerate(zip(line, tl), 1):
                    add(f"{tag} vertex {vi}", t, pos, {})
    return out
