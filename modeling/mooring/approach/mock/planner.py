"""Mock approach route and under-keel clearance (M12, Phase 3).

A canned NAVSTA Norfolk route with approximate coordinates; Barrass squat. Workstream E replaces the route with
NOAA ENC geometry.
"""

import math
from datetime import timedelta

from mooring import refdata
from mooring.core.envelopes import envelope
from mooring.core.schemas import LatLon, RouteRequest, RouteResponse, RouteResult, TimeWindow, UkcLeg, UkcRequest, UkcResponse, UkcResult, Waypoint
from mooring import environment
from mooring.loads import mean_draft_ft

ROUTE = [  # approximate, for development only
    ("Thimble Shoal Channel entrance", 36.9590, -76.0450, 55.0, 1000.0),
    ("Thimble Shoal Channel", 36.9660, -76.1600, 55.0, 1000.0),
    ("Hampton Roads", 36.9640, -76.2700, 50.0, 1500.0),
    ("NAVSTA approach", 36.9600, -76.3150, 45.0, 800.0),
]


def route(req: RouteRequest) -> RouteResponse:
    berth = refdata.berth(req.berth_id)
    wps = [Waypoint(lat=lat, lon=lon, leg_name=n, channel_depth_mllw_ft=d, width_ft=w) for n, lat, lon, d, w in ROUTE]
    wps.append(Waypoint(lat=berth.origin_lat, lon=berth.origin_lon, leg_name=f"Berth {berth.name}",
                        channel_depth_mllw_ft=min(p.depth_mllw_ft for p in berth.depth_profile), width_ft=400.0))
    if req.origin:
        wps.insert(0, Waypoint(lat=req.origin.lat, lon=req.origin.lon, leg_name="Origin",
                               channel_depth_mllw_ft=60.0, width_ft=2000.0))
    result = RouteResult(waypoints=wps, tug_rendezvous=LatLon(lat=36.9620, lon=-76.3000),
                         abort_points=[LatLon(lat=36.9650, lon=-76.2500), LatLon(lat=36.9620, lon=-76.3000)])
    return envelope(RouteResponse, model="mooring.approach.route", request=req, result=result, status="GREEN",
                    assumptions=["Mock route with approximate coordinates; real route from NOAA ENC."])


def leg_nm(a: Waypoint, b: Waypoint) -> float:
    dlat = (b.lat - a.lat) * 60
    dlon = (b.lon - a.lon) * 60 * math.cos(math.radians((a.lat + b.lat) / 2))
    return math.hypot(dlat, dlon)


def ukc(req: UkcRequest) -> UkcResponse:
    ship = refdata.ship(req.ship_class_id)
    draft = mean_draft_ft(ship, req.loading)
    t = req.eta_utc
    legs = []
    for i, (a, b) in enumerate(zip(req.waypoints, req.waypoints[1:])):
        v = req.speed_profile_kt[i] if i < len(req.speed_profile_kt) else req.speed_profile_kt[-1]
        squat = ship.block_coefficient * v**2 / 50 * 3.281  # Barrass, confined channel, metres -> feet
        wl = environment.synthetic(t, "forecast").water_level_mllw_ft
        ukc_ft = min(a.channel_depth_mllw_ft, b.channel_depth_mllw_ft) + wl - draft - squat
        status = "RED" if ukc_ft < 2 else "AMBER" if ukc_ft < 4 else "GREEN"
        legs.append(UkcLeg(leg_name=b.leg_name, min_ukc_ft=round(ukc_ft, 1), squat_ft=round(squat, 2),
                           water_level_ft=wl, status=status))
        t += timedelta(hours=leg_nm(a, b) / max(v, 0.5))
    overall = "RED" if any(l.status == "RED" for l in legs) else "AMBER" if any(l.status == "AMBER" for l in legs) else "GREEN"
    return envelope(UkcResponse, model="mooring.approach.ukc", request=req,
                    result=UkcResult(legs=legs, window=TimeWindow(earliest_utc=req.eta_utc - timedelta(hours=1),
                                                                  latest_utc=req.eta_utc + timedelta(hours=2))),
                    status=overall, assumptions=["Barrass squat (confined): Cb x V^2 / 50 m.", "Mock tide."])
