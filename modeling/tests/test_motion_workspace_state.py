"""Actual API state reseeding: atomic adoption, lifecycle, evidence and ownership."""
from datetime import UTC, datetime, timedelta

import pytest

from modeling_api import state
from modeling_api.motion_state_sessions import adopt_state
from mooring.berthing.motion_prediction import snapshot_hash
from mooring.core.schemas.motion_state import MotionStateInput
from test_motion_workspace import A, B, P, client, session  # noqa: F401 - shared API fixture


def observation(created, **changes):
    result = dict(entity="ship", entity_id=created["ship"]["class_id"], frame="berth",
        berth_id=created["berth"]["berth_id"], source="synthetic", source_name="offline test input",
        observed_at_utc=datetime.now(UTC).isoformat(), sequence=1,
        x_ft=600.0, y_ft=100.0, heading_true_deg=created["berth"]["face_bearing_true_deg"],
        surge_fps=0.5, sway_fps=-0.1, yaw_degps=0.02,
        measured_acceleration={"surge_fps2": 1.2, "sway_fps2": None, "yaw_degps2": None})
    return {**result, **changes}


def test_adoption_starts_new_paused_run_with_evidence_in_recording_and_prediction(client):
    created = session(client, tug_ids=[])
    sid = created["session"]["session_id"]
    s = state.SESSIONS[sid]
    old_run, original = s.run_id, snapshot_hash(s.model)
    before_sequence = s.sequence
    response = client.post(P + f"/sessions/{sid}/state", json=observation(created))
    assert response.status_code == 200, response.text
    evidence = response.json()
    assert s.model.t == 0 and s.paused
    assert evidence["previous_run_id"] == old_run and evidence["run_id"] == s.run_id != old_run
    assert s.model.integrator.state[:2] == (600, 100)
    assert s.model.integrator.state[3:5] == (0.5, -0.1)
    assert s.latest.state_inputs[0].input.measured_acceleration.sway_fps2 is None
    assert s.latest.state_inputs[0].input.measured_acceleration.surge_fps2 == 1.2
    assert s.sequence > before_sequence and s.lifecycle[-1].state == "reset"
    assert {f.run_id for f in s.recording().frames} == {old_run, s.run_id}
    assert snapshot_hash(s.model) != original
    prediction = client.post(P + f"/sessions/{sid}/prediction", json={"horizon_s": 0.1}).json()
    assert prediction["source"]["run_id"] == s.run_id
    assert prediction["source"]["input_hash"] == snapshot_hash(s.model)
    assert s.latest.validity.state == "limited"


@pytest.mark.parametrize("changes,code", [
    ({"entity_id": "another-hull"}, "STATE_ENTITY_MISMATCH"),
    ({"entity": "tug", "entity_id": "not-selected"}, "STATE_ENTITY_MISMATCH"),
    ({"berth_id": "another-berth"}, "STATE_FRAME_MISMATCH"),
    ({"observed_at_utc": "2025-01-01T00:00:00Z"}, "STATE_STALE"),
    ({"observed_at_utc": "2099-01-01T00:00:00Z"}, "STATE_FUTURE"),
    ({"quality": "invalid"}, "STATE_QUALITY_INVALID"),
])
def test_rejected_state_leaves_every_actual_state_and_identity_unchanged(client, changes, code):
    created = session(client, tug_ids=[])
    sid = created["session"]["session_id"]
    s = state.SESSIONS[sid]
    before = snapshot_hash(s.model), s.run_id, s.sequence, s.recording_json()
    response = client.post(P + f"/sessions/{sid}/state", json=observation(created, **changes))
    assert response.status_code == 422 and response.json()["detail"]["code"] == code
    assert (snapshot_hash(s.model), s.run_id, s.sequence, s.recording_json()) == before


def test_pause_and_per_principal_boundary_are_enforced(client):
    created = session(client, tug_ids=[])
    sid = created["session"]["session_id"]
    req = observation(created)
    assert client.post(P + f"/sessions/{sid}/state", json=req, headers=B).status_code == 404
    s = state.SESSIONS[sid]
    s.paused = False
    response = client.post(P + f"/sessions/{sid}/state", json=req)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "STATE_REQUIRES_PAUSED"


def test_replay_rejected_across_new_runs_and_source_changes(client):
    created = session(client, tug_ids=[])
    sid = created["session"]["session_id"]
    req = observation(created)
    assert client.post(P + f"/sessions/{sid}/state", json=req).status_code == 200
    response = client.post(P + f"/sessions/{sid}/state", json={**req, "source": "sensor"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "STATE_DUPLICATE"


def test_independent_tug_state_changes_that_tug_only(client):
    created = session(client)
    sid = created["session"]["session_id"]
    s = state.SESSIONS[sid]
    ship = s.model.integrator.state
    other_id = s.model.tug_dynamics.ids[1]
    offset = s.model.tug_dynamics.offsets[other_id]
    other = s.model.integrator.auxiliary_state[offset:offset+9]
    tug_id = s.model.tug_dynamics.ids[0]
    response = client.post(P + f"/sessions/{sid}/state", json=observation(created,
        entity="tug", entity_id=tug_id, x_ft=200.0, y_ft=300.0))
    assert response.status_code == 200, response.text
    assert s.model.integrator.state == ship
    assert s.model.integrator.auxiliary_state[offset:offset+9] == other
    i = s.model.tug_dynamics.offsets[tug_id]
    assert s.model.integrator.auxiliary_state[i:i+2] == (200, 300)


def test_injected_acceptance_clock_has_no_wall_time_dependency(client):
    created = session(client, tug_ids=[])
    s = state.SESSIONS[created["session"]["session_id"]]
    observed = datetime(2026, 1, 2, tzinfo=UTC)
    req = MotionStateInput.model_validate(observation(created, source="recorded", observed_at_utc=observed))
    evidence = adopt_state(s, req, now_utc=observed+timedelta(seconds=10))
    assert evidence.age_s == 10 and evidence.input.observed_at_utc == observed
    assert evidence.input.source == "recorded" and evidence.qualification == "unqualified"
