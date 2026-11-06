"""Independent review regressions: historical evidence, clock demand, isolation and saved replay."""
import asyncio
from contextlib import contextmanager
import copy
import threading

import httpx
import pytest

from modeling_api import security, sim_sessions, state
from modeling_api import ws as route
from modeling_api.main import app
from modeling_api.sim_sessions import Session
from mooring.berthing import simulator
from mooring.core import access, store
from mooring.core.schemas import SimControlMessage, SimLineEventMessage, SimRecording, SimScene, SimSpeedMessage
from mooring.examples import EXAMPLES

from test_s1_session_protocol import (A, B, P, Clock, Socket, client, command, fake_rich, idle_scheduler,
                                      make, setup)  # noqa: F401


@contextmanager
def owner(name):
    token, enforced = access.principal.set(name), access.enforced.set(True)
    try:
        yield
    finally:
        access.principal.reset(token)
        access.enforced.reset(enforced)


def test_reset_retains_invalid_recording_evidence(setup, fake_rich):
    clock = Clock()
    session = make(setup, clock, "review-invalid-reset")
    session.attach("a")
    session.fail("REVIEW_FAILURE", "Failed run", ValueError("failure before reset"))
    session.receive("a", SimControlMessage(type="reset"))
    assert session.model.validity().state == "limited"  # the new live run has fresh state
    recording = SimRecording.model_validate_json(session.recording_json())
    assert recording.validity.state == "invalid"
    assert any(r.code == "REVIEW_FAILURE" for r in recording.validity.reasons)
    assert any(e.validity.state == "invalid" for e in recording.lifecycle)
    session.persist(force=True)
    assert sim_sessions.RECORDINGS[session.session_id].validity.state == "invalid"
    assert sim_sessions.RECORDING_INDEX[session.session_id].validity.state == "invalid"


@pytest.mark.parametrize("kind", ["speed", "resume"])
def test_repeated_controls_do_not_erase_clock_demand(setup, fake_rich, kind):
    clock = Clock()
    session = make(setup, clock, "review-idempotent-" + kind)
    normal = make(setup, clock, "review-control-" + kind)
    session.attach("a"); normal.attach("b")
    msg = SimSpeedMessage(type="set_speed", speed=1) if kind == "speed" else SimControlMessage(type="resume")
    for i in range(1, 101):
        clock.now = i * .01
        session.receive("a", msg)
        session.tick(); normal.tick()
    assert session.model.t == normal.model.t == pytest.approx(1)
    assert session.model.integrator.state == pytest.approx(normal.model.integrator.state)


def test_changed_speeds_preserve_fractional_demand_and_backlog(setup, fake_rich):
    clock = Clock()
    session = make(setup, clock, "review-fractional-speed", duration=100)
    session.attach("a")
    demand, previous_speed = 0, 1
    for i in range(1, 101):
        clock.now = i * .01
        demand += .01 * previous_speed
        previous_speed = 2 if i % 2 else 1
        session.receive("a", SimSpeedMessage(type="set_speed", speed=previous_speed))
        session.tick()
    assert demand == pytest.approx(1.5)
    assert session.model.t == pytest.approx(1.5)
    clock.now += 10
    session.receive("a", SimSpeedMessage(type="set_speed", speed=2))
    # Already-earned time survives a speed change even when physics has not caught up.
    for _ in range(6):
        session.tick()
    assert session.model.t == pytest.approx(11.5)


def test_nonintegral_final_step_reaches_end(setup, fake_rich):
    clock = Clock()
    session = make(setup, clock, "review-final-boundary", duration=.15)
    session.attach("a")
    clock.now = .2
    session.tick()
    assert session.model.t == pytest.approx(.15)
    assert session.state == "ended"


