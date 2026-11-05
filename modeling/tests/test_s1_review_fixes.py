"""Independent review regressions: historical evidence, clock demand, isolation and saved replay."""
import asyncio
from contextlib import contextmanager
import copy
import threading

import httpx
import pytest

from modeling_api import sim_sessions, state
from modeling_api.main import app
from modeling_api.sim_sessions import Session
from mooring.berthing import simulator
from mooring.core import access, store
from mooring.core.schemas import SimControlMessage, SimRecording, SimScene, SimSpeedMessage
from mooring.examples import EXAMPLES

from test_s1_session_protocol import A, B, P, Clock, client, fake_rich, make, setup  # noqa: F401


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


def test_cancelling_ticker_joins_its_current_worker_before_return(setup, fake_rich, monkeypatch):
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
