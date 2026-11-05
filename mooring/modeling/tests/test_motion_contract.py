"""RM0 wire compatibility and motion validity; no simulator physics is introduced here."""

import copy
import json
import math
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from modeling_api.main import app
from mooring.core.envelopes import validity_state
from mooring.core.schemas import (
    FenderResult,
    LineTension,
    ShipState,
    SimFrame,
    SimLifecycle,
    SimRecording,
    SimScene,
    SimSessionCreated,
    TugState,
)
from mooring.core.schemas.motion import (
    MotionFenderState, MotionFittingLoad, MotionLineState, MotionProvenance, MotionSceneDepth,
    MotionSceneFender, MotionScenePierFitting, MotionSceneShipFitting, MotionTugState,
    MotionWaveComponent, MotionWaves, MotionWind, MotionWrench, ShipMotion,
)
from mooring.examples import EXAMPLES


LEGACY_POSE = {
    "x_ft": 650.0,
    "y_ft": 160.0,
    "heading_true_deg": 105.0,
    "u_kt": 0.0,
    "v_kt": 0.25,
    "r_degps": 0.0,
}
LEGACY_TUG = {"tug_id": "T1", "force_lbf": 50000.0, "direction_rel_deg": 90.0}
LEGACY_LINE = {"line_number": 3, "tension_lbf": 12000.0}
LEGACY_FENDER = {"fender_id": "F1", "reaction_lbf": 8000.0, "compression_ft": 0.2, "status": "AMBER"}
LEGACY_FRAME = {
    "t_s": 1.2,
    "pose": LEGACY_POSE,
    "tugs": [LEGACY_TUG],
    "lines": [LEGACY_LINE],
    "fenders": [LEGACY_FENDER],
    "alerts": ["Line 3 secured."],
}
LEGACY_SESSION = {"session_id": "sim_legacy", "ws_url": "/ws/sim/sim_legacy"}
RM0_IDENTITY = {"session_id": "session-test", "run_id": "run-test", "sequence": 0,
                "scene_id": "scene-test", "scene_revision": "r1"}
MOCK_PROVENANCE = {"kind": "mock", "source": "Authored contract test; no dynamics solver."}
QUALIFIED_PROVENANCE = {"kind": "qualified", "source": "Qualified contract-test case", "references": ["fixture:benchmark-1"]}
LIMITED = {
    "state": "limited",
    "reasons": [{"code": "SYNTHETIC_FIXTURE", "message": "Values are authored, not qualified simulation results."}],
}
SCENE_IDENTITY = {"scene_id": "scene-test", "revision": "r1", "berth_id": "berth-test",
                  "ship_class_id": "ship-test", "loading": "test"}


def motion_payload():
    return {
        "availability": "available",
        "provenance": copy.deepcopy(MOCK_PROVENANCE),
        "validity": copy.deepcopy(LIMITED),
        "pose": {"x_ft": 650.0, "y_ft": 160.0, "yaw_deg": 0.0},
        "velocity": {"surge_fps": 0.0, "sway_fps": 0.4, "yaw_degps": 0.0},
        "dofs": {"surge": "prescribed", "sway": "prescribed", "yaw": "prescribed"},
        "acceleration": {},
    }


@pytest.mark.parametrize("model,payload", [
    (ShipState, LEGACY_POSE),
    (TugState, LEGACY_TUG),
    (LineTension, LEGACY_LINE),
    (FenderResult, LEGACY_FENDER),
    (SimFrame, LEGACY_FRAME),
    (SimSessionCreated, LEGACY_SESSION),
])
def test_legacy_wire_payloads_round_trip_without_new_fields(model, payload):
    parsed = model.model_validate(payload)
    assert parsed.model_dump(mode="json") == payload
    assert json.loads(parsed.model_dump_json()) == payload


def test_legacy_ship_velocity_defaults_and_toward_pier_sway_are_unchanged():
    pose = ShipState(x_ft=650, y_ft=160, heading_true_deg=105)
    assert pose.model_dump() == {**LEGACY_POSE, "v_kt": 0.0}
    # Existing +v means toward the pier; body-frame sway belongs in the new motion object.
    assert "toward the pier" in ShipState.model_fields["v_kt"].description