def test_busy_tick_does_not_block_another_session_or_http(setup, fake_rich, monkeypatch):
    """Control worker work with events, rather than sleeps or a machine-specific physics timing bound."""
    clock = Clock()
    heavy = make(setup, clock, "review-heavy-worker")
    other = make(setup, clock, "review-other-worker")
    heavy.attach("a"); other.attach("b")
    entered, release, progressed = threading.Event(), threading.Event(), threading.Event()
    timed_out = []
    advance, other_advance = heavy.model.advance, other.model.advance

    def held(target, **kwargs):
        entered.set()
        if not release.wait(3):
            timed_out.append(True)
        return advance(target, **kwargs)

    def observed(target, **kwargs):
        result = other_advance(target, **kwargs)
        progressed.set()
        return result

    monkeypatch.setattr(heavy.model, "advance", held)
    monkeypatch.setattr(other.model, "advance", observed)
    clock.now = .5

    async def exercise():
        tasks = [asyncio.create_task(s.run()) for s in (heavy, other)]
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await asyncio.wait_for(client.get(P + "/health"), 1)
            assert response.status_code == 200
            assert await asyncio.to_thread(progressed.wait, 1)
            assert not timed_out and not release.is_set()
            assert heavy.model.t == 0 and other.model.t > 0
        finally:
            release.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("cancellations", [1, 2])
def test_cancelling_ticker_joins_its_current_worker_before_return(setup, fake_rich, monkeypatch, cancellations):
    clock = Clock()
    session = make(setup, clock, "review-worker-cancel")
    session.attach("a")
    entered, release = threading.Event(), threading.Event()
    advance = session.model.advance

    def held(target, **kwargs):
        entered.set()
        assert release.wait(3)
        return advance(target, **kwargs)

    monkeypatch.setattr(session.model, "advance", held)
    clock.now = 1

    async def exercise():
        task = asyncio.create_task(session.run())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            for _ in range(cancellations):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()  # returning here would leave a worker mutating a detached/reset session
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
        final = session.model.t
        session.detach("a")
        assert session.model.t == final and session.paused

    asyncio.run(exercise())


def test_runtime_chunk_caps_catchup_work(setup, fake_rich, monkeypatch):
    clock = Clock()
    session = Session(simulator.BerthingModel(*setup, dt=.0001, duration=20),
                      session_id="review-runtime-cap", clock=clock)
    session.attach("a")
    session.receive("a", SimSpeedMessage(type="set_speed", speed=16))
    advance = session.model.advance

    def one_chunk(target, **kwargs):
        advance(target, **kwargs)
        session.connection = None

    monkeypatch.setattr(session.model, "advance", one_chunk)
    clock.now = 1
    asyncio.run(session.run())
    assert session.model.t == pytest.approx(.001)
    assert session.lag_s > 0


def test_dense_command_chunks_bound_actual_work_and_preserve_trajectory(setup, fake_rich):
    """A thousand legal sub-dt commands must not turn ten nominal steps into a thousand segments."""
    clock = Clock()
    session = Session(simulator.BerthingModel(*setup, dt=.0001, duration=.01),
                      session_id="review-dense-work-cap", clock=clock)
    reference = simulator.BerthingModel(*setup, dt=.0001, duration=.01)
    for i in range(1000):
        msg = command(t=(i + 1) * 1e-6, force=10000 if i % 2 else 20000)
        session.model.schedule(msg); reference.schedule(msg)
    session.attach("a")
    clock.now = .01
    reference.advance(.01)
    chunks = 0
    while session.state != "ended":
        steps, queued = session.model.integrator.steps, len(session.model.pending)
        session.tick(max_steps=sim_sessions.RUNTIME_STEPS_PER_TICK)
        work = session.model.integrator.steps - steps + queued - len(session.model.pending)
        assert 0 < work <= sim_sessions.RUNTIME_STEPS_PER_TICK
        assert session.model.validity().state == "limited" and not session.error
        chunks += 1
        assert chunks < 300
    assert chunks > 100
    assert session.model.t == pytest.approx(.01)
    assert session.model.integrator.steps == reference.integrator.steps
    assert session.model.integrator.state == pytest.approx(reference.integrator.state, abs=1e-12)
    assert session.model.diagnostics() == reference.diagnostics()
    assert session.model.ramps == reference.ramps
    assert session.model.transitions == reference.transitions and not session.model.pending


