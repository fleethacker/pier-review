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

from pydantic import ValidationError

from mooring.core.schemas.missions import TrackFix

from .geo import KT_MS

MAX_ERRORS = 50
MAX_EPOCH_S = 4_102_444_800  # 2100-01-01; larger numbers are almost certainly milliseconds


class TrackParseError(ValueError):
    """The file as a whole cannot be read (wrong format, malformed container)."""


@dataclass
class ParseResult:
    fixes: list[TrackFix] = field(default_factory=list)
    rejected: int = 0
    errors: list[str] = field(default_factory=list)

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


def parse_time(value, utc_offset_min: int | None) -> datetime:
    """ISO-8601 or epoch seconds -> aware UTC datetime. Naive ISO needs utc_offset_min. Raises ValueError."""
    if isinstance(value, bool) or value is None:
        raise ValueError("missing time")
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", value)):
        sec = float(value)
        if not math.isfinite(sec) or sec < 0 or sec > MAX_EPOCH_S:
            raise ValueError(f"epoch seconds out of range ({value}); milliseconds are not accepted")
        return datetime.fromtimestamp(0, UTC) + timedelta(microseconds=round(sec * 1e6))
    s = str(value).strip()
    if not s:
        raise ValueError("missing time")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"unparseable time '{s[:40]}'") from exc
    if dt.tzinfo is None:
        if utc_offset_min is None:
            raise ValueError(f"naive timestamp '{s[:40]}' and no utc_offset_min given")
        dt = dt.replace(tzinfo=timezone(timedelta(minutes=utc_offset_min)))
    return dt.astimezone(UTC)


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
    try:
        return TrackFix(source=source, **kw)
    except ValidationError as exc:  # defensive: the checks above should have caught it
        raise ValueError(exc.errors()[0]["msg"]) from exc


# ---------------------------------------------------------------- CSV

def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


_ALIASES = {
    "time": {"time", "timestamp", "datetime", "date_time", "time_utc", "utc", "t_utc", "utc_time", "gps_time"},
    "lat": {"lat", "latitude", "lat_deg", "latitude_deg"},
    "lon": {"lon", "lng", "long", "longitude", "lon_deg", "longitude_deg"},
    "heading": {"heading", "hdg", "heading_deg", "heading_true_deg", "hdt", "true_heading"},
    "cog": {"cog", "cog_deg", "cog_true_deg", "course", "course_over_ground"},
    "sog": {"sog", "sog_kt", "sog_kts", "speed", "speed_kt", "speed_kts", "speed_knots", "sog_knots"},
    "hdop": {"hdop"},
}


def parse_csv(data: bytes, utc_offset_min: int | None = None) -> ParseResult:
    """Header row required. Speeds are knots, angles degrees true, time ISO-8601 or epoch seconds."""
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
    for i, h in enumerate(header):
        for key, names in _ALIASES.items():
            if _norm(h) in names and key not in cols:
                cols[key] = i
    missing = [k for k in ("time", "lat", "lon") if k not in cols]
    if missing:
        raise TrackParseError(f"CSV header (line {head_no + 1}) lacks a recognised column for: {', '.join(missing)}")
    out = ParseResult()
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
            t = parse_time(cell("time"), utc_offset_min)
            out.fixes.append(make_fix(t, cell("lat"), cell("lon"), heading=cell("heading"), cog=cell("cog"),
                                      sog_kt=cell("sog"), hdop=cell("hdop"), source="csv"))
        except ValueError as exc:
            out.reject(f"line {lineno}", str(exc))
    return out


# ---------------------------------------------------------------- GPX

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_gpx(data: bytes, utc_offset_min: int | None = None) -> ParseResult:
    """trkpt, rtept and wpt with a <time>. Points without time are rejected. <speed> is m/s, <course> is COG."""
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data[:65536].lower():
        raise TrackParseError("GPX with a DOCTYPE or entity declaration is refused")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise TrackParseError(f"GPX is not well-formed XML: {exc}") from exc
    if _local(root.tag) != "gpx":
        raise TrackParseError("root element is not <gpx>")
    out, n = ParseResult(), 0
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
            out.fixes.append(make_fix(t, el.get("lat"), el.get("lon"), cog=child.get("course") or None,
                                      sog_kt=sog, hdop=child.get("hdop") or None, source="gpx"))
        except ValueError as exc:
            out.reject(where, str(exc))
    if n == 0:
        raise TrackParseError("GPX has no trkpt, rtept or wpt")
    return out


# ---------------------------------------------------------------- NMEA 0183

def nmea_checksum_ok(line: str) -> bool | None:
    """None if the sentence carries no checksum, else whether it matches."""
    if "*" not in line:
        return None
    body, _, tail = line[1:].partition("*")
    try:
        want = int(tail.strip()[:2], 16)
    except ValueError:
        return False
    got = 0
    for ch in body:
        got ^= ord(ch)
    return got == want