@pytest.mark.parametrize("model,payload", [(SimFrame, LEGACY_FRAME), (SimSessionCreated, LEGACY_SESSION)])
def test_legacy_motion_validity_is_unknown(model, payload):
    assert validity_state(payload) == "unknown"
    assert validity_state(model.model_validate(payload)) == "unknown"


def test_explicit_null_extensions_also_preserve_legacy_wire_shapes():
    frame = SimFrame.model_validate({**LEGACY_FRAME, "motion": None, "validity": None, "provenance": None,
                                     "schema_version": None, "sequence": None})
    session = SimSessionCreated.model_validate({**LEGACY_SESSION, "validity": None, "protocol": None, "scene_url": None})
    assert frame.model_dump(mode="json") == LEGACY_FRAME
    assert session.model_dump(mode="json") == LEGACY_SESSION


def test_websocket_rm0_session_keeps_legacy_fields_and_s17_validity(monkeypatch):
    """S1 upgraded live sessions to rm0-v1; legacy frame fields and S17 validity must be unchanged."""
    from modeling_api.state import SESSIONS
    from mooring.environment import mock as env_mock

    monkeypatch.setattr(env_mock, "utcnow", lambda: datetime(2026, 11, 4, 12, tzinfo=UTC))
    with TestClient(app) as client:
        scenario = client.post("/api/v1/scenarios", json=EXAMPLES["scenario"])
        assert scenario.status_code == 201, scenario.text
        request = copy.deepcopy(EXAMPLES["berthing_session"])
        request["scenario_id"] = scenario.json()["scenario_id"]
        response = client.post("/api/v1/berthing/sessions", json=request)
        assert response.status_code == 201, response.text
        session = response.json()
        try:
            assert set(LEGACY_SESSION) <= set(session)
            assert session["protocol"] == "rm0-v1"
            assert session["scene_url"] == f"/api/v1/berthing/sessions/{session['session_id']}/scene"
            assert validity_state(session) == "limited"
            scene = client.get(session["scene_url"])
            assert scene.status_code == 200, scene.text
            with client.websocket_connect(session["ws_url"] + "?limit=3") as ws:
                messages = [ws.receive_json() for _ in range(3)]
        finally:
            SESSIONS.pop(session["session_id"], None)

    assert messages[0]["type"] == "session_lifecycle" and messages[0]["state"] == "created"
    frame = next(m for m in messages if m.get("type") != "session_lifecycle")
    assert set(LEGACY_FRAME) <= set(frame)
    assert set(frame["pose"]) == set(LEGACY_POSE)
    assert frame["schema_version"] == "rm0-v1"
    assert (frame["scene_id"], frame["scene_revision"]) == (scene.json()["scene_id"], scene.json()["revision"])
    assert frame["provenance"]["kind"] == "estimated"
    assert {frame["motion"]["dofs"][axis] for axis in ("heave", "roll", "pitch")} == {"not_simulated"}
    assert validity_state(frame) == "limited"
    assert SimFrame.model_validate(frame).model_dump(mode="json") == frame


def test_s17_diagnostics_survive_without_enabling_rm0_fields():
    diagnostics = {
        "parameter_set": "synthetic-demonstration-v1", "qualification": "unqualified", "integration_steps": 0,
        "simulated_time_s": 0.0, "initial_energy_ftlbf": 0.0, "final_energy_ftlbf": 0.0,
        "applied_work_ftlbf": 0.0, "dissipated_energy_ftlbf": 0.0, "line_event_energy_ftlbf": 0.0,
        "energy_residual_ftlbf": 0.0, "integration_dt_s": 0.1,
    }
    frame = SimFrame.model_validate({**LEGACY_FRAME, "diagnostics": diagnostics})
    assert frame.model_dump(mode="json") == {**LEGACY_FRAME, "diagnostics": diagnostics}


