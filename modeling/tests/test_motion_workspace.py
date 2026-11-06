"""Motion authoring API acceptance: ownership, source honesty and paused mechanics."""
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from modeling_api import security, state
from modeling_api.main import app
from modeling_api.routers import motion
from mooring import refdata
from mooring.berthing import motion_prediction, motion_workspace as workspace
from mooring.core.schemas.motion_prediction import MotionPredictionResponse
from mooring.core.schemas.motion_workspace import MotionWorkspaceSessionCreated, MotionWorkspaceSpec
from mooring.data_simulation.motion_scenarios import DEMO_SHIPS, training_environment

P = "/api/v1/motion"
A = {"Authorization": "Bearer " + "a" * 32}
B = {"Authorization": "Bearer " + "b" * 32}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MOORING_API_KEYS", json.dumps({"motion-alice": "a" * 32, "motion-bob": "b" * 32}))
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE", "10000")
    monkeypatch.setattr(security, "RATE", security.RateLimit())
    before = set(state.SESSIONS)
    with TestClient(app, headers=A) as c:
        yield c
    for sid in set(state.SESSIONS) - before:
        state.SESSIONS.pop(sid, None)


def scenario(client, index=0, **updates):
    spec = client.get(P + "/catalog").json()["presets"][index]["configuration"]
    spec.update(updates)
    response = client.post(P + "/scenarios", json=spec)
    assert response.status_code == 201, response.text
    return response.json()


def session(client, index=0, **updates):
    row = scenario(client, index, **updates)
    response = client.post(P + "/sessions", json={"motion_scenario_id": row["motion_scenario_id"]})
    assert response.status_code == 201, response.text
    MotionWorkspaceSessionCreated.model_validate(response.json())
    return response.json()


@pytest.mark.parametrize("index,class_id", enumerate(DEMO_SHIPS))
def test_four_demos_start_paused_with_authoritative_class_and_private_geometry(client, index, class_id):
    original = refdata.ship(class_id).model_dump_json()
    created = session(client, index)
    sid = created["session"]["session_id"]
    runtime = state.SESSIONS[sid]
    assert runtime.paused and runtime.model.t == 0
    assert created["ship"]["class_id"] == runtime.model.ship.class_id == class_id
    assert created["ship"]["loa_ft"] == refdata.ship(class_id).loa_ft
    assert created["ship"]["fittings"]
    assert created["session"]["forcing_synthetic"] is True
    assert created["session"]["validity"]["state"] == "limited"
    assert created["environment"]["metadata"]["basis"] == "scenario"
    assert runtime.model.system.lines == []
    assert refdata.ship(class_id).model_dump_json() == original
    assert client.delete(P + f"/sessions/{sid}").status_code == 204


def test_scenarios_are_copies_and_principal_isolated(client):
    row = scenario(client, name="My independent scenario")
    rid = row["motion_scenario_id"]
    second = scenario(client, name="Changed configuration")
    assert second["motion_scenario_id"] != rid and second["revision"] != row["revision"]
    assert client.get(P + f"/scenarios/{rid}").json() == row
    assert client.get(P + f"/scenarios/{rid}", headers=B).status_code == 404
    assert rid not in client.get(P + "/scenarios", headers=B).text
    assert client.post(P + "/sessions", json={"motion_scenario_id": rid}, headers=B).status_code == 404


