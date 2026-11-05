"""S02: immutable persistent results, resolved-input snapshots, bounded background jobs."""

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core import store
from mooring.core.envelopes import RESULTS
from mooring.core.jobs import JobQueueFull, JobStore

client = TestClient(app)
P = "/api/v1"


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return False


def sse_events(js: JobStore, jid: str, last: int | None = None) -> list[tuple[int | None, str]]:
    async def run():
        out = []
        async for chunk in js.stream(jid, last):
            lines = chunk.strip().split("\n")
            eid = int(lines[0][4:]) if lines[0].startswith("id: ") else None
            out.append((eid, next(l for l in lines if l.startswith("event: "))[7:]))
        return out
    return asyncio.run(run())


# ---------- results and snapshots ----------

def test_results_are_write_once_and_persist_across_restart(tmp_path):
    path = str(tmp_path / "m.sqlite")
    store.reset_db(path)
    try:
        env = {"result_id": "res_a", "model": "m", "inputs_hash": "sha256:1", "computed_at_utc": "2026-01-01T00:00:00Z",
               "manifest": {"resolved_inputs_hash": "sha256:r"}}
        RESULTS["res_a"] = env
        RESULTS["res_a"] = env  # identical rewrite is a no-op
        with pytest.raises(store.ImmutableResultError):
            RESULTS["res_a"] = {**env, "model": "other"}
        with pytest.raises(store.ImmutableResultError):
            del RESULTS["res_a"]
        store.save_snapshot("sha256:r", {"ship": {"loa_ft": 500}})
        store.reset_db(path)  # simulated restart
        assert RESULTS["res_a"] == env and "res_a" in RESULTS and len(RESULTS) == 1
        assert store.load_snapshot("sha256:r") == {"ship": {"loa_ft": 500}}
        assert store.db().schema_version() == len(store.MIGRATIONS)
    finally:
        store.reset_db(":memory:")


def test_newer_database_is_refused(tmp_path):
    path = str(tmp_path / "n.sqlite")
    d = store.reset_db(path)
    d.execute("INSERT INTO schema_version VALUES (99)")
    try:
        with pytest.raises(RuntimeError, match="newer than this code"):
            store.Database(path)
    finally:
        store.reset_db(":memory:")


def test_saved_scenarios_survive_restart(tmp_path):
    from mooring.examples import EXAMPLES
    path = str(tmp_path / "s.sqlite")
    store.reset_db(path)
    try:
        sid = client.post(f"{P}/scenarios", json=EXAMPLES["scenario"]).json()["scenario_id"]
        store.reset_db(path)
        assert client.get(f"{P}/scenarios/{sid}").status_code == 200
    finally:
        store.reset_db(":memory:")


# ---------- background execution ----------

def test_ack_is_immediate_and_blocked_work_does_not_block_others():
    js = JobStore("/api", workers=1, queue_size=4)
    gate, started = threading.Event(), threading.Event()
    def blocked(ctx):
        started.set()
        gate.wait(5)
        return {"ok": True}
    t0 = time.monotonic()
    acc = js.submit_task("t.block", blocked)
    assert time.monotonic() - t0 < 0.5  # acknowledged without computing
    assert started.wait(2) and js.status(acc.job_id).state == "running"
    assert client.get(f"{P}/health").status_code == 200  # unrelated request is served meanwhile
    gate.set()
    assert wait_for(lambda: js.status(acc.job_id).state == "succeeded")
    assert js.status(acc.job_id).result == {"ok": True} and js.status(acc.job_id).progress == 1.0
    js.shutdown()


def test_progress_follows_completed_work_and_sse_is_ordered():
    js = JobStore("/api", workers=1)
    step, go = threading.Semaphore(0), threading.Event()
    def work(ctx):
        for i in range(1, 4):
            step.acquire()
            ctx.progress(i / 4, f"unit {i}")
        return {"n": 3}
    acc = js.submit_task("t.prog", work)
    assert js.status(acc.job_id).progress == 0.0
    step.release()
    assert wait_for(lambda: js.status(acc.job_id).progress == 0.25)
    step.release(); step.release()
    assert wait_for(lambda: js.status(acc.job_id).state == "succeeded")
    ev = sse_events(js, acc.job_id)
    assert [n for _, n in ev] == ["progress", "progress", "progress", "done"] and [i for i, _ in ev] == [0, 1, 2, 3]
    js.shutdown()


def test_sse_reconnect_resumes_and_completion_callback_runs_once():
    js = JobStore("/api", workers=1)
    calls = []
    acc = js.submit_task("t.cb", lambda ctx: ctx.progress(0.5) or {"v": 1}, on_done=lambda job: calls.append(job.job_id))
    assert wait_for(lambda: js.status(acc.job_id).state == "succeeded")
    first = sse_events(js, acc.job_id)
    again = sse_events(js, acc.job_id, last=first[-2][0])  # reconnect after the last progress event
    assert [n for _, n in again] == ["done"]
    assert sse_events(js, acc.job_id, last=first[-1][0]) == []  # already saw done: nothing replayed
    sse_events(js, acc.job_id); sse_events(js, acc.job_id)
    assert calls == [acc.job_id] and js.get(acc.job_id).completed_callbacks == 1
    js.shutdown()