def test_unknown_vertical_components_stay_null_and_do_not_imply_level_water():
    parsed = ShipMotion.model_validate(motion_payload())
    assert parsed.pose.heave_mllw_ft is None
    assert parsed.pose.roll_deg is None and parsed.pose.pitch_deg is None
    assert parsed.velocity.heave_fps is None
    assert parsed.velocity.roll_degps is None and parsed.velocity.pitch_degps is None
    assert parsed.acceleration.heave_fps2 is None
    assert parsed.acceleration.roll_degps2 is None and parsed.acceleration.pitch_degps2 is None
    assert parsed.dofs.heave == parsed.dofs.roll == parsed.dofs.pitch == "unknown"


@pytest.mark.parametrize("state", ["unknown", "not_simulated"])
@pytest.mark.parametrize("axis,component,field", [
    ("heave", "pose", "heave_mllw_ft"),
    ("heave", "velocity", "heave_fps"),
    ("heave", "acceleration", "heave_fps2"),
    ("roll", "pose", "roll_deg"),
    ("roll", "velocity", "roll_degps"),
    ("roll", "acceleration", "roll_degps2"),
    ("pitch", "pose", "pitch_deg"),
    ("pitch", "velocity", "pitch_degps"),
    ("pitch", "acceleration", "pitch_degps2"),
])
def test_unsimulated_vertical_dofs_reject_even_an_apparently_flat_zero(state, axis, component, field):
    payload = motion_payload()
    payload["dofs"][axis] = state
    payload[component][field] = 0.0
    with pytest.raises(ValidationError, match=f"{axis} values require"):
        ShipMotion.model_validate(payload)


@pytest.mark.parametrize("state", ["simulated", "prescribed"])
def test_explicit_vertical_dofs_allow_supplied_values_without_computation(state):
    payload = motion_payload()
    payload["dofs"].update(heave=state, roll=state, pitch=state)
    payload["pose"].update(heave_mllw_ft=3.5, roll_deg=-1.25, pitch_deg=0.2)
    payload["velocity"].update(heave_fps=0.0, roll_degps=0.1, pitch_degps=-0.1)
    payload["acceleration"].update(heave_fps2=0.0, roll_degps2=0.02, pitch_degps2=-0.01)
    parsed = ShipMotion.model_validate(payload).model_dump(mode="json")
    for component in ("pose", "velocity", "acceleration"):
        assert all(parsed[component][key] == value for key, value in payload[component].items())


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("component,field", [
    ("pose", "x_ft"), ("velocity", "sway_fps"), ("acceleration", "yaw_degps2"),
])
def test_nested_motion_numbers_must_be_finite(bad, component, field):
    payload = motion_payload()
    payload[component][field] = bad
    with pytest.raises(ValidationError) as error:
        ShipMotion.model_validate(payload)
    assert any(e["loc"] == (component, field) and e["type"] == "finite_number" for e in error.value.errors())


def test_provenance_never_implies_validity_and_qualification_requires_evidence():
    wind = MotionWind(speed_kt=12, provenance=MOCK_PROVENANCE)
    assert validity_state(wind) == "unknown"
    assert wind.availability == "unknown"
    with pytest.raises(ValidationError, match="evidence reference"):
        MotionProvenance(kind="qualified", source="Unreferenced claim")
    qualified = MotionProvenance(kind="qualified", source="Qualified test case", references=["fixture:benchmark-1"])
    assert validity_state(MotionWind(speed_kt=12, availability="available", provenance=qualified)) == "unknown"


@pytest.mark.parametrize("kind", ["mock", "estimated", "unknown"])
def test_unqualified_environment_cannot_claim_validity(kind):
    with pytest.raises(ValidationError, match="qualified provenance"):
        MotionWind(speed_kt=12, availability="available", provenance={**MOCK_PROVENANCE, "kind": kind},
                   validity={"state": "valid"})


def test_validity_requires_available_data_even_with_qualified_provenance():
    with pytest.raises(ValidationError, match="must be available"):
        MotionWind(availability="unavailable", provenance={"kind": "qualified", "source": "Test source",
                   "references": ["fixture:benchmark-1"]}, validity={"state": "valid"})


