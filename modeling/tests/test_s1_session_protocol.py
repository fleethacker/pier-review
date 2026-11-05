"""rm0-v1 interactive session protocol: sequence, lifecycle, speed, reconnect, bounded recording, REST routes.

Offline with an injected clock. Protocol tests patch `mooring.berthing.rich` with a small valid fake so they do not
depend on the rich-frame implementation; `test_real_rich_frames_end_to_end` uses the real module.
"""
import asyncio
import copy
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from modeling_api import security, sim_sessions, state
from modeling_api import ws as route
from modeling_api.main import app
from modeling_api.sim_sessions import RECORDINGS, Session
from mooring import refdata, scenarios
from mooring.core import access
from mooring.berthing import rich
from mooring.berthing import simulator as sim
from mooring.core.schemas import (MotionProvenance, Scenario, ShipState, SimControlMessage, SimFrame, SimLifecycle,
                                  SimRecording, SimScene, SimSessionCreate, SimSessionCreated, SimSpeedMessage,
                                  SimTugCommandMessage)
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship

P = "/api/v1"


class Clock:
    now = 0.0
    def __call__(self): return self.now


@pytest.fixture
def setup(monkeypatch):
    ship, berth, spec = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
    monkeypatch.setattr(refdata, "ship", lambda _: ship.model_copy(deep=True))
    monkeypatch.setattr(refdata, "berth", lambda _: berth.model_copy(deep=True))
    monkeypatch.setattr(refdata, "line", lambda _: spec.model_copy(deep=True))
    sc = Scenario.model_validate({**EXAMPLES["scenario"], "scenario_id": "test-s1", "created_at_utc": "2026-01-01T00:00:00Z",
        "ship_class_id": ship.class_id, "berth_id": berth.berth_id, "side_to": "starboard", "config": breast_config(standoff=11)})
    env = calm_env()
    initial = ShipState(x_ft=400, y_ft=41, heading_true_deg=90, v_kt=0.5)
    monkeypatch.setattr(scenarios, "get", lambda _: sc.model_copy(deep=True))
    monkeypatch.setattr(scenarios, "environment_for", lambda _: env.model_copy(deep=True))
    return sc, initial, env


def _estimated():
    return MotionProvenance(kind="estimated", source="test fake rich module")


@pytest.fixture
def fake_rich(monkeypatch):
    """Valid minimal rm0-v1 scene and frames built from the legacy frame."""
    def build_scene(model):
        return SimScene(scene_id="scene_fake", revision="r1", berth_id="berth", ship_class_id="ship", loading="full_load")
    def rich_frame(model, *, session_id, run_id, sequence, scene, state=None, t=None, alerts=None):
        legacy = model.frame(state, t, alerts).model_dump()
        return SimFrame.model_validate({**legacy, "schema_version": "rm0-v1", "sequence": sequence, "session_id": session_id,
            "run_id": run_id, "scene_id": scene.scene_id, "scene_revision": scene.revision, "provenance": _estimated().model_dump()})
    monkeypatch.setattr(rich, "build_scene", build_scene)
    monkeypatch.setattr(rich, "scene_id_for", lambda model: ("scene_fake", "r1"))
    monkeypatch.setattr(rich, "rich_frame", rich_frame)


def make(setup, clock, sid="s1-a", duration=20, **kw):
    return Session(sim.BerthingModel(*setup, duration=duration), session_id=sid, clock=clock, **kw)


def command(t=0, force=10000):
    return SimTugCommandMessage(type="tug_command", t_s=t, tug_id="T1", force_lbf=force, direction_rel_deg=90)


def states(session):
    return [m.state for m in session.lifecycle]


def run_to(session, clock, wall):
    """Tick at 0.1 s wall steps up to `wall` seconds."""
    for i in range(1, int(round(wall * 10)) + 1):
        clock.now = i * 0.1
        session.tick()


