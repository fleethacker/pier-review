"""Mock approach simulation (M12, Phase 3): straight-line track between waypoints, no maneuvering model yet."""

import math
from datetime import timedelta

from mooring import refdata
from mooring.core.envelopes import envelope
from mooring.core.schemas import ApproachSimRequest, ApproachSimResponse, ApproachSimResult, ApproachTrack, TrackPoint
from mooring import environment
from mooring.loads import mean_draft_ft

from .planner import leg_nm

TRACKS: dict[str, ApproachTrack] = {}


def simulate_approach(req: ApproachSimRequest, job_id: str, base_path: str) -> ApproachSimResponse:
    ship = refdata.ship(req.ship_class_id)
    draft = mean_draft_ft(ship, req.loading)
    pts, t_s = [], 0.0
    for i, (a, b) in enumerate(zip(req.waypoints, req.waypoints[1:])):
        v = req.speed_profile_kt[i] if i < len(req.speed_profile_kt) else req.speed_profile_kt[-1]
        hdg = math.degrees(math.atan2((b.lon - a.lon) * math.cos(math.radians(a.lat)), b.lat - a.lat)) % 360
        dur = leg_nm(a, b) / max(v, 0.5) * 3600
        for k in range(10):
            f = k / 10
            squat = ship.block_coefficient * v**2 / 50 * 3.281
            wl = environment.synthetic(req.eta_utc + timedelta(seconds=t_s + f * dur), "forecast").water_level_mllw_ft
            pts.append(TrackPoint(lat=a.lat + f * (b.lat - a.lat), lon=a.lon + f * (b.lon - a.lon), t_s=round(t_s + f * dur),
                                  heading_true_deg=round(hdg, 1), speed_kt=v, cross_track_ft=round(20 * math.sin(k), 1),
                                  ukc_ft=round(min(a.channel_depth_mllw_ft, b.channel_depth_mllw_ft) + wl - draft - squat, 1)))
        t_s += dur
    TRACKS[job_id] = ApproachTrack(job_id=job_id, points=pts)
    min_ukc = min(p.ukc_ft for p in pts) if pts else 0.0
    result = ApproachSimResult(track_url=f"{base_path}/approach/simulations/{job_id}/track",
                               max_cross_track_ft=max(abs(p.cross_track_ft) for p in pts) if pts else 0.0,
                               min_ukc_ft=min_ukc, events=[])
    return envelope(ApproachSimResponse, model="mooring.dynamics.approach", request=req, result=result,
                    status="RED" if min_ukc < 2 else "AMBER" if min_ukc < 4 else "GREEN",
                    assumptions=["Mock straight-line track between waypoints; no maneuvering model yet."])
