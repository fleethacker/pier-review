"""Storyboard assembly and GeoJSON export."""

from mooring.core.schemas.common import Validity, ValidityReason
from mooring.core.schemas.missions import Storyboard, StoryboardEvent, TrackStats

from . import store
from .geo import NM_M
from .locate import TrackIndex, locate


def _stats(ix: TrackIndex, max_gap: float) -> TrackStats:
    n = len(ix)
    return TrackStats(fix_count=n, start_utc=ix.fix(0).t_utc if n else None, end_utc=ix.fix(n - 1).t_utc if n else None,
                      duration_s=(ix.t[-1] - ix.t[0]) / 1e6 if n else 0.0, distance_nm=ix.cum_m[-1] / NM_M if n else 0.0,
                      max_gap_s=ix.max_gap_s(), gaps_over_limit=len(ix.gaps(max_gap)))


def build_events(mission_id: str, ix: TrackIndex, max_gap: float, prefix: str) -> list[StoryboardEvent]:
    events: list[StoryboardEvent] = []
    for m, caveats in store.media_records(mission_id, prefix):
        stated = (m.exif_lat, m.exif_lon) if m.exif_lat is not None and m.exif_lon is not None else None
        events.append(StoryboardEvent(
            kind="image", event_id=m.media_id, t_utc=m.captured_utc, title=m.caption or m.filename, media_url=m.url,
            tags=m.tags, located=locate(ix, m.captured_utc, max_gap, stated=stated, stated_source="exif" if stated else None,
                                        time_caveats=caveats, component=m.media_id)))
    for r in store.list_reports(mission_id):
        stated = (r.lat, r.lon) if r.lat is not None else None
        events.append(StoryboardEvent(
            kind="report", event_id=r.report_id, t_utc=r.t_utc, title=r.title, body=r.body or None, tags=r.tags,
            located=locate(ix, r.t_utc, max_gap, stated=stated, stated_source="report" if stated else None,
                           component=r.report_id)))
    events.sort(key=lambda e: (e.t_utc is None, e.t_utc.timestamp() if e.t_utc else 0.0, e.kind, e.event_id))
    return events


def aggregate_validity(events: list[StoryboardEvent], stats: TrackStats) -> Validity:
    by_code: dict[str, ValidityReason] = {}
    for e in events:
        for r in e.located.validity.reasons:
            cur = by_code.setdefault(r.code, ValidityReason(code=r.code, message=r.message, affected_components=[]))
            cur.affected_components.extend(c for c in r.affected_components if c not in cur.affected_components)
    reasons = list(by_code.values())
    if stats.fix_count == 0:
        reasons.insert(0, ValidityReason(code="NO_TRACK", message="The mission has no recorded track."))
    elif stats.gaps_over_limit:
        reasons.insert(0, ValidityReason(code="TRACK_GAPS_OVER_LIMIT", message=(
            f"The track has {stats.gaps_over_limit} gap(s) longer than the interpolation limit; the largest is "
            f"{stats.max_gap_s:.0f} s. Positions inside those gaps are not established.")))
    return Validity(state="limited", reasons=reasons) if reasons else Validity(state="valid")


def build(mission_id: str, max_interp_gap_s: float, max_points: int, prefix: str) -> Storyboard:
    mission = store.get_mission(mission_id)
    ix = store.load_index(mission_id)
    stats = _stats(ix, max_interp_gap_s)
    events = build_events(mission_id, ix, max_interp_gap_s, prefix)
    keep = store.decimate(ix, max_points, _gap_endpoints(ix, max_interp_gap_s))
    return Storyboard(mission=mission, max_interp_gap_s=max_interp_gap_s, stats=stats, track=[ix.fix(i) for i in keep],
                      events=events, validity=aggregate_validity(events, stats))


def _gap_endpoints(ix: TrackIndex, limit: float) -> list[int]:
    """Gap boundary indices, longest gap first so the budget keeps the most significant ones."""
    gaps = sorted(ix.gaps(limit), key=lambda i: ix.t[i] - ix.t[i + 1])
    return [k for i in gaps for k in (i, i + 1)]


def _iso(us_t) -> str:
    from .geo import from_us
    return from_us(us_t).isoformat().replace("+00:00", "Z")


def geojson(mission_id: str, max_interp_gap_s: float, prefix: str) -> dict:
    mission = store.get_mission(mission_id)
    ix = store.load_index(mission_id)
    stats = _stats(ix, max_interp_gap_s)
    events = build_events(mission_id, ix, max_interp_gap_s, prefix)
    features, cuts, start = [], [*ix.gaps(max_interp_gap_s), len(ix) - 1], 0
    for seg, end in enumerate(cuts if len(ix) else []):
        idx = range(start, end + 1)
        start = end + 1
        times = [_iso(ix.t[i]) for i in idx]
        base = {"kind": "track", "segment": seg, "start_utc": times[0], "end_utc": times[-1]}
        if len(idx) >= 2:
            geom = {"type": "LineString", "coordinates": [[ix.lon[i], ix.lat[i]] for i in idx]}
            features.append({"type": "Feature", "geometry": geom, "properties": {**base, "times": times}})
        else:  # a lone fix between two gaps has no line; keep it as a timed point
            i = idx[0]
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [ix.lon[i], ix.lat[i]]},
                             "properties": {**base, "kind": "track_point", "time": times[0]}})
    unlocated = []
    for e in events:
        t = e.t_utc.isoformat().replace("+00:00", "Z") if e.t_utc else None
        if e.located.lat is None:
            unlocated.append({"kind": e.kind, "id": e.event_id, "t_utc": t, "method": e.located.method, "title": e.title})
            continue
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [e.located.lon, e.located.lat]},
                         "properties": {"kind": e.kind, "id": e.event_id, "t_utc": t, "method": e.located.method,
                                        "title": e.title, "media_url": e.media_url,
                                        "validity": e.located.validity.state}})
    return {"type": "FeatureCollection", "features": features,
            "properties": {"mission_id": mission_id, "name": mission.name, "max_interp_gap_s": max_interp_gap_s,
                           "fix_count": stats.fix_count, "unlocated_events": unlocated,
                           "validity": aggregate_validity(events, stats).model_dump(mode="json")}}