def test_lifecycle_order_sequence_and_reset(setup, fake_rich):
    clock = Clock(); s = make(setup, clock, duration=2)
    assert states(s) == ["created"] and s.lifecycle[0].t_s == 0
    s.attach("a")
    run_to(s, clock, 0.5)
    s.receive("a", SimControlMessage(type="pause"))
    first_run, paused_t = s.run_id, s.model.t
    assert s.lifecycle[-1].state == "paused" and s.lifecycle[-1].t_s == pytest.approx(paused_t)
    s.receive("a", SimControlMessage(type="reset"))
    reset = s.lifecycle[-1]
    assert reset.state == "reset" and reset.t_s == 0 and reset.run_id != first_run and s.run_id == reset.run_id
    assert s.paused and s.latest.t_s == 0 and s.latest.run_id == reset.run_id
    s.receive("a", SimControlMessage(type="resume"))
    clock.now += 10; s.tick(); clock.now += 10; s.tick()
    assert s.model.t == pytest.approx(2)
    s.tick(); clock.now += 5; s.tick()
    assert states(s) == ["created", "running", "paused", "reset", "running", "ended"]
    assert all(m.speed == 1.0 and m.scene_id == "scene_fake" and m.provenance.kind == "estimated" for m in s.lifecycle)
    assert [m.run_id for m in s.lifecycle] == [first_run] * 3 + [s.run_id] * 3
    # One counter for frames and lifecycle, strictly increasing and never reset.
    recording = s.recording()
    sequences = sorted(m.sequence for m in [*recording.frames, *recording.lifecycle])
    assert sequences == sorted(set(sequences)) and len(sequences) > 6
    assert [m.sequence for m in recording.frames] == sorted({m.sequence for m in recording.frames})
    assert {f.run_id for f in recording.frames} == {first_run, s.run_id}
    assert s.latest.sequence < s.sequence


def test_sequence_increases_every_frame_and_detach_emits_paused(setup, fake_rich):
    clock = Clock(); s = make(setup, clock)
    s.attach("a")
    seen = [s.latest.sequence]
    for i in range(1, 6):
        clock.now = i * 0.3; s.tick(); seen.append(s.latest.sequence)
    assert seen == sorted(set(seen))
    last = s.sequence
    s.detach("a")
    assert states(s)[-1] == "paused" and s.lifecycle[-1].sequence == last + 1
    s.attach("b"); s.tick()
    assert states(s).count("running") == 1  # reattach does not resume; resume is explicit


def test_speed_advances_proportionally_with_unchanged_dt_and_trajectory(setup, fake_rich):
    clock = Clock(); a = make(setup, clock, "s1-1x"); b = make(setup, clock, "s1-2x")
    a.attach("a"); b.attach("b")
    for s in (a, b): s.receive(s.connection, command(0))
    b.receive("b", SimSpeedMessage(type="set_speed", speed=2))
    assert b.lifecycle[-1].speed == 2 and b.lifecycle[-1].state == "running"
    dt = a.model.dt
    run_to(a, clock, 3.0)
    clock.now = 0
    run_to_b = Clock(); b.clock = run_to_b
    b.reanchor()
    for i in range(1, 16):
        run_to_b.now = i * 0.1; b.tick()
    assert a.model.t == pytest.approx(3.0) and b.model.t == pytest.approx(3.0)  # 1.5 wall s at 2x == 3 wall s at 1x
    assert a.model.dt == b.model.dt == dt
    assert b.model.integrator.state == pytest.approx(a.model.integrator.state, abs=1e-9)
    assert b.latest.pose.model_dump() == pytest.approx(a.latest.pose.model_dump(), abs=1e-9)
    for i in range(16, 31):
        run_to_b.now = i * 0.1; b.tick()
    assert b.model.t == pytest.approx(6.0)


def test_speed_validation_and_lag_alert(setup, fake_rich):
    for bad in (0, -1, 16.5):
        with pytest.raises(ValueError):
            SimSpeedMessage(type="set_speed", speed=bad)
    clock = Clock(); s = make(setup, clock, duration=900)
    s.attach("a"); s.receive("a", SimSpeedMessage(type="set_speed", speed=16))
    clock.now = 10; s.tick()          # wants 160 s of simulation; the per-tick cap is 16 s: scheduler is behind
    assert s.model.t == pytest.approx(16) and s.lag_s == pytest.approx(9)
    assert any("lagging wall clock by 9.0 s at 16x" in alert for alert in s.latest.alerts)
    for _ in range(12): s.tick()      # physics is never skipped: it catches up
    assert s.model.t == pytest.approx(160) and s.lag_s == 0 and not s.latest.alerts


