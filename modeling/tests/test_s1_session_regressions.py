"""Regression tests for the S1 session review findings (one test per finding). Offline, injected Clock."""
import asyncio
import copy
import json

import pytest
from pydantic import ValidationError

from modeling_api import sim_sessions, state
from modeling_api.sim_sessions import RECORDINGS, Session
from mooring.berthing import rich
from mooring.berthing import simulator as sim
from mooring.core import access
from mooring.core.schemas import SimControlMessage, SimLifecycle, SimRecording, SimSpeedMessage
from mooring.examples import EXAMPLES

# Fixtures and helpers shared with the protocol tests.
from test_s1_session_protocol import A, P, Clock, client, fake_rich, make, setup, states  # noqa: F401


def pause_resume_reset(s, clock, cycles):
    for i in range(cycles):
        for kind in ("pause", "resume", "reset"):
            clock.now += 0.001
            s.receive("a", SimControlMessage(type=kind))


def codes(session):
    return [r.code for r in session.model.reasons]


def test_persistence_storm_is_throttled_and_detach_forces(setup, fake_rich, monkeypatch):
    stored = []
    monkeypatch.setattr(sim_sessions, "store_recording_json", lambda sid, raw: stored.append((sid, raw)))
    clock = Clock(); s = make(setup, clock, "s1-storm")
    s.attach("a")
    # 30 cycles x 3 commands = 90 commands (< 100 per second), well inside PERSIST_MIN_S of fake time.
    pause_resume_reset(s, clock, 30)
    assert clock.now < sim_sessions.PERSIST_MIN_S
    assert len(stored) <= 1
    before = len(stored)
    s.detach("a")                       # detach always persists
    assert len(stored) == before + 1
    sid, raw = stored[-1]
    assert sid == "s1-storm"
    assert SimRecording.model_validate_json(raw) == s.recording()
    assert s.paused and s.connection is None


def test_recorded_frames_are_str_and_byte_budget_stops_recording_not_display(setup, monkeypatch):
    clock = Clock(); s = make(setup, clock, "s1-bytes", duration=20)    # real rich module: real frame sizes
    assert all(isinstance(f, str) for f in s.rec_frames) and isinstance(s.rec_lifecycle[0], str)
    first = len(s.rec_frames[0])
    assert 1000 < first < 100_000
    monkeypatch.setattr(sim_sessions, "RECORDING_MAX_BYTES", int(first * 2.5))
    s.attach("a")
    for i in range(1, 61):
        clock.now = i * 0.1; s.tick()
    assert s.rec_frames_truncated and len(s.rec_frames) == 2
    assert all(isinstance(f, str) for f in s.rec_frames)
    assert s.rec_bytes <= sim_sessions.RECORDING_MAX_BYTES
    assert s.latest.t_s == pytest.approx(6.0)               # display kept advancing
    rec = s.recording()
    assert any(r.code == "RECORDING_TRUNCATED" for r in rec.validity.reasons)
    assert len(rec.frames) == 2


def test_display_is_decimated_while_physics_runs_every_step(setup, fake_rich):
    clock = Clock(); s = Session(sim.BerthingModel(*setup, duration=20, dt=0.001), session_id="s1-dec", clock=clock)
    s.attach("a")
    sequences, alerts = {s.latest.sequence}, []
    for i in range(1, 201):
        clock.now = i * 0.005; s.tick()
        sequences.add(s.latest.sequence); alerts.append(s.latest.alerts)
    assert s.model.t == pytest.approx(1.0)
    assert len(sequences) <= 25 and len(sequences) >= 10
    assert not any(alerts)                      # budget never exceeded -> no lag alert
    clock.now += 5.0; s.tick()                  # a wall-clock jump the per-tick budget cannot absorb
    assert s.lag_s > sim_sessions.LAG_ALERT_S
    assert any("lagging wall clock" in a for a in s.latest.alerts)


@pytest.mark.parametrize("steps", [(0.1,), (0.07, 0.13, 0.31), (0.5,)])
def test_recorded_times_are_exact_multiples_at_high_speed(setup, fake_rich, steps):
    clock = Clock(); s = make(setup, clock, "s1-exact", duration=60, record_interval_s=0.5)
    s.attach("a"); s.receive("a", SimSpeedMessage(type="set_speed", speed=16))
    for i in range(40):
        clock.now += steps[i % len(steps)]; s.tick()
    assert s.model.t > 10
    ts = [f.t_s for f in s.recording().frames]
    assert len(ts) >= 15
    for t in ts[:-1]:
        assert abs(t / 0.5 - round(t / 0.5)) * 0.5 < 1e-9, t
    for a, b in zip(ts, ts[1:]):
        assert b - a == pytest.approx(0.5, abs=1e-9)        # no gaps


def test_lifecycle_overflow_does_not_stop_frame_recording(setup, fake_rich):
    clock = Clock(); s = make(setup, clock, "s1-life", duration=60)
    s.attach("a")
    for i in range(sim_sessions.RECORDING_LIFECYCLE + 50):
        if i % 100 == 0: clock.now += 1.0
        s.receive("a", SimSpeedMessage(type="set_speed", speed=1 + (i % 2)))
    assert s.rec_lifecycle_truncated and len(s.rec_lifecycle) == sim_sessions.RECORDING_LIFECYCLE
    s.receive("a", SimSpeedMessage(type="set_speed", speed=1))
    frames_before = len(s.rec_frames)
    for _ in range(50):
        clock.now += 0.1; s.tick()
    assert s.model.t > 4
    assert not s.rec_frames_truncated and len(s.rec_frames) >= frames_before + 4
    rec = s.recording()
    assert len(rec.lifecycle) == sim_sessions.RECORDING_LIFECYCLE
    msg = next(r.message for r in rec.validity.reasons if r.code == "RECORDING_TRUNCATED")
    assert f"{sim_sessions.RECORDING_LIFECYCLE} lifecycle" in msg