@pytest.mark.parametrize("duration", [.1, .2])
def test_commands_at_session_end_drain_before_ended_and_recording(setup, fake_rich, duration):
    """A budget yield at the end must drain same-time commands without another integration step."""
    clock = Clock()
    session = make(setup, clock, "review-due-at-end", duration=duration, record_interval_s=.1)
    reference = make(setup, clock, "review-end-reference", duration=duration, record_interval_s=.1)
    for i in range(21):
        msg = SimLineEventMessage(type="line_event", t_s=.1, line_number=1,
                                  event="secured" if i % 2 == 0 else "released")
        session.model.schedule(msg); reference.model.schedule(msg)
    session.attach("a"); reference.attach("b")
    clock.now = duration
    reference.tick()
    session.tick(max_steps=3)
    assert session.model.t == pytest.approx(.1) and session.model.pending
    assert session.state == "running" and [f.t_s for f in session.recording().frames] == [0]
    assert session.latest.t_s == 0  # do not publish a partially applied command group
    while session.model.pending:
        before = len(session.model.pending)
        session.tick(max_steps=3)
        assert 0 < before - len(session.model.pending) <= 3
        if session.model.pending:
            assert session.model.integrator.steps == 1
    assert session.state == "ended"
    assert session.model.transitions == reference.model.transitions
    recorded = session.recording().frames
    assert [f.t_s for f in recorded] == ([0, .1] if duration == .1 else [0, .1, .2])
    assert [f.lines for f in recorded] == [f.lines for f in reference.recording().frames]
    assert len(recorded[1].lines) == 1
    assert sum(event.state == "ended" for event in session.lifecycle) == 1


@pytest.mark.parametrize("control", ["pause", "reconnect"])
def test_off_grid_command_yield_can_resume_after_reanchoring(setup, fake_rich, control):
    clock = Clock()
    session = make(setup, clock, "review-off-grid-" + control)
    reference = simulator.BerthingModel(*setup)
    for i in range(21):
        msg = SimLineEventMessage(type="line_event", t_s=.05, line_number=1,
                                  event="secured" if i % 2 == 0 else "released")
        session.model.schedule(msg); reference.schedule(msg)
    session.attach("a")
    clock.now = .1
    session.tick(max_steps=3)
    assert session.model.t == .05 and session.model.pending
    if control == "pause":
        session.receive("a", SimControlMessage(type="pause"))
    else:
        session.detach("a")
        session.attach("a")
    session.receive("a", SimControlMessage(type="resume"))
    while session.model.pending:
        queued = len(session.model.pending)
        session.tick(max_steps=3)
        assert 0 < queued - len(session.model.pending) <= 3
        assert session.model.t == .05 and not session.error and not session.model.invalid
    clock.now += .05
    session.tick(max_steps=3)
    reference.advance(.1)
    assert session.model.t == pytest.approx(.1)
    assert session.model.integrator.state == reference.integrator.state
    assert session.model.transitions == reference.transitions
    assert session.model.diagnostics() == reference.diagnostics()


def test_contact_subdivision_yield_preserves_crossings_and_diagnostics(setup):
    """Yield inside a nominal step after a real contact crossing, then resume the unchanged grid."""
    sc, initial, env = setup
    initial = initial.model_copy(update={"y_ft": 40.00002})
    reference = simulator.BerthingModel(sc, initial, env, dt=.1, duration=.2)
    chunked = simulator.BerthingModel(sc, initial, env, dt=.1, duration=.2)
    observed, reference_observed = [], []
    reference.advance(.2, observe=lambda *args: reference_observed.append(args))
    chunked.advance(.2, max_work=1, observe=lambda *args: observed.append(args))
    assert chunked.integrator.steps == 1 and 0 < chunked.t < .1
    assert any(event.kind == "contact_start" for event in chunked.transitions)
    assert any(event.kind == "fender_contact" for event in chunked.events)
    assert chunked.integrator.crossings == []  # accepted crossings are already drained on yield
    while chunked.t < .2 - 1e-10:
        before = chunked.integrator.steps
        chunked.advance(.2, max_work=1, observe=lambda *args: observed.append(args))
        assert chunked.integrator.steps - before == 1
        assert not chunked.integrator.crossings and not chunked.invalid
    assert observed == reference_observed
    assert chunked.integrator.state == reference.integrator.state
    assert chunked.diagnostics() == reference.diagnostics()
    assert chunked.transitions == reference.transitions
    assert chunked.events == reference.events