def test_flood_of_commands_cannot_advance_sim_time(setup, fake_rich):
    clock = Clock(); s = make(setup, clock)
    s.attach("a")
    for _ in range(100): s.receive("a", command(1))
    with pytest.raises(ValueError, match="rate limit"): s.receive("a", command(1))
    assert s.model.t == 0
    clock.now = 0.5; s.tick()
    assert s.model.t == pytest.approx(0.5)


class Socket:
    headers = {}
    def __init__(self):
        self.incoming = asyncio.Queue(); self.sent = []
        self.sending = asyncio.Event(); self.release = asyncio.Event(); self.release.set(); self.closed = []
    async def accept(self): pass
    async def receive(self):
        message = await self.incoming.get()
        return {"type": "websocket.disconnect"} if message is None else {"type": "websocket.receive", "text": message}
    async def send_json(self, frame):
        self.sending.set()
        await self.release.wait()
        self.sent.append(frame)
    async def close(self, code=1000, reason=""): self.closed.append((code, reason))


@pytest.fixture
def idle_scheduler(monkeypatch):
    async def stopped(self): await asyncio.Event().wait()
    monkeypatch.setattr(Session, "run", stopped)


def test_slow_client_receives_only_the_latest_frame_with_gaps(setup, fake_rich, idle_scheduler, monkeypatch):
    async def exercise():
        clock = Clock(); s = make(setup, clock)
        monkeypatch.setattr(route, "SESSIONS", {"slow": s})
        socket = Socket(); socket.release.clear()
        task = asyncio.create_task(route.ws_sim(socket, "slow"))
        await socket.sending.wait()                     # first message is blocked in the transport
        produced = []
        for i in range(1, 11):
            clock.now = i * 0.1; s.tick(); produced.append(s.latest.sequence)
        socket.release.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            if socket.sent and "pose" in socket.sent[-1] and socket.sent[-1]["t_s"] == pytest.approx(1.0): break
        socket.incoming.put_nowait(None); await task
        frames = [m for m in socket.sent if m.get("type") != "session_lifecycle"]
        life = [m for m in socket.sent if m.get("type") == "session_lifecycle"]
        assert frames[-1]["t_s"] == pytest.approx(1.0) and frames[-1]["sequence"] == produced[-1]
        sequences = [f["sequence"] for f in frames]
        assert sequences == sorted(set(sequences)) and len(frames) < len(produced) + 1  # intermediate frames were dropped
        assert any(b - a > 1 for a, b in zip(sequences, sequences[1:]))
        assert [m["state"] for m in life][:2] == ["created", "running"]
    asyncio.run(asyncio.wait_for(exercise(), timeout=5))


def test_reconnect_after_sequence_resends_only_newer_lifecycle(setup, fake_rich, idle_scheduler, monkeypatch):
    async def exercise():
        clock = Clock(); s = make(setup, clock)
        monkeypatch.setattr(route, "SESSIONS", {"re": s})
        s.attach("a"); clock.now = 0.5; s.tick(); s.detach("a")
        retained = list(s.lifecycle)
        assert [m.state for m in retained] == ["created", "running", "paused"]
        async def connect(after, expected):
            socket = Socket()
            await route.ws_sim(socket, "re", limit=expected, after_sequence=after)
            return socket.sent
        everything = await connect(-1, 4)
        assert [m["state"] for m in everything if m.get("type") == "session_lifecycle"] == ["created", "running", "paused"]
        assert next(m for m in everything if "pose" in m)["t_s"] == pytest.approx(0.5)
        assert [m["sequence"] for m in everything] == sorted(m["sequence"] for m in everything)
        newer = await connect(retained[1].sequence, 2)
        assert [m["state"] for m in newer if m.get("type") == "session_lifecycle"] == ["paused"]
        assert next(m for m in newer if "pose" in m)["sequence"] == s.latest.sequence
        latest_only = await connect(retained[-1].sequence, 1)
        assert len(latest_only) == 1 and "pose" in latest_only[0]
    asyncio.run(asyncio.wait_for(exercise(), timeout=5))


