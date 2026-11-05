"""Ready-made transit requests. DEMONSTRATION routes only: demonstration route checked only against the OSM coastline; not a
navigational route. The waypoints follow the water of Thimble Shoal Channel -> Hampton Roads -> the Norfolk Harbor Entrance Reach
toward Sewells Point, then a final point off the NAVSTA Norfolk Pier 12 north face from the berth catalog. They were laid out
by hand against an OpenStreetMap-derived land polygon (modeling/tests/fixtures/transit/hampton_roads_coastline.geojson, built by
scripts/fetch_transit_coastline.py, ODbL) and test_s6_presets_coastline.py checks that no leg crosses that land; they are not the charted
channel centrelines, depths, bridges or traffic lanes. Speeds are illustrative. Propulsion uses the labeled class defaults."""

from __future__ import annotations

import math

from mooring import refdata
from mooring.core.schemas import (
    AutopilotSettings,
    TransitPreset,
    TransitRequest,
    TransitStart,
    TransitWaypoint,
    TugAssistSettings,
    Validity,
    ValidityReason,
    VesselTransit,
)

from .geo import LocalPlane, bearing_deg

BERTH_ID = "NAVSTA-NORFOLK-P12-N"
APPROACH = [  # approximate water points, development only (see the module docstring)
    ("Thimble Shoal Channel entrance", 36.9950, -76.0450),
    ("Thimble Shoal Channel", 36.9950, -76.1600),
    ("Hampton Roads", 36.9850, -76.2700),
    ("Norfolk Harbor Entrance Reach", 36.9750, -76.3150),
    ("Off Sewells Point", 36.9690, -76.3300),
]
OFF_PIER_FT = 250.0
LABEL = "Demonstration route checked only against OSM coastline; not a navigational route; not navigational advice."


def pier_point(off_pier_ft: float = OFF_PIER_FT) -> tuple[float, float]:
    b = refdata.berth(BERTH_ID)
    plane = LocalPlane(b.origin_lat, b.origin_lon)
    ex, ey = math.radians(b.face_bearing_true_deg), math.radians(b.face_bearing_true_deg - 90.0)
    x = b.face_length_ft / 2 * 0.3048
    y = off_pier_ft * 0.3048
    return plane.to_geo(x * math.sin(ex) + y * math.sin(ey), x * math.cos(ex) + y * math.cos(ey))


def _inbound(vessel_id, cls, dlat=0.0, mode="own_thrust", assist=None):
    pts = [(n, la + dlat, lo) for n, la, lo in APPROACH]
    plat, plon = pier_point()
    first, rest = pts[0], pts[1:]
    speeds = [12.0, 12.0, 12.0, 10.0]
    route = [TransitWaypoint(lat=la, lon=lo, name=n, speed_kt=s) for (n, la, lo), s in zip(rest, speeds)]
    route.append(TransitWaypoint(lat=plat, lon=plon, name="Off NAVSTA Norfolk Pier 12 north face", speed_kt=6.0,
                                 acceptance_radius_ft=300.0))
    plane = LocalPlane(first[1], first[2])
    e, n_ = plane.to_local(rest[0][1], rest[0][2])
    return VesselTransit(vessel_id=vessel_id, ship_class_id=cls, loading="full_load",
                         start=TransitStart(lat=first[1], lon=first[2], heading_true_deg=bearing_deg(e, n_), speed_kt=10.0),
                         route=route, mode=mode, tug_assist=assist,
                         autopilot=AutopilotSettings(arrival_slowdown_nm=0.5, arrival_speed_kt=0.0))


def _outbound(vessel_id, cls, dlat=0.0):
    plat, plon = pier_point(OFF_PIER_FT)
    pts = [(n, la + dlat, lo) for n, la, lo in reversed(APPROACH)]
    plane = LocalPlane(plat, plon)
    e, n_ = plane.to_local(pts[0][1], pts[0][2])
    speeds = [8.0, 10.0, 10.0, 10.0, 10.0]
    route = [TransitWaypoint(lat=la, lon=lo, name=n, speed_kt=s) for (n, la, lo), s in zip(pts, speeds)]
    route[-1] = route[-1].model_copy(update={"name": "Thimble Shoal Channel entrance (to sea)", "acceptance_radius_ft": 1000.0})
    return VesselTransit(vessel_id=vessel_id, ship_class_id=cls, loading="full_load",
                         start=TransitStart(lat=plat, lon=plon, heading_true_deg=bearing_deg(e, n_), speed_kt=0.0),
                         route=route, mode="own_thrust",
                         autopilot=AutopilotSettings(arrival_slowdown_nm=0.0, arrival_speed_kt=10.0))


def _validity() -> Validity:
    return Validity(state="limited", reasons=[
        ValidityReason(code="TRANSIT_SURROGATE_MANEUVERING", message="Surrogate maneuvering model; not validated for any ship."),
        ValidityReason(code="PROPULSION_ASSUMED", message="Propulsion, rudder and tug response are labeled assumptions."),
        ValidityReason(code="DEMONSTRATION_ROUTE", message=LABEL)])


def presets() -> list[TransitPreset]:
    own = _inbound("DDG-A", "DDG-51-FIIA")
    assisted = _inbound("DDG-A", "DDG-51-FIIA", mode="tug_assisted",
                        assist=TugAssistSettings(policy="auto", tug_ids=["T1", "T2"], assist_below_kt=5.0))
    out = _outbound("DDG-A", "DDG-51-FIIA")
    two = [_inbound("DDG-IN", "DDG-51-FIIA", dlat=0.0007), _outbound("CG-OUT", "CG-47", dlat=-0.0007)]
    mk = lambda vs, dur: TransitRequest(vessels=vs, duration_s=dur, sample_interval_s=5.0)
    return [
        TransitPreset(preset_id="ddg-inbound-own-thrust", title="DDG-51 inbound to NAVSTA Norfolk Pier 12, own thrust",
                      description="From Thimble Shoal entrance to a point 250 ft off the Pier 12 north face, slowing over the last half mile. "
                                  + LABEL, request=mk([own], 6000), validity=_validity()),
        TransitPreset(preset_id="ddg-inbound-tug-assisted", title="DDG-51 inbound, tug-assisted final approach",
                      description="Same route; below 5 kt a bow and a stern tug (T1, T2) supply the turning moment the rudder cannot and brake. "
                                  + LABEL, request=mk([assisted], 6000), validity=_validity()),
        TransitPreset(preset_id="ddg-outbound-own-thrust", title="DDG-51 outbound from Pier 12 to sea, own thrust",
                      description="From the pier area to the Thimble Shoal entrance. " + LABEL, request=mk([out], 6600), validity=_validity()),
        TransitPreset(preset_id="two-vessels", title="Two vessels on one clock: DDG inbound, CG outbound",
                      description="Opposing traffic on laterally offset demonstration lanes; no ship-ship interaction is modeled. " + LABEL,
                      request=mk(two, 6600), validity=_validity()),
    ]