def test_scene_and_recording_survive_restart_with_ownership(client, fake_rich, monkeypatch, tmp_path):
    path = str(tmp_path / "recordings.sqlite")
    database = store.Database(path)
    monkeypatch.setattr(store, "_db", database)
    sid = None
    try:
        scenario = client.post(P + "/scenarios", json=EXAMPLES["scenario"], headers=A).json()["scenario_id"]
        request = copy.deepcopy(EXAMPLES["berthing_session"]); request["scenario_id"] = scenario
        created = client.post(P + "/berthing/sessions", json=request, headers=A).json()
        sid = created["session_id"]
        expected_scene = client.get(created["scene_url"], headers=A).json()
        with owner("alice"):
            state.SESSIONS[sid].persist(force=True)
        state.SESSIONS.pop(sid)
        database.close()
        database = store.Database(path)
        monkeypatch.setattr(store, "_db", database)
        scene = client.get(created["scene_url"], headers=A)
        recording = client.get(created["recording_url"], headers=A)
        assert scene.status_code == recording.status_code == 200
        assert scene.json() == expected_scene
        assert SimScene.model_validate(scene.json()).scene_id == SimRecording.model_validate(recording.json()).scene_id
        for url in (created["scene_url"], created["recording_url"]):
            assert client.get(url, headers=B).status_code == 404
        assert client.get(P + "/berthing/recordings", headers=A).json()["recordings"][0]["session_id"] == sid
        assert client.get(P + "/berthing/recordings", headers=B).json()["recordings"] == []
    finally:
        state.SESSIONS.pop(sid, None)
        database.close()


def test_recording_index_is_bounded_and_owner_scoped(client, setup, fake_rich, monkeypatch):
    database = store.Database(":memory:")
    monkeypatch.setattr(store, "_db", database)
    try:
        for name, sid in (("alice", "a1"), ("bob", "a2"), ("alice", "a3"), ("alice", "a4")):
            with owner(name):
                access.claim("session", sid)
                make(setup, Clock(), sid).persist(force=True)
        first = client.get(P + "/berthing/recordings?limit=2", headers=A)
        assert first.status_code == 200
        assert [r["session_id"] for r in first.json()["recordings"]] == ["a1", "a3"]
        assert first.json()["next_cursor"] == "a3"
        second = client.get(P + "/berthing/recordings?limit=2&after_session_id=a3", headers=A).json()
        assert [r["session_id"] for r in second["recordings"]] == ["a4"]
        assert "next_cursor" not in second
        entry = second["recordings"][0]
        assert "frames" not in entry and entry["frame_count"] == 1
        assert client.get(entry["recording_url"], headers=A).status_code == 200
        assert client.get(entry["scene_url"], headers=A).status_code == 200
        assert [r["session_id"] for r in client.get(P + "/berthing/recordings", headers=B).json()["recordings"]] == ["a2"]
        for limit in (0, 101):
            assert client.get(P + f"/berthing/recordings?limit={limit}", headers=A).status_code == 422
    finally:
        database.close()


def test_first_lifecycle_truncation_is_saved_without_another_frame(setup, fake_rich, monkeypatch):
    monkeypatch.setattr(sim_sessions, "RECORDING_LIFECYCLE", 1)
    session = make(setup, Clock(), "review-clean-save-then-truncate")
    session.persist(force=True)
    assert not session.rec_dirty
    assert not any(reason.code == "RECORDING_TRUNCATED"
                   for reason in sim_sessions.RECORDINGS[session.session_id].validity.reasons)
    session.attach("a")
    assert session.rec_lifecycle_truncated and session.rec_dirty
    session.detach("a")
    assert not session.rec_dirty
    for saved in (sim_sessions.RECORDINGS[session.session_id], sim_sessions.RECORDING_INDEX[session.session_id]):
        assert any(reason.code == "RECORDING_TRUNCATED" for reason in saved.validity.reasons)