def test_recording_validates_samples_by_simulation_time_and_persists_after_detach(setup, fake_rich):
    clock = Clock(); s = make(setup, clock, "s1-rec", duration=20, record_interval_s=1.0)
    s.attach("a")
    run_to(s, clock, 3.0)
    rec = s.recording()
    assert SimRecording.model_validate_json(rec.model_dump_json()) == rec
    assert rec.recording_id == "rec_s1-rec" and rec.session_id == "s1-rec" and (rec.scene_id, rec.scene_revision) == ("scene_fake", "r1")
    assert [f.t_s for f in rec.frames] == pytest.approx([0, 1, 2, 3])
    assert rec.sampling.physics_dt_s == s.model.dt and rec.sampling.display_interval_s == 1.0 and rec.sampling.max_pending_frames == 1
    assert [m.state for m in rec.lifecycle] == ["created", "running"]
    assert rec.duration_s == pytest.approx(3.0) and rec.provenance.kind == "estimated"
    assert "s1-rec" not in RECORDINGS
    s.detach("a")
    stored = RECORDINGS["s1-rec"]
    assert [m.state for m in stored.lifecycle] == ["created", "running", "paused"]
    assert [f.sequence for f in stored.frames] == [f.sequence for f in rec.frames]
    assert not any(r.code == "RECORDING_TRUNCATED" for r in stored.validity.reasons)


def test_recording_is_bounded_and_truncation_is_flagged(setup, fake_rich, monkeypatch):
    monkeypatch.setattr(sim_sessions, "RECORDING_FRAMES", 4)
    clock = Clock(); s = make(setup, clock, "s1-trunc", duration=20)
    s.attach("a")
    run_to(s, clock, 8.0)
    rec = s.recording()
    assert len(rec.frames) == 4 and [f.t_s for f in rec.frames] == pytest.approx([0, 1, 2, 3])
    assert any(r.code == "RECORDING_TRUNCATED" for r in rec.validity.reasons)
    assert s.latest.t_s == pytest.approx(8.0)           # display continues
    s.detach("a")
    assert any(r.code == "RECORDING_TRUNCATED" for r in RECORDINGS["s1-trunc"].validity.reasons)


def test_end_reset_and_error_persist_the_recording(setup, fake_rich):
    clock = Clock(); s = make(setup, clock, "s1-end", duration=1)
    s.attach("a"); clock.now = 5; s.tick()
    assert states(s)[-1] == "ended"
    ended = RECORDINGS["s1-end"]
    assert ended.lifecycle[-1].state == "ended" and ended.frames[-1].t_s == pytest.approx(1)
    clock.now += sim_sessions.PERSIST_MIN_S   # pause/reset persistence is throttled (review: loop stalls)
    s.receive("a", SimControlMessage(type="reset"))
    assert RECORDINGS["s1-end"].lifecycle[-1].state == "reset"
    s.receive("a", SimControlMessage(type="resume"))
    s.model.advance = lambda target, **kw: (_ for _ in ()).throw(ValueError("boom"))
    clock.now += 1; s.tick()
    assert s.error and states(s)[-1] == "error" and "boom" in s.lifecycle[-1].message
    assert RECORDINGS["s1-end"].lifecycle[-1].state == "error"


def test_wire_additions_are_omitted_when_unset():
    assert "record_interval_s" not in SimSessionCreate(scenario_id="s", initial_state=ShipState(x_ft=1, y_ft=1, heading_true_deg=1)).model_dump()
    assert SimSessionCreated(session_id="s", ws_url="/s").model_dump() == {"session_id": "s", "ws_url": "/s"}
    life = SimLifecycle(session_id="s", run_id="r", sequence=0, t_s=0, state="created")
    assert "speed" not in life.model_dump(mode="json")
    assert SimLifecycle(session_id="s", run_id="r", sequence=0, t_s=0, state="created", speed=2).model_dump(mode="json")["speed"] == 2


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MOORING_API_KEYS", json.dumps({"alice": "a" * 32, "bob": "b" * 32}))
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE", "10000")
    monkeypatch.setattr(security, "RATE", security.RateLimit())
    from mooring.environment import mock as env_mock
    monkeypatch.setattr(env_mock, "utcnow", lambda: datetime(2026, 11, 4, 12, tzinfo=UTC))
    return TestClient(app)


