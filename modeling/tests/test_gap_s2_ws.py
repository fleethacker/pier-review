"""Gap: S2 forcing through REST session create and the real WebSocket /ws/sim/{id} (real rich frames, real clock)."""
import copy
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from modeling_api import security, state
from modeling_api.main import app
from mooring.examples import EXAMPLES

P = "/api/v1"
A = {"Authorization": "Bearer " + "a" * 32}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MOORING_API_KEYS", json.dumps({"alice": "a" * 32}))
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE", "10000")
    monkeypatch.setattr(security, "RATE", security.RateLimit())
    from mooring.environment import mock as env_mock
    monkeypatch.setattr(env_mock, "utcnow", lambda: datetime(2026, 11, 4, 12, tzinfo=UTC))
    return TestClient(app)


RAMP = {"kind": "ramp", "ramp_start_s": 0, "target": {"t_s": 2, "wind_speed_kt": 30, "wind_gust_kt": 36, "wind_from_true_deg": 200}}


def create(client, forcing, duration_s=4):
    sc = client.post(P + "/scenarios", json=EXAMPLES["scenario"], headers=A).json()["scenario_id"]
    body = copy.deepcopy(EXAMPLES["berthing_session"])
    body.update(scenario_id=sc, forcing=forcing, duration_s=duration_s)
    r = client.post(P + "/berthing/sessions", json=body, headers=A)
    assert r.status_code == 201, r.text
    return r.json()


def collect(client, created, done, speed=8, extra=(), cap=400):
    """Read server messages until done(messages) is true; the cap and limit bound the loop so a bug cannot hang."""
    out = []
    with client.websocket_connect(created["ws_url"] + f"?limit={cap}", headers=A) as ws:
        ws.send_json({"type": "set_speed", "speed": speed})
        for m in extra:
            ws.send_json(m)
        while len(out) < cap and not done(out):
            out.append(ws.receive_json())
    return out


def ended(msgs):
    return any(m.get("type") == "session_lifecycle" and m["state"] in ("ended", "error") for m in msgs)


def frames_of(msgs):
    return [m for m in msgs if "pose" in m]


def after_reset(msgs):
    resets = [m["sequence"] for m in msgs if m.get("type") == "session_lifecycle" and m["state"] == "reset"]
    return bool(resets) and any("pose" in m and m["sequence"] > resets[-1] for m in msgs)


def test_rest_create_reports_forcing_revision_and_synthetic_flag(client):
    created = create(client, RAMP)
    try:
        assert created["forcing_revision"].startswith("frc-") and created["forcing_synthetic"] is True
    finally:
        state.SESSIONS.pop(created["session_id"], None)


def test_ws_frames_carry_forcing_revision_and_time_stamped_environment(client):
    created = create(client, RAMP, duration_s=4)
    try:
        frames = frames_of(collect(client, created, ended))
        assert len(frames) >= 2
        assert {f["forcing_revision"] for f in frames} == {created["forcing_revision"]}
        assert all(f["environment"]["t_s"] == f["t_s"] for f in frames)
    finally:
        state.SESSIONS.pop(created["session_id"], None)


def test_ws_environment_changes_over_simulation_time(client):
    created = create(client, RAMP, duration_s=4)
    try:
        msgs = collect(client, created, ended)
        frames = frames_of(msgs)
        assert len(frames) >= 2
        assert {f["forcing_revision"] for f in frames} == {created["forcing_revision"]}
        by_t = sorted(frames, key=lambda f: f["t_s"])
        winds = [f["environment"]["wind"]["speed_kt"] for f in by_t if f["environment"]]
        times = [f["t_s"] for f in by_t if f["environment"]]
        assert winds and winds[-1] > winds[0] + 1e-6, (times, winds)   # ramp moves the wind with simulation time
        assert all(b >= a - 1e-9 for a, b in zip(winds, winds[1:]))
    finally:
        state.SESSIONS.pop(created["session_id"], None)


def test_ws_uncovered_forcing_ends_with_forcing_uncovered_reason(client):
    replay = {"kind": "replay", "samples": [{"t_s": 0, "water_level_mllw_ft": 0.0}, {"t_s": 1, "water_level_mllw_ft": 0.5}]}
    created = create(client, replay, duration_s=5)
    try:
        msgs = collect(client, created, ended, speed=16)
        life = [m for m in msgs if m.get("type") == "session_lifecycle"]
        assert life[-1]["state"] == "error", [m["state"] for m in life]
        session = state.SESSIONS[created["session_id"]]
        assert session.error and any(r.code == "FORCING_UNCOVERED" for r in session.model.reasons)
        last = frames_of(msgs)[-1]
        assert last["validity"]["state"] == "invalid"
        assert "FORCING_UNCOVERED" in {r["code"] for r in last["validity"]["reasons"]}
        assert last["t_s"] < 5   # never integrated on invented forcing
    finally:
        state.SESSIONS.pop(created["session_id"], None)


def test_ws_reset_keeps_forcing_revision_and_restarts_time(client):
    created = create(client, RAMP, duration_s=4)
    try:
        msgs = collect(client, created, after_reset, extra=[{"type": "reset"}])
        frames = frames_of(msgs)
        reset = next(m for m in msgs if m.get("type") == "session_lifecycle" and m["state"] == "reset")
        post = [f for f in frames if f["sequence"] > reset["sequence"]]
        assert post and post[-1]["t_s"] == 0
        assert {f["forcing_revision"] for f in frames} == {created["forcing_revision"]}
        session = state.SESSIONS[created["session_id"]]
        assert any(m.state == "reset" for m in session.lifecycle)
        assert session.latest.forcing_revision == created["forcing_revision"]
    finally:
        state.SESSIONS.pop(created["session_id"], None)


def test_rest_create_rejects_invalid_forcing_422(client):
    sc = client.post(P + "/scenarios", json=EXAMPLES["scenario"], headers=A).json()["scenario_id"]
    body = copy.deepcopy(EXAMPLES["berthing_session"])
    body["scenario_id"] = sc
    for bad in ({"kind": "ramp"}, {"kind": "gusts"}, {"kind": "replay", "samples": []}):
        assert client.post(P + "/berthing/sessions", json={**body, "forcing": bad}, headers=A).status_code == 422
