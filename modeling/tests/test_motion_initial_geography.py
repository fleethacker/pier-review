"""Offline initial-body acceptance against independently transformed NOAA evidence."""
import json
import math

import pytest
from shapely.geometry import Point, Polygon, shape
from shapely.ops import transform, unary_union

from modeling_api import state
from mooring import refdata
from mooring.berthing import motion_workspace as workspace, rich
from mooring.berthing.motion_prediction import snapshot_hash
from mooring.core.schemas import ShipState, SimControlMessage
from mooring.data_simulation.motion_scenarios import DEMO_SHIPS
from mooring.data_simulation.shoreline import SOURCE_PATH
from mooring.transit.geo import LocalPlane
from test_motion_workspace import P, client, scenario, session  # noqa: F401
from test_motion_workspace_state import observation


def known_features(berth):
    """Independent fixture conversion, separate from the production helper."""
    source = json.loads(SOURCE_PATH.read_text())
    plane = LocalPlane(berth.origin_lat, berth.origin_lon)
    a = math.radians(berth.face_bearing_true_deg)

    def local(lon, lat):
        east, north = plane.to_local(lat, lon)
        return ((east*math.sin(a)+north*math.cos(a))/.3048,
                (east*math.sin(a-math.pi/2)+north*math.cos(a-math.pi/2))/.3048)

    return transform(local, unary_union([shape(f["geometry"]) for f in source["features"]]))


def footprint(x, y, yaw, length, beam):
    return Polygon([(x+u*math.cos(yaw)-v*math.sin(yaw), y+u*math.sin(yaw)+v*math.cos(yaw))
        for u, v in ((-length/2, -beam/2), (length/2, -beam/2), (length/2, beam/2), (-length/2, beam/2))])


@pytest.mark.parametrize("class_id", DEMO_SHIPS)
@pytest.mark.parametrize("face", ["N", "S"])
@pytest.mark.parametrize("side", ["port", "starboard"])
@pytest.mark.parametrize("start", ["berth", "approach"])
@pytest.mark.parametrize("tugs", [[], ["T1"], ["T1", "T2"], None])
def test_authored_full_ship_and_tug_envelopes_avoid_known_features(class_id, face, side, start, tugs):
    spec = workspace.MotionWorkspaceSpec(name="geography matrix", ship_class_id=class_id,
        berth_id=f"NAVSTA-NORFOLK-P12-{face}", side_to=side, start=start, tug_ids=tugs)
    resolved = workspace.resolve_configuration(spec)
    ship, berth = refdata.ship(class_id), refdata.berth(spec.berth_id)
    pose = workspace.initial_state(resolved, ship, berth)
    hazards = known_features(berth)
    bodies = [(pose.x_ft, pose.y_ft, math.radians(berth.face_bearing_true_deg-pose.heading_true_deg),
               ship.loa_ft, ship.beam_ft)]
    bodies += [(c.initial_state.x_ft, c.initial_state.y_ft, math.radians(c.initial_state.yaw_deg),
                c.length_ft, c.beam_ft) for c in resolved.controls.tug_dynamics]
    assert all(not footprint(*body).intersects(hazards) for body in bodies)


@pytest.mark.parametrize("class_id", DEMO_SHIPS)
@pytest.mark.parametrize("endpoint", ["configuration", "scenarios"])
def test_old_north_approach_on_pier14_is_rejected_over_http(client, class_id, endpoint):
    spec = workspace.MotionWorkspaceSpec(name="old approach", ship_class_id=class_id, start="approach",
        initial_state=ShipState(x_ft=696, y_ft=900, heading_true_deg=99.5))
    response = client.post(P+"/"+endpoint, json=spec.model_dump(mode="json"))
    assert response.status_code == 422
    assert "footprint intersects known NOAA shoreline" in response.text


def test_hull_corner_on_pier_is_rejected_even_when_its_center_is_outside_land(client):
    berth = refdata.berth("NAVSTA-NORFOLK-P12-N")
    assert not Point(696, 5).intersects(known_features(berth))
    spec = workspace.MotionWorkspaceSpec(name="body straddles edge", ship_class_id="DDG-51-FIIA",
        tug_ids=[], initial_state=ShipState(x_ft=696, y_ft=5, heading_true_deg=99.5))
    response = client.post(P+"/configuration", json=spec.model_dump(mode="json"))
    assert response.status_code == 422 and "Initial ship footprint" in response.text