def test_configuration_preview_resolves_parameters_without_allocating_or_saving(client):
    saved = client.get(P + "/scenarios").json()
    active = set(state.SESSIONS)
    spec = MotionWorkspaceSpec(name="New loading", ship_class_id="CG-47", tug_ids=["T1"])
    response = client.post(P + "/configuration", json=spec.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    resolved = MotionWorkspaceSpec.model_validate(response.json())
    assert resolved.controls.propulsion.basis == "synthetic"
    assert len(resolved.controls.tug_dynamics) == 1
    assert client.get(P + "/scenarios").json() == saved and set(state.SESSIONS) == active


def test_session_read_prediction_and_release_are_principal_isolated(client):
    result = session(client)
    sid = result["session"]["session_id"]
    for path in (result["session"]["scene_url"], result["session"]["recording_url"]):
        assert client.get(path, headers=B).status_code == 404
    assert client.post(P + f"/sessions/{sid}/prediction", json={"horizon_s": 1}, headers=B).status_code == 404
    assert client.delete(P + f"/sessions/{sid}", headers=B).status_code == 404
    assert sid in state.SESSIONS


def test_what_if_never_changes_actual_session(client, monkeypatch):
    monkeypatch.setattr(motion_prediction.time, "monotonic", lambda: 0.0)
    result = session(client, tug_ids=[])
    sid = result["session"]["session_id"]
    model = state.SESSIONS[sid].model
    before = motion_prediction.snapshot_hash(model)
    response = client.post(P + f"/sessions/{sid}/prediction", json={"horizon_s": 2,
        "what_if_commands": [{"type": "helm_command", "port_throttle": 0.4, "starboard_throttle": 0.4,
                              "rudder_deg": 0, "bow_thruster": 0, "stern_thruster": 0}]})
    assert response.status_code == 200, response.text
    prediction = MotionPredictionResponse.model_validate(response.json())
    assert prediction.complete and prediction.source.run_id == state.SESSIONS[sid].run_id
    assert prediction.path[-1].velocity.surge_fps > prediction.path[0].velocity.surge_fps
    assert prediction.validity.state == "limited"
    assert motion_prediction.snapshot_hash(model) == before and model.t == 0


def test_prediction_worker_capacity_is_bounded_and_recoverable(client):
    sid = session(client)["session"]["session_id"]
    assert motion._PREDICTIONS.acquire(False) and motion._PREDICTIONS.acquire(False)
    try:
        response = client.post(P + f"/sessions/{sid}/prediction", json={"horizon_s": 1})
        assert response.status_code == 429 and response.headers["Retry-After"] == "1"
    finally:
        motion._PREDICTIONS.release(); motion._PREDICTIONS.release()
    assert client.post(P + f"/sessions/{sid}/prediction", json={"horizon_s": 0.1}).status_code == 200


def test_release_refuses_active_socket_and_preserves_recording(client):
    result = session(client)
    sid = result["session"]["session_id"]
    runtime = state.SESSIONS[sid]
    runtime.attach("test-controller")
    assert client.delete(P + f"/sessions/{sid}").status_code == 409
    runtime.detach("test-controller")
    assert client.delete(P + f"/sessions/{sid}").status_code == 204
    assert sid not in state.SESSIONS
    assert client.get(result["session"]["recording_url"]).status_code == 200


def test_line_attachment_starts_at_actual_length_without_fabricated_pretension(client):
    result = session(client, initial_lines_attached=True, tug_ids=[])
    runtime = state.SESSIONS[result["session"]["session_id"]]
    assert len(runtime.model.system.lines) == len(runtime.model.all_lines) > 0
    for rec in runtime.model.system.lines:
        line = runtime.model.system.line_state(rec, runtime.model.body.pose(runtime.model.integrator.state))
        assert rec.model.tension(line.length_ft) == pytest.approx(0, abs=1e-5)


def test_snapshot_keeps_evidence_but_synthetic_edit_relabels_it(client):
    env = training_environment(datetime(2026, 11, 6, tzinfo=UTC)).model_dump(mode="json")
    env["metadata"].update(source="A supplied observation", basis="observation", quality="good", age_s=0)
    row = scenario(client, environment_mode="snapshot", environment=env)
    assert row["configuration"]["environment"] == env
    edited = scenario(client, environment_mode="synthetic", environment=env)
    assert edited["configuration"]["environment"]["metadata"]["basis"] == "scenario"
    assert edited["configuration"]["environment"]["metadata"]["quality"] == "unknown"
    assert "A supplied observation" not in json.dumps(edited)


def test_live_provider_failure_is_not_replaced_by_synthetic_values(client, monkeypatch):
    from mooring.environment.errors import ProviderError
    def unavailable(*_):
        raise ProviderError("unavailable", "Provider unavailable in offline acceptance")
    monkeypatch.setattr(workspace.environment, "live_snapshot", unavailable)
    row = scenario(client, environment_mode="live", environment=None)
    response = client.post(P + "/sessions", json={"motion_scenario_id": row["motion_scenario_id"]})
    assert response.status_code == 503 and "unavailable" in response.text.lower()


@pytest.mark.parametrize("change", [
    {"environment_mode": "live", "environment": {}},
    {"environment_mode": "snapshot", "environment": None},
    {"tug_ids": ["T1", "T1"]}, {"tug_ids": ["unknown"]},
    {"start": "channel", "route_id": None},
    {"start": "approach", "initial_lines_attached": True},
    {"route_follow": True, "route_id": None}, {"route_id": "unknown"},
    {"dt_s": 0}, {"duration_s": 14401},
])
def test_invalid_or_ambiguous_scenarios_are_rejected(client, change):
    spec = MotionWorkspaceSpec(name="invalid test", ship_class_id="DDG-51-FIIA").model_dump(mode="json")
    spec.update(change)
    assert client.post(P + "/scenarios", json=spec).status_code in (404, 422)