def test_cancel_queued_and_running_jobs():
    js = JobStore("/api", workers=1, queue_size=2)
    gate = threading.Event()
    running = js.submit_task("t.run", lambda ctx: gate.wait(5) or (ctx.check_cancelled(), {})[1])
    queued = js.submit_task("t.queued", lambda ctx: {"never": True})
    assert wait_for(lambda: js.status(running.job_id).state == "running")
    assert js.status(queued.job_id).state == "queued"
    js.cancel(queued.job_id)
    assert js.status(queued.job_id).state == "cancelled" and js.status(queued.job_id).result is None
    js.cancel(running.job_id)
    assert js.status(running.job_id).state == "cancelled"
    gate.set()  # the late result must be discarded, not resurrect the job
    time.sleep(0.1)
    assert js.status(running.job_id).state == "cancelled" and js.status(running.job_id).result is None
    js.shutdown()


def test_deadline_makes_a_job_terminal_and_discards_late_result():
    js = JobStore("/api", workers=1)
    gate = threading.Event()
    acc = js.submit_task("t.slow", lambda ctx: gate.wait(5) or {"late": True}, deadline_s=0.05)
    assert wait_for(lambda: js.status(acc.job_id).state == "running")
    assert wait_for(lambda: js.status(acc.job_id).state == "failed")
    assert "deadline" in js.status(acc.job_id).error
    gate.set(); time.sleep(0.1)
    assert js.status(acc.job_id).state == "failed" and js.status(acc.job_id).result is None
    js.shutdown()


def test_task_exception_is_a_terminal_error():
    js = JobStore("/api", workers=1)
    def boom(ctx):
        raise ValueError("bad input")
    acc = js.submit_task("t.err", boom)
    assert wait_for(lambda: js.status(acc.job_id).state == "failed")
    assert js.status(acc.job_id).error == "ValueError: bad input"
    js.shutdown()


def test_overload_is_bounded_and_served_as_429():
    js = JobStore("/api", workers=1, queue_size=1)
    gate = threading.Event()
    js.submit_task("a", lambda ctx: gate.wait(5) or {})
    js.submit_task("b", lambda ctx: gate.wait(5) or {})
    with pytest.raises(JobQueueFull):
        js.submit_task("c", lambda ctx: {})
    gate.set(); js.shutdown()
    # HTTP mapping
    from modeling_api import state
    saved = state.JOBS.queue_size, state.JOBS.workers
    state.JOBS.queue_size, state.JOBS.workers = 0, 0
    try:
        from mooring.examples import EXAMPLES
        r = client.post(f"{P}/risk/exceedance", json=EXAMPLES["risk_exceedance"])
        assert r.status_code == 429 and r.headers["retry-after"] == "5"
    finally:
        state.JOBS.queue_size, state.JOBS.workers = saved


def test_shutdown_fails_running_work_with_a_reason():
    js = JobStore("/api", workers=1)
    gate = threading.Event()
    acc = js.submit_task("t.sd", lambda ctx: gate.wait(5))
    assert wait_for(lambda: js.status(acc.job_id).state == "running")
    js.shutdown(); gate.set()
    assert js.status(acc.job_id).state == "failed" and js.status(acc.job_id).error == "service shut down"


def test_restart_marks_interrupted_jobs_failed_and_keeps_finished_ones(tmp_path):
    path = str(tmp_path / "j.sqlite")
    store.reset_db(path)
    try:
        js = JobStore("/api", workers=1, persist=True)
        done = js.submit_task("t.done", lambda ctx: {"x": 1})
        assert wait_for(lambda: js.status(done.job_id).state == "succeeded")
        gate = threading.Event()
        stuck = js.submit_task("t.stuck", lambda ctx: gate.wait(5))
        assert wait_for(lambda: js.status(stuck.job_id).state == "running")
        store.reset_db(path)  # process "dies" here
        js2 = JobStore("/api", persist=True)
        assert js2.status(done.job_id).state == "succeeded" and js2.status(done.job_id).result == {"x": 1}
        st = js2.status(stuck.job_id)
        assert st.state == "failed" and st.error == "interrupted by restart"
        assert sse_events(js2, stuck.job_id)[-1][1] == "done"
        assert js2.purge(older_than_s=-1) == 2 and js2.status(done.job_id) is None
        gate.set(); js.shutdown()
    finally:
        store.reset_db(":memory:")


def test_modeling_job_lifecycle_over_http_including_cancel():
    from mooring.examples import EXAMPLES
    acc = client.post(f"{P}/risk/exceedance", json=EXAMPLES["risk_exceedance"]).json()
    assert wait_for(lambda: client.get(acc["status_url"]).json()["state"] == "succeeded", 20)
    assert client.delete(f"{P}/jobs/{acc['job_id']}").json()["state"] == "succeeded"  # terminal jobs stay terminal
    assert client.delete(f"{P}/jobs/job_missing").status_code == 404