@pytest.mark.parametrize("phase", ["attach", "receive", "detach"])
@pytest.mark.parametrize("cancellations", [1, 2])
def test_handler_cancellation_joins_session_operations_before_releasing_owner(
        setup, fake_rich, idle_scheduler, monkeypatch, phase, cancellations):
    """No attach/command/detach worker may outlive ownership cleanup, including repeated cancellation."""
    session = make(setup, Clock(), f"review-cancel-{phase}-{cancellations}")
    monkeypatch.setattr(route, "SESSIONS", {session.session_id: session})
    monkeypatch.setattr(security, "identity", lambda _: ("local", False))
    monkeypatch.setattr(session, "persist", lambda **_: None)
    entered, release, locked = threading.Event(), threading.Event(), threading.Event()
    original = getattr(session, phase)

    def gated(*args):
        entered.set()
        if phase != "attach":
            assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(session, phase, gated)

    def hold_attach_lock():
        with session.lock:
            locked.set()
            assert release.wait(3)

    async def exercise():
        holder = asyncio.create_task(asyncio.to_thread(hold_attach_lock)) if phase == "attach" else None
        task = None
        try:
            if holder:
                assert await asyncio.to_thread(locked.wait, 2)
            socket = Socket()
            task = asyncio.create_task(route.ws_sim(socket, session.session_id))
            if phase != "attach":
                await asyncio.wait_for(socket.sending.wait(), 2)
                socket.incoming.put_nowait(
                    SimSpeedMessage(type="set_speed", speed=2).model_dump_json() if phase == "receive" else None)
            assert await asyncio.to_thread(entered.wait, 2)
            for _ in range(cancellations):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            release.set()
            if holder:
                await holder
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
            assert session.connection is None and session.paused
            if phase == "receive":
                assert session.speed == 2  # queued work completed before detach; nothing can apply after reconnect
            reconnect = Socket()
            await asyncio.wait_for(route.ws_sim(reconnect, session.session_id, limit=1), 2)
            assert not any(code == 4409 for code, _ in reconnect.closed)
            assert session.connection is None and session.paused
        finally:
            release.set()
            if holder:
                await asyncio.gather(holder, return_exceptions=True)
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_failed_disconnect_save_is_retained_then_retried_before_cross_owner_expiry(setup, fake_rich, monkeypatch):
    """TTL cannot discard dirty evidence, and another creator must not become its owner."""
    from mooring.core.jobs import JobQueueFull
    database = store.Database(':memory:')
    monkeypatch.setattr(store, '_db', database)
    monkeypatch.setenv('MOORING_MAX_SESSIONS', '1')
    monkeypatch.setenv('MOORING_SESSION_IDLE_S', '1')
    original = sim_sessions.store_recording_json
    broken = True

    def save(*args):
        if broken:
            raise OSError('temporary disk failure')
        return original(*args)

    monkeypatch.setattr(sim_sessions, 'store_recording_json', save)
    clock = Clock()
    try:
        with owner('alice'):
            access.claim('session', 'dirty-expiry')
            session = make(setup, clock, 'dirty-expiry')
            session.attach('controller')
            session.detach('controller')
            assert session.rec_dirty
        sessions = {session.session_id: session}
        monkeypatch.setattr(sim_sessions.time, 'monotonic', lambda: 10)
        with owner('bob'):
            with pytest.raises(JobQueueFull):
                sim_sessions.create(sessions, 'blocked', session.model)
            assert list(sessions) == ['dirty-expiry']
            broken = False
            sim_sessions.create(sessions, 'new-session', session.model)
            assert list(sessions) == ['new-session']
            assert access.principal.get() == 'bob'
            assert not access.allowed(sim_sessions.RECORDINGS.namespace, 'dirty-expiry')
        with owner('alice'):
            saved = sim_sessions.RECORDINGS['dirty-expiry']
            assert saved.lifecycle[-1].state == 'paused'
            assert sim_sessions.RECORDING_INDEX['dirty-expiry'].frame_count == len(saved.frames)
            assert sim_sessions.SCENES['dirty-expiry'].scene_id == saved.scene_id
        assert not session.rec_dirty
    finally:
        database.close()