def test_wave_sources_keep_separate_availability_and_validity():
    waves = MotionWaves.model_validate({
        "ocean_swell": {"availability": "unavailable"},
        "local_chop": {"availability": "available", "height_ft": 0.5, "period_s": 2.0,
                       "provenance": MOCK_PROVENANCE, "validity": LIMITED},
        "ship_wake": {"availability": "not_simulated"},
    })
    assert waves.ocean_swell.height_ft is None and validity_state(waves.ocean_swell) == "unknown"
    assert waves.local_chop.height_ft == 0.5 and validity_state(waves.local_chop) == "limited"
    assert waves.ship_wake.height_ft is None and waves.tug_wake is None


@pytest.mark.parametrize("kind", ["mock", "estimated", "unknown"])
def test_frame_cannot_label_unqualified_motion_as_valid(kind):
    payload = {**LEGACY_FRAME, **RM0_IDENTITY, "schema_version": "rm0-v1", "validity": {"state": "valid"},
               "provenance": {**MOCK_PROVENANCE, "kind": kind}}
    with pytest.raises(ValidationError, match="qualified provenance"):
        SimFrame.model_validate(payload)
    payload["validity"] = LIMITED
    assert validity_state(SimFrame.model_validate(payload)) == "limited"


def test_qualified_frame_cannot_hide_explicitly_mock_ship_motion():
    with pytest.raises(ValidationError):
        SimFrame.model_validate({**LEGACY_FRAME, **RM0_IDENTITY, "schema_version": "rm0-v1", "validity": {"state": "valid"},
                                 "provenance": QUALIFIED_PROVENANCE, "motion": motion_payload()})


@pytest.mark.parametrize("availability", ["unavailable", "not_simulated"])
@pytest.mark.parametrize("model,values", [(MotionWind, {"speed_kt": 0}), (MotionWaveComponent, {"height_ft": 0})])
def test_unavailable_environment_has_no_invented_calm_values(availability, model, values):
    with pytest.raises(ValidationError):
        model(availability=availability, **values)


def test_qualified_frame_cannot_hide_mock_force_by_marking_it_unavailable():
    payload = {**LEGACY_FRAME, **RM0_IDENTITY, "schema_version": "rm0-v1", "validity": {"state": "valid"},
               "provenance": QUALIFIED_PROVENANCE, "forces": {"wind": {
                   "availability": "unavailable", "provenance": MOCK_PROVENANCE, "force": {"x_lbf": 5000},
               }}}
    with pytest.raises(ValidationError, match="motion values must be absent") as error:
        SimFrame.model_validate(payload)
    assert error.value.errors()[0]["loc"] == ("forces", "wind")


UNAVAILABLE_VALUES = [
    (MotionWrench, {"force": {"x_lbf": 0}}),
    (MotionTugState, {"tug_id": "tug-test", "position": {"x_ft": 0}}),
    (MotionTugState, {"tug_id": "tug-test", "mode": "standby"}),
    (MotionTugState, {"tug_id": "tug-test", "contact_state": "no_contact"}),
    (ShipMotion, {"pose": {}, "velocity": {"surge_fps": 0}, "dofs": {}}),
    (ShipMotion, {"pose": {}, "velocity": {}, "dofs": {"surge": "prescribed"}}),
    (MotionLineState, {"line_number": 1, "status": "slack"}),
    (MotionLineState, {"line_number": 1, "polyline": [{"x_ft": 0}, {}]}),
    (MotionFittingLoad, {"fitting_id": "fitting-test", "owner": "pier", "capacity_lbf": 1000}),
    (MotionFenderState, {"fender_id": "fender-test", "status": "GREEN"}),
    (MotionSceneShipFitting, {"fitting_id": "ship-test", "position": {"z_ft": 0}}),
    (MotionScenePierFitting, {"fitting_id": "pier-test", "position": {"z_mllw_ft": 0}}),
    (MotionSceneFender, {"fender_id": "fender-test", "position": {}, "standoff_ft": 0}),
    (MotionSceneDepth, {"position": {}, "depth_mllw_ft": 0}),
    (SimScene, {**SCENE_IDENTITY, "deck_height_mllw_ft": 0}),
    (SimScene, {**SCENE_IDENTITY, "ship_fittings": [{"fitting_id": "ship-test", "position": {"x_ft": 0}}]}),
]


