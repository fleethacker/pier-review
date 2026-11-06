"""Offline full-hull route acceptance using actual public land/pier geometry.

NOAA shoreline geometry replaces the old transit test's near-pier exemption.
Outside its declared box, the existing OSM fixture supplies land geometry.
Neither dataset establishes navigable depth, traffic or operational approval.
"""
import json
import math
from pathlib import Path

import pytest
from shapely.geometry import LineString, Polygon, box, shape
from shapely.ops import transform, unary_union

from mooring import refdata
from mooring.berthing import motion_workspace as workspace
from mooring.data_simulation import motion_scenarios
from mooring.transit.geo import LocalPlane

NOAA_PATH = Path(motion_scenarios.__file__).parent / "data/norfolk_piers_shoreline.geojson"
NOAA = json.loads(NOAA_PATH.read_text())
OSM = json.loads((Path(__file__).parent / "fixtures/transit/hampton_roads_coastline.geojson").read_text())


def geometry(berth):
    p = LocalPlane(berth.origin_lat, berth.origin_lon)
    a = math.radians(berth.face_bearing_true_deg)
    def local(lon, lat):
        east, north = p.to_local(lat, lon)
        return ((east*math.sin(a)+north*math.cos(a))/.3048,
                (east*math.sin(a-math.pi/2)+north*math.cos(a-math.pi/2))/.3048)
    region = box(*NOAA["properties"]["bounds_wgs84"])
    coast = next(shape(f["geometry"]) for f in OSM["features"] if f["properties"]["kind"] == "land")
    hazards = [coast.difference(region), *(shape(f["geometry"]) for f in NOAA["features"])]
    return transform(local, unary_union(hazards)), local


def hull(state, ship):
    x, y, yaw = state[:3]
    return Polygon([(x+u*math.cos(yaw)-v*math.sin(yaw), y+u*math.sin(yaw)+v*math.cos(yaw))
                    for u,v in ((-ship.loa_ft/2,-ship.beam_ft/2),(ship.loa_ft/2,-ship.beam_ft/2),
                                (ship.loa_ft/2,ship.beam_ft/2),(-ship.loa_ft/2,ship.beam_ft/2))])


def test_source_is_actual_bounded_geographic_evidence_and_catches_the_old_route():
    assert len(NOAA["properties"]["response_sha256"]) == 64
    assert "NOAA" in NOAA["properties"]["attribution"]
    assert "Not for navigation" in NOAA["properties"]["limitations"]
    assert NOAA_PATH.stat().st_size < 100_000
    berth = refdata.berth(motion_scenarios.NORFOLK_BERTH)
    hazards, local = geometry(berth)
    old = LineString([local(-76.330,36.969), (berth.face_length_ft/2,900), (berth.face_length_ft/2,300)])
    assert old.intersects(hazards)
    route = motion_scenarios.norfolk_route(berth)
    assert not LineString([local(w.lon,w.lat) for w in route.waypoints]).intersects(hazards)


@pytest.mark.parametrize("class_id", motion_scenarios.DEMO_SHIPS)
def test_channel_to_pier_guidance_keeps_the_whole_hull_off_known_land(class_id):
    spec = workspace.catalog().presets[3].configuration.model_copy(deep=True)
    spec.ship_class_id, spec.controls, spec.dt_s = class_id, None, .2
    model = workspace.build_model(workspace.create_scenario(spec))
    hazards, _ = geometry(model.berth)
    previous = hull(model.integrator.state, model.ship)
    minimum = float("inf")
    for time in range(10, int(model.duration)+1, 10):
        model.advance(time)
        current = hull(model.integrator.state, model.ship)
        swept = previous.union(current).convex_hull
        distance = swept.distance(hazards)
        minimum = min(minimum, distance)
        assert distance > 10, (class_id, time, model.integrator.state, "known land/pier clearance", distance)
        assert not model.invalid
        previous = current
        if model.guidance.completed:
            break
    assert model.guidance.completed, (class_id, model.guidance.state(model.t,model.integrator.state))
    final = model.guidance.points[-1]
    assert math.hypot(model.integrator.state[0]-final.x_ft,model.integrator.state[1]-final.y_ft) < 90
    assert abs(math.degrees(model.integrator.state[2])) < 15
    assert math.hypot(*model.integrator.state[3:5]) < .25
    assert not any(e.kind == "contact_start" for e in model.transitions)
    assert model.validity().state == "limited"
    arrival = model.t
    for elapsed in range(10, 241, 10):
        model.advance(arrival+elapsed)
        current = hull(model.integrator.state, model.ship)
        assert current.distance(hazards) > 10
        assert math.hypot(model.integrator.state[0]-final.x_ft,model.integrator.state[1]-final.y_ft) < 40
    assert model.guidance.active and model.guidance.completed