A, B = {"Authorization": "Bearer " + "a" * 32}, {"Authorization": "Bearer " + "b" * 32}


def test_session_routes_created_fields_and_ownership(client, fake_rich):
    sid_scenario = client.post(P + "/scenarios", json=EXAMPLES["scenario"], headers=A).json()["scenario_id"]
    request = copy.deepcopy(EXAMPLES["berthing_session"]); request["scenario_id"] = sid_scenario
    created = client.post(P + "/berthing/sessions", json=request, headers=A)
    assert created.status_code == 201, created.text
    body = created.json(); sid = body["session_id"]
    try:
        assert body["scene_url"] == f"{P}/berthing/sessions/{sid}/scene" and body["protocol"] == "rm0-v1"
        assert body["recording_url"] == f"{P}/berthing/sessions/{sid}/recording" and body["ws_url"] == f"/ws/sim/{sid}"
        scene = client.get(body["scene_url"], headers=A)
        assert scene.status_code == 200 and SimScene.model_validate(scene.json()).scene_id == "scene_fake"
        live = client.get(body["recording_url"], headers=A)
        assert live.status_code == 200 and SimRecording.model_validate(live.json()).frames[0].t_s == 0
        unknown = f"{P}/berthing/sessions/sim_nope"
        for path in (body["scene_url"], body["recording_url"], unknown + "/scene", unknown + "/recording"):
            assert client.get(path, headers=B if sid in path else A).status_code == 404
        # Recording outlives the live session (expiry), still owner-only.
        session = state.SESSIONS[sid]
        token, enforced = access.principal.set("alice"), access.enforced.set(True)  # as the WS handler runs it
        try: session.attach("c"); session.detach("c")
        finally: access.principal.reset(token); access.enforced.reset(enforced)
        del state.SESSIONS[sid]
        persisted = client.get(body["recording_url"], headers=A)
        assert persisted.status_code == 200 and persisted.json()["lifecycle"][-1]["state"] == "paused"
        assert client.get(body["recording_url"], headers=B).status_code == 404
        assert client.get(body["scene_url"], headers=A).status_code == 404  # scene needs a live session
    finally:
        state.SESSIONS.pop(sid, None)


def test_websocket_streams_lifecycle_then_rich_frame(client, fake_rich):
    sid_scenario = client.post(P + "/scenarios", json=EXAMPLES["scenario"], headers=A).json()["scenario_id"]
    request = copy.deepcopy(EXAMPLES["berthing_session"]); request["scenario_id"] = sid_scenario
    body = client.post(P + "/berthing/sessions", json=request, headers=A).json()
    try:
        with client.websocket_connect(body["ws_url"] + "?limit=3", headers=A) as ws:
            messages = [ws.receive_json() for _ in range(3)]
        assert [m.get("state") for m in messages if m.get("type") == "session_lifecycle"] == ["created", "running"]
        frame = next(m for m in messages if "pose" in m)
        assert frame["schema_version"] == "rm0-v1" and frame["session_id"] == body["session_id"]
        assert [m["sequence"] for m in messages] == sorted(m["sequence"] for m in messages)
    finally:
        state.SESSIONS.pop(body["session_id"], None)


def test_real_rich_frames_end_to_end(setup):
    """Uses the real rich module (no monkeypatch): scene, frames and recording must be valid rm0-v1."""
    clock = Clock(); s = make(setup, clock, "s1-real", duration=5)
    s.attach("a")
    run_to(s, clock, 2.0)
    assert s.latest.schema_version == "rm0-v1" and s.latest.sequence is not None and s.latest.motion is not None
    assert s.latest.scene_id == s.scene.scene_id and s.latest.scene_revision == s.scene.revision
    SimScene.model_validate_json(s.scene.model_dump_json())
    recording = s.recording()
    assert SimRecording.model_validate_json(recording.model_dump_json()).frames[-1].t_s == pytest.approx(2.0)