def test_resync_after_eviction_restates_state_once(setup, fake_rich):
    clock = Clock(); s = make(setup, clock, "s1-evict")
    s.attach("a")
    for i in range(sim_sessions.LIFECYCLE_LOG + 44):
        if i % 100 == 0: clock.now += 1.0
        s.receive("a", SimSpeedMessage(type="set_speed", speed=1 + (i % 2)))
    assert len(s.lifecycle) == sim_sessions.LIFECYCLE_LOG and s.lifecycle_evicted_through > 0
    seq, evicted = s.sequence, s.lifecycle_evicted_through
    s.resync(-1)
    assert s.sequence == seq + 1
    last = s.lifecycle[-1]
    assert last.sequence == seq + 1 and last.state == s.state == "running"
    assert "no longer retained" in last.message and f"sequence {evicted} " in last.message
    assert last.speed == s.speed
    after = s.sequence
    s.resync(after)                       # a current client gets nothing new
    assert s.sequence == after
    s.resync(s.sequence)                  # the newest sequence the client could hold
    assert s.sequence == after


@pytest.fixture
def failing_frames(monkeypatch, fake_rich):
    real = rich.rich_frame
    flag = {"fail": False, "exc": None}
    def maybe(*a, **kw):
        if flag["fail"]: raise flag["exc"]
        return real(*a, **kw)
    monkeypatch.setattr(rich, "rich_frame", maybe)
    return flag


def _validation_error():
    try: SimLifecycle.model_validate({})
    except ValidationError as exc: return exc


@pytest.mark.parametrize("exc", [_validation_error(), ValueError("bad frame")], ids=["validation_error", "value_error"])
def test_frame_production_failure_is_not_a_dynamics_failure(setup, failing_frames, exc):
    clock = Clock(); s = make(setup, clock, "s1-frame")
    s.attach("a")
    clock.now = 0.1; s.tick()
    good = s.latest
    failing_frames["fail"], failing_frames["exc"] = True, exc
    clock.now = 0.3; s.tick()
    assert s.error and "Frame production failed" in s.error
    assert "FRAME_PRODUCTION_FAILED" in codes(s) and "DYNAMICS_INTEGRATION_FAILED" not in codes(s)
    assert states(s)[-1] == "error" and s.state == "error"
    assert s.latest is good                             # the error frame failed too: last good frame is kept
    failing_frames["fail"] = False
    s.receive("a", SimControlMessage(type="pause"))     # next publish carries the error alert
    assert s.error in s.latest.alerts
    s.receive("a", SimControlMessage(type="resume"))
    assert s.error in s.latest.alerts and s.paused
    assert any(r.code == "FRAME_PRODUCTION_FAILED" for r in s.model.validity().reasons)


def test_ticker_survives_a_scheduler_exception(setup, fake_rich, monkeypatch):
    clock = Clock(); s = make(setup, clock, "s1-sched")
    original = Session.tick
    calls = []
    def flaky(self, **kwargs):
        calls.append(1)
        if len(calls) == 1: raise RuntimeError("scheduler boom")
        return original(self, **kwargs)
    monkeypatch.setattr(Session, "tick", flaky)
    async def exercise():
        s.attach("a")
        task = asyncio.create_task(s.run())
        await asyncio.sleep(0.2)
        assert not task.done()                          # the exception did not propagate out of run()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(asyncio.wait_for(exercise(), timeout=5))
    assert len(calls) >= 2                              # it kept ticking after the failure
    assert s.error and "SESSION_SCHEDULER_FAILED" in codes(s)
    assert states(s)[-1] == "error" and "scheduler boom" in s.lifecycle[-1].message


def test_recording_endpoint_serves_stored_json_after_session_removed(client, fake_rich):
    scenario = client.post(P + "/scenarios", json=EXAMPLES["scenario"], headers=A).json()["scenario_id"]
    request = copy.deepcopy(EXAMPLES["berthing_session"]); request["scenario_id"] = scenario
    body = client.post(P + "/berthing/sessions", json=request, headers=A).json()
    sid = body["session_id"]
    try:
        session = state.SESSIONS[sid]
        token, enforced = access.principal.set("alice"), access.enforced.set(True)
        try: session.attach("c"); session.detach("c")
        finally: access.principal.reset(token); access.enforced.reset(enforced)
        del state.SESSIONS[sid]
        got = client.get(body["recording_url"], headers=A)
        assert got.status_code == 200
        assert got.json() == json.loads(RECORDINGS_raw(sid))
        assert SimRecording.model_validate(got.json()).session_id == sid
        assert client.get(f"{P}/berthing/sessions/sim_unknown/recording", headers=A).status_code == 404
    finally:
        state.SESSIONS.pop(sid, None)


def RECORDINGS_raw(sid):
    token, enforced = access.principal.set("alice"), access.enforced.set(True)
    try: return sim_sessions.load_recording_json(sid)
    finally: access.principal.reset(token); access.enforced.reset(enforced)