def _latlon(v: str, hemi: str, deg_digits: int, name: str, neg: str) -> float:
    if not v or not hemi:
        raise ValueError(f"empty {name}")
    if not re.fullmatch(rf"\d{{{deg_digits}}}\d\d\.\d+|\d{{{deg_digits}}}\d\d", v):
        raise ValueError(f"malformed {name} '{v}'")
    deg, minutes = int(v[:deg_digits]), float(v[deg_digits:])
    if minutes >= 60:
        raise ValueError(f"{name} minutes >= 60")
    if hemi not in ("N", "S", "E", "W"):
        raise ValueError(f"bad hemisphere '{hemi}'")
    x = deg + minutes / 60
    return -x if hemi == neg else x


def _tod(v: str) -> timedelta:
    m = re.fullmatch(r"(\d\d)(\d\d)(\d\d)(\.\d+)?", v or "")
    if not m or int(m[1]) > 23 or int(m[2]) > 59 or int(m[3]) > 60:
        raise ValueError(f"malformed time '{v}'")
    return timedelta(hours=int(m[1]), minutes=int(m[2]), seconds=int(m[3]) + float(m[4] or 0))


def parse_nmea(data: bytes, nmea_date: date | None = None) -> ParseResult:
    """RMC (date, time, position, SOG, COG) and GGA (time, position, HDOP). Checksums are required and verified.

    RMC status V and mode N, and GGA quality 0, are rejected. A GGA takes its date from the preceding RMC, else
    `nmea_date`; with neither it is rejected. An RMC and a GGA with the same timestamp are merged into one fix.
    """
    out = ParseResult()
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
                if len(f) > 12 and f[12] == "N":
                    raise ValueError("RMC mode N (data not valid)")
                m = re.fullmatch(r"(\d\d)(\d\d)(\d\d)", f[9])
                if not m:
                    raise ValueError(f"malformed date '{f[9]}'")
                yy = int(m[3])
                try:
                    d = date(2000 + yy if yy < 80 else 1900 + yy, int(m[2]), int(m[1]))
                except ValueError as exc:
                    raise ValueError(f"invalid date '{f[9]}'") from exc
                tod = _tod(f[1])
                cur_date, last_tod = d, tod
                lat, lon = _latlon(f[3], f[4], 2, "latitude", "S"), _latlon(f[5], f[6], 3, "longitude", "W")
                extra = dict(sog_kt=f[7] or None, cog=f[8] or None)
            else:
                if len(f) < 9:
                    raise ValueError("too few fields")
                if f[6] in ("", "0"):
                    raise ValueError(f"GGA quality '{f[6] or 'empty'}' (no fix)")
                tod = _tod(f[1])
                if cur_date is None:
                    raise ValueError("GGA has no date: no preceding RMC and no nmea_date")
                d = cur_date + timedelta(days=1) if last_tod is not None and tod < last_tod - timedelta(hours=12) else cur_date
                lat, lon = _latlon(f[2], f[3], 2, "latitude", "S"), _latlon(f[4], f[5], 3, "longitude", "W")
                extra = dict(hdop=f[8] or None)
            t = datetime(d.year, d.month, d.day, tzinfo=UTC) + tod
            fix = make_fix(t, lat, lon, source="nmea", **extra)
        except ValueError as exc:
            out.reject(f"line {lineno}", str(exc))
            continue
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
        out.fixes.append(fix)
    return out


# ---------------------------------------------------------------- GeoJSON

_TIME_KEYS = ("time", "timestamp", "datetime")


def _props_extra(props: dict) -> dict:
    g = lambda *ks: next((props[k] for k in ks if props.get(k) is not None), None)
    return dict(heading=g("heading", "heading_true_deg", "hdg"), cog=g("cog", "cog_true_deg"),
                sog_kt=g("sog", "sog_kt", "speed_kt"), hdop=g("hdop"))


def parse_geojson(data: bytes, utc_offset_min: int | None = None) -> ParseResult:
    """Point features with a time/timestamp/datetime property; LineString (or MultiLineString) with per-vertex
    `coordTimes` or `times` (also `coordinateProperties.times`). Other geometries are ignored, as are the image/report
    event markers of this service's own storyboard export, so an export can be re-imported."""
    try:
        doc = json.loads(decode(data))
    except json.JSONDecodeError as exc:
        raise TrackParseError(f"GeoJSON is not valid JSON: {exc}") from exc
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
    out = ParseResult()

    def add(where, t, pos, props):
        try:
            if not isinstance(pos, list) or len(pos) < 2:
                raise ValueError("bad coordinates")
            out.fixes.append(make_fix(parse_time(t, utc_offset_min), pos[1], pos[0], source="geojson", **_props_extra(props)))
        except ValueError as exc:
            out.reject(where, str(exc))

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