def test_supplied_tug_footprint_and_saved_row_reopen_cannot_bypass_validation(client):
    spec = workspace.resolve_configuration(workspace.MotionWorkspaceSpec(name="valid", ship_class_id="CG-47"))
    spec.controls.tug_dynamics[0].initial_state.x_ft = 696
    spec.controls.tug_dynamics[0].initial_state.y_ft = 900
    response = client.post(P+"/configuration", json=spec.model_dump(mode="json"))
    assert response.status_code == 422 and "Initial tug" in response.text
    saved = scenario(client, index=1, name="old saved row")
    row = workspace.get_scenario(saved["motion_scenario_id"])
    row.configuration.initial_state = ShipState(x_ft=696, y_ft=900, heading_true_deg=99.5)
    workspace.SCENARIOS[row.motion_scenario_id] = row
    response = client.post(P+"/sessions", json={"motion_scenario_id": row.motion_scenario_id})
    assert response.status_code == 422 and "Initial ship footprint" in response.text


@pytest.mark.parametrize("entity", ["ship", "tug"])
def test_import_rejects_known_shoreline_atomically(client, entity):
    created = session(client)
    sid = created["session"]["session_id"]
    runtime = state.SESSIONS[sid]
    before = snapshot_hash(runtime.model), runtime.run_id, runtime.sequence, runtime.recording_json()
    identifier = created["ship"]["class_id"] if entity == "ship" else runtime.model.tug_dynamics.ids[0]
    response = client.post(P+f"/sessions/{sid}/state", json=observation(created, entity=entity,
        entity_id=identifier, x_ft=696, y_ft=900, heading_true_deg=99.5))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "STATE_SHORELINE_INTERSECTION"
    assert (snapshot_hash(runtime.model), runtime.run_id, runtime.sequence, runtime.recording_json()) == before


def test_reset_returns_to_validated_authored_pose_after_import(client):
    created = session(client, index=1)
    sid = created["session"]["session_id"]
    runtime = state.SESSIONS[sid]
    initial = runtime.model.integrator.state
    assert initial[1] == 300
    assert client.post(P+f"/sessions/{sid}/state", json=observation(created)).status_code == 200
    runtime.attach("reset-test")
    runtime.receive("reset-test", SimControlMessage(type="reset"))
    runtime.detach("reset-test")
    assert runtime.model.integrator.state == initial
    assert runtime.model.motion_geography
    assert not footprint(*initial[:3], runtime.model.ship.loa_ft, runtime.model.ship.beam_ft).intersects(
        known_features(runtime.model.berth))


def test_scene_preserves_bounded_source_geometry_dimensions_and_unknown_coverage(client):
    created = session(client)
    scene = client.get(created["session"]["scene_url"]).json()
    source = json.loads(SOURCE_PATH.read_text())
    context = scene["geographic_context"]
    assert context["coverage"] == "partial" and context["runtime_collision_checks"] is False
    assert context["attribution"] == source["properties"]["attribution"]
    assert "unknown" in " ".join(context["limitations"])
    assert "not establish navigable" in " ".join(context["limitations"])
    pier12 = next(f for f in context["features"] if f["name"] == "Pier 12")
    assert pier12["geometry_type"] == "LineString" and len(pier12["rings"][0]) == 47
    assert pier12["rings"][0][0] != pier12["rings"][0][-1]
    assert pier12["source_date"] == "20030825" and scene["berth_outline"] == []
    assert len(scene["tug_dimensions"]) == 2
    assert all(t["length_ft"] == 90 and t["beam_ft"] == 32 and t["basis"] == "synthetic"
               for t in scene["tug_dimensions"])
    model = state.SESSIONS[created["session"]["session_id"]].model.clone_for_prediction()
    del model.motion_geography
    legacy = rich.build_scene(model).model_dump(mode="json")
    assert "geographic_context" not in legacy and "tug_dimensions" not in legacy


def test_outside_fixture_is_unknown_and_does_not_claim_safe_water(client):
    # The existing authored channel start is outside the tiny NOAA context box.
    created = session(client, index=3)
    scene = client.get(created["session"]["scene_url"]).json()
    context = scene["geographic_context"]
    runtime = state.SESSIONS[created["session"]["session_id"]]
    coverage = Polygon([(p["x_ft"], p["y_ft"]) for p in context["coverage_outline"]])
    assert not coverage.intersects(Point(*runtime.model.integrator.state[:2]))
    assert context["coverage"] == "partial" and created["session"]["validity"]["state"] == "limited"
    assert context["runtime_collision_checks"] is False