@pytest.mark.parametrize("availability", ["unavailable", "not_simulated"])
@pytest.mark.parametrize("model,payload", UNAVAILABLE_VALUES)
def test_unavailable_components_reject_supplied_measurements_and_known_states(availability, model, payload):
    with pytest.raises(ValidationError, match="motion values must be absent"):
        model.model_validate({**payload, "availability": availability})


@pytest.mark.parametrize("model,payload", UNAVAILABLE_VALUES)
def test_unspecified_availability_remains_compatible_with_supplied_values(model, payload):
    assert model.model_validate(payload).availability == "unknown"


def test_unavailable_components_allow_ids_explanations_null_coordinates_and_empty_geometry():
    reason = {"state": "unknown", "reasons": [{"code": "NO_MEASUREMENTS", "message": "Source unavailable."}]}
    evidence = {"availability": "unavailable", "provenance": MOCK_PROVENANCE, "validity": reason}
    tug = MotionTugState(**evidence, tug_id="tug-test", push_point_id="push-test", position={}, actual_force={})
    assert tug.mode == tug.contact_state == "unknown" and tug.actual_force.x_lbf is None
    line = MotionLineState(**evidence, line_number=1, ship_fitting_id="ship-test", pier_fitting_id="pier-test",
                           ship_end={}, pier_end={}, polyline=[])
    assert line.status == "unknown" and line.polyline == []
    scene = SimScene(**evidence, **SCENE_IDENTITY, berth_outline=[], ship_hull_outline=[], fenders=[], depth_profile=[],
                     ship_fittings=[{"fitting_id": "ship-test", "kind": "bitt", "position": {}}])
    assert scene.ship_fittings[0].position.x_ft is None
    assert scene.berth_outline == scene.ship_hull_outline == []
    wind = MotionWind(**evidence, metadata={"basis": "scenario", "source": "Unavailable test source"})
    assert wind.speed_kt is None and wind.metadata.source == "Unavailable test source"
    motion = ShipMotion(availability="not_simulated", pose={}, velocity={}, acceleration={},
                        dofs={"heave": "not_simulated", "roll": "not_simulated", "pitch": "not_simulated"})
    assert motion.pose.heave_mllw_ft is None


def test_empty_geometry_is_allowed_but_partial_nonempty_geometry_is_rejected():
    from jsonschema import Draft202012Validator, ValidationError as SchemaValidationError

    for model, empty, partial in (
        (MotionLineState, {"line_number": 1, "polyline": []}, {"line_number": 1, "polyline": [{}]}),
        (SimScene, {**SCENE_IDENTITY, "berth_outline": []}, {**SCENE_IDENTITY, "berth_outline": [{}, {}]}),
        (SimScene, {**SCENE_IDENTITY, "ship_hull_outline": []}, {**SCENE_IDENTITY, "ship_hull_outline": [{}, {}]}),
    ):
        validator = Draft202012Validator(model.model_json_schema())
        validator.validate(empty)
        model.model_validate(empty)
        with pytest.raises(ValidationError):
            model.model_validate(partial)
        with pytest.raises(SchemaValidationError):
            validator.validate(partial)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_scene_deck_elevation_must_be_finite(bad):
    with pytest.raises(ValidationError) as error:
        SimScene(scene_id="scene-test", revision="r1", berth_id="berth-test", ship_class_id="ship-test",
                 loading="test", deck_height_mllw_ft=bad)
    assert any(e["loc"] == ("deck_height_mllw_ft",) and e["type"] == "finite_number" for e in error.value.errors())


