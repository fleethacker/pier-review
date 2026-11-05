"""Mission persistence in the process SQLite database (mooring.core.store.db()).

Missions are DocStore documents (ownership claimed on create). Fixes are rows keyed (mission_id, t_us), so the
primary key itself enforces "one fix per timestamp, first kept". Image bytes are SQLite BLOBs next to their metadata
(single-host durability, same file and backup as everything else). Tables are created lazily and idempotently.

Bounds: 200 000 fixes, 300 images (8 MB each), 5 000 reports per mission.
Every access goes through `require`, which answers refdata.NotFound for unknown and not-owned missions alike.
"""

import hashlib
import json
import re

from mooring import refdata
from mooring.core.envelopes import new_id, utcnow
from mooring.core.schemas.missions import (
    MediaItem,
    MediaMetadata,
    Mission,
    MissionCreate,
    MissionTrack,
    Report,
    ReportCreate,
    TrackFix,
    TrackIngestResult,
)
from mooring.core.store import DocStore, db

from . import exif
from .geo import TimeRangeError, decimate_indices, from_us, to_us
from .locate import TrackIndex

MAX_FIXES = 200_000
MAX_IMAGES = 300
MAX_REPORTS = 5_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mission_fixes (mission_id TEXT NOT NULL, t_us INTEGER NOT NULL, lat REAL NOT NULL,
  lon REAL NOT NULL, heading REAL, cog REAL, sog REAL, hdop REAL, quality TEXT NOT NULL, source TEXT,
  PRIMARY KEY (mission_id, t_us)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS mission_media (media_id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, meta TEXT NOT NULL,
  data BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS mission_media_m ON mission_media(mission_id);
CREATE TABLE IF NOT EXISTS mission_reports (report_id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, t_us INTEGER NOT NULL,
  body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS mission_reports_m ON mission_reports(mission_id);
"""


class LimitExceeded(ValueError):
    """A per-mission bound would be exceeded (HTTP 409)."""


def _d():
    d = db()
    if not getattr(d, "_missions_ready", False):
        with d.lock:
            d.conn.executescript(_SCHEMA)
            d._missions_ready = True
    return d


MISSIONS = DocStore("mission", Mission)


def require(mission_id: str) -> Mission:
    try:
        return MISSIONS[mission_id]
    except KeyError:
        raise refdata.NotFound(f"No mission '{mission_id}'") from None


def _with_counts(m: Mission) -> Mission:
    d = _d()
    mid = m.mission_id
    n, lo, hi = d.execute("SELECT COUNT(*), MIN(t_us), MAX(t_us) FROM mission_fixes WHERE mission_id=?", (mid,))[0]
    media = d.execute("SELECT COUNT(*) FROM mission_media WHERE mission_id=?", (mid,))[0][0]
    reports = d.execute("SELECT COUNT(*) FROM mission_reports WHERE mission_id=?", (mid,))[0][0]
    return m.model_copy(update=dict(fix_count=n, media_count=media, report_count=reports,
                                    start_utc=from_us(lo) if n else None, end_utc=from_us(hi) if n else None))


def create_mission(req: MissionCreate) -> Mission:
    _d()
    m = Mission(**req.model_dump(), mission_id=new_id("mis"), created_at_utc=utcnow(), fix_count=0, media_count=0,
                report_count=0)
    MISSIONS[m.mission_id] = m
    return m


def get_mission(mission_id: str) -> Mission:
    return _with_counts(require(mission_id))


def list_missions() -> list[Mission]:
    return [_with_counts(MISSIONS[k]) for k in list(MISSIONS)]


# ---------------------------------------------------------------- track

def ingest(mission_id: str, fixes: list[TrackFix], rejected: int, errors: list[str], fmt: str,
           parse_duplicates: int = 0) -> TrackIngestResult:
    """Merge parsed fixes into the mission. Duplicates (same timestamp, already present or earlier in the batch) are
    dropped keeping the first; `reordered` counts fixes earlier in time than the one received just before."""
    require(mission_id)
    d = _d()
    try:
        ts = [to_us(f.t_utc) for f in fixes]  # TimeRangeError (ValueError) outside 1970..2100
    except TimeRangeError as exc:
        raise TimeRangeError(f"fix time rejected: {exc}") from exc
    reordered = sum(1 for a, b in zip(ts, ts[1:]) if b < a)
    rows = [(mission_id, tu, f.lat, f.lon, f.heading_true_deg, f.cog_true_deg, f.sog_kt, f.hdop, f.quality,
             f.source) for tu, f in zip(ts, fixes)]
    with d.lock:
        d.conn.execute("BEGIN IMMEDIATE")
        try:
            before = d.conn.total_changes
            d.conn.executemany("INSERT OR IGNORE INTO mission_fixes VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            accepted = d.conn.total_changes - before
            total = d.conn.execute("SELECT COUNT(*) FROM mission_fixes WHERE mission_id=?", (mission_id,)).fetchone()[0]
            if total > MAX_FIXES:
                raise LimitExceeded(f"a mission holds at most {MAX_FIXES} fixes; this upload would make {total}")
            d.conn.execute("COMMIT")
        except BaseException:
            d.conn.execute("ROLLBACK")
            raise
    m = get_mission(mission_id)
    return TrackIngestResult(mission_id=mission_id, format=fmt, accepted=accepted, rejected=rejected,
                             duplicates=len(rows) - accepted + parse_duplicates, reordered=reordered, errors=errors[:50],
                             fix_count=m.fix_count, start_utc=m.start_utc, end_utc=m.end_utc)


def load_index(mission_id: str) -> TrackIndex:
    require(mission_id)
    rows = _d().execute("SELECT t_us,lat,lon,heading,cog,sog,hdop,quality,source FROM mission_fixes "
                        "WHERE mission_id=? ORDER BY t_us", (mission_id,))
    return TrackIndex.from_rows(rows)


def decimate(index: TrackIndex, max_points: int, forced: list[int] | None = None) -> list[int]:
    return decimate_indices(index.lat, index.lon, max_points, forced)


def get_track(mission_id: str, max_points: int) -> MissionTrack:
    ix = load_index(mission_id)
    keep = decimate(ix, max_points)
    return MissionTrack(mission_id=mission_id, fix_count=len(ix), decimated=len(keep) < len(ix),
                        fixes=[ix.fix(i) for i in keep])


# ---------------------------------------------------------------- media

def _safe_name(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()[:200]
    return base or "image"


def media_url(prefix: str, mission_id: str, media_id: str) -> str:
    return f"{prefix}/missions/{mission_id}/media/{media_id}"


def add_media(mission_id: str, filename: str | None, data: bytes, meta: MediaMetadata, prefix: str) -> MediaItem:
    require(mission_id)
    if meta.captured_utc is not None and meta.camera_clock_offset_s:
        raise exif.ImageError(422, "camera_clock_offset_s corrects the camera clock and cannot be combined with captured_utc")
    ctype = exif.validate_image(data)
    info = exif.extract_exif(data)
    rt = exif.resolve_time(info, meta)
    item = MediaItem(media_id=new_id("img"), mission_id=mission_id, filename=_safe_name(filename), content_type=ctype,
                     bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), captured_utc=rt.captured_utc,
                     time_source=rt.source, time_note=rt.note, camera_clock_offset_s=meta.camera_clock_offset_s,
                     exif_lat=info.lat, exif_lon=info.lon, caption=meta.caption, tags=meta.tags, url="")
    item = item.model_copy(update={"url": media_url(prefix, mission_id, item.media_id)})
    d = _d()
    with d.lock:
        n = d.execute("SELECT COUNT(*) FROM mission_media WHERE mission_id=?", (mission_id,))[0][0]
        if n >= MAX_IMAGES:
            raise LimitExceeded(f"a mission holds at most {MAX_IMAGES} images")
        d.conn.execute("INSERT INTO mission_media VALUES (?,?,?,?)",
                       (item.media_id, mission_id, json.dumps({"item": item.model_dump(mode="json"), "caveats": rt.caveats}), data))
    return item


def media_records(mission_id: str, prefix: str) -> list[tuple[MediaItem, list[str]]]:
    require(mission_id)
    out = []
    for (meta,) in _d().execute("SELECT meta FROM mission_media WHERE mission_id=? ORDER BY rowid", (mission_id,)):
        j = json.loads(meta)
        item = MediaItem.model_validate(j["item"])
        out.append((item.model_copy(update={"url": media_url(prefix, mission_id, item.media_id)}), j["caveats"]))
    return out


def list_media(mission_id: str, prefix: str) -> list[MediaItem]:
    return [m for m, _ in media_records(mission_id, prefix)]


def media_bytes(mission_id: str, media_id: str) -> tuple[str, bytes]:
    require(mission_id)
    rows = _d().execute("SELECT meta, data FROM mission_media WHERE media_id=? AND mission_id=?", (media_id, mission_id))
    if not rows:
        raise refdata.NotFound(f"No image '{media_id}' in mission '{mission_id}'")
    return json.loads(rows[0][0])["item"]["content_type"], bytes(rows[0][1])


# ---------------------------------------------------------------- reports

def add_report(mission_id: str, req: ReportCreate) -> Report:
    require(mission_id)
    r = Report(**req.model_dump(), report_id=new_id("rpt"), mission_id=mission_id)
    t_us = to_us(r.t_utc)  # TimeRangeError (ValueError) outside 1970..2100
    d = _d()
    with d.lock:
        if d.execute("SELECT COUNT(*) FROM mission_reports WHERE mission_id=?", (mission_id,))[0][0] >= MAX_REPORTS:
            raise LimitExceeded(f"a mission holds at most {MAX_REPORTS} reports")
        d.conn.execute("INSERT INTO mission_reports VALUES (?,?,?,?)",
                       (r.report_id, mission_id, t_us, r.model_dump_json()))
    return r


def list_reports(mission_id: str) -> list[Report]:
    require(mission_id)
    return [Report.model_validate_json(b) for (b,) in
            _d().execute("SELECT body FROM mission_reports WHERE mission_id=? ORDER BY t_us, rowid", (mission_id,))]