def test_frame_environment_must_describe_the_same_simulation_time():
    with pytest.raises(ValidationError, match="environment.t_s"):
        SimFrame.model_validate({**LEGACY_FRAME, "environment": {"t_s": 1.3}})


def test_line_polyline_cannot_draw_different_attachments_than_reported_endpoints():
    ship_end = {"x_ft": 20, "y_ft": 30, "z_mllw_ft": 10}
    pier_end = {"x_ft": 0, "y_ft": 0, "z_mllw_ft": 7}
    line = {"line_number": 3, "ship_fitting_id": "ship-bitt", "pier_fitting_id": "pier-bollard",
            "ship_end": ship_end, "pier_end": pier_end, "polyline": [ship_end, pier_end]}
    parsed = MotionLineState.model_validate(line)
    assert parsed.polyline[0] == parsed.ship_end and parsed.polyline[-1] == parsed.pier_end
    with pytest.raises(ValidationError, match="start at ship_end"):
        MotionLineState.model_validate({**line, "polyline": [pier_end, ship_end]})


def recording_payload():
    frame = {**LEGACY_FRAME, **RM0_IDENTITY, "schema_version": "rm0-v1", "session_id": "session-test", "run_id": "run-test",
             "scene_id": "scene-test", "scene_revision": "r1"}
    return {
        "recording_id": "recording-test", "session_id": "session-test", "scene_id": "scene-test", "scene_revision": "r1",
        "sampling": {"display_interval_s": 1.0},
        "frames": [{**frame, "sequence": 10, "t_s": 0}, {**frame, "sequence": 20, "t_s": 1}],
    }


def test_decimated_sequences_are_valid_but_sequence_reuse_is_not():
    payload = recording_payload()
    assert [frame.sequence for frame in SimRecording.model_validate(payload).frames] == [10, 20]
    payload["frames"][1]["sequence"] = 10
    with pytest.raises(ValidationError, match="strictly increasing"):
        SimRecording.model_validate(payload)


def test_reset_uses_a_new_run_without_resetting_the_session_sequence():
    payload = recording_payload()
    payload["frames"][0]["t_s"] = 5
    with pytest.raises(ValidationError, match="monotonic within a run"):
        SimRecording.model_validate(payload)
    payload["frames"][1].update(run_id="reset-run", t_s=0)
    assert SimRecording.model_validate(payload).frames[1].t_s == 0
    payload["frames"].append({**payload["frames"][0], "sequence": 21, "t_s": 6})
    with pytest.raises(ValidationError, match="previous run after reset"):
        SimRecording.model_validate(payload)


def test_frames_and_lifecycle_share_one_sequence_and_session_identity():
    payload = recording_payload()
    payload["lifecycle"] = [{"session_id": "session-test", "run_id": "run-test", "sequence": 20,
                             "t_s": 1, "state": "paused"}]
    with pytest.raises(ValidationError, match="unique within a session"):
        SimRecording.model_validate(payload)
    payload["lifecycle"][0]["sequence"] = 21
    assert SimRecording.model_validate(payload).lifecycle[0].state == "paused"
    payload["lifecycle"][0]["session_id"] = "other-session"
    with pytest.raises(ValidationError, match="session_id does not match"):
        SimRecording.model_validate(payload)


def test_lifecycle_and_recording_cannot_call_mock_provenance_valid():
    with pytest.raises(ValidationError):
        SimLifecycle(session_id="session-test", run_id="run-test", sequence=1, t_s=0, state="created",
                     provenance=MOCK_PROVENANCE, validity={"state": "valid"})
    with pytest.raises(ValidationError):
        SimRecording.model_validate({**recording_payload(), "provenance": MOCK_PROVENANCE, "validity": {"state": "valid"}})


def test_qualified_recording_cannot_hide_a_limited_mock_frame():
    payload = recording_payload()
    payload.update(provenance=QUALIFIED_PROVENANCE, validity={"state": "valid"})
    payload["frames"][0].update(provenance=MOCK_PROVENANCE, validity=LIMITED)
    with pytest.raises(ValidationError):
        SimRecording.model_validate(payload)
