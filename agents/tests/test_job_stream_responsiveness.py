"""Slow terminal persistence must not stall either SSE channel's ASGI event loop."""
import asyncio
import threading

import httpx
import pytest

from mooring.core.jobs import JobStore
from mooring_agents.api.main import app
from mooring_agents.api.routers import planner


@pytest.mark.parametrize('channel', ['jobs', 'planner'])
def test_sse_does_not_block_health_during_terminal_database_write(monkeypatch, channel):
    js = JobStore('/api', workers=1)
    work_release, writing, commit_release = (threading.Event() for _ in range(3))
    timed_out = []

    def work(ctx):
        assert work_release.wait(3)
        return {'ok': True}

    def persist(job):
        if job.finished:
            writing.set()
            if not commit_release.wait(3):
                timed_out.append(True)

    monkeypatch.setattr(js, '_persist', persist)
    accepted = js.submit_task('blocked-write', work)
    job = js.jobs[accepted.job_id]
    monkeypatch.setattr(planner, 'JOBS', js)
    monkeypatch.setattr(planner, '_job', lambda _: job)
    monkeypatch.setattr(planner.planner, 'PLANS', {})
    stream = js.stream(job.job_id) if channel == 'jobs' else planner.plan_events('plan', follow=False, last_event_id=None).body_iterator

    async def consume():
        return [event async for event in stream]

    async def exercise():
        work_release.set()
        assert await asyncio.to_thread(writing.wait, 2)
        task = asyncio.create_task(consume())
        try:
            await asyncio.sleep(0)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as http:
                response = await asyncio.wait_for(http.get('/api/v1/health'), 1)
            assert response.status_code == 200
            assert not timed_out and not commit_release.is_set()
            commit_release.set()
            events = await asyncio.wait_for(task, 2)
            assert len(events) == 1 and 'event: done' in events[0]
        finally:
            commit_release.set()
            await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(exercise())
        job.future.result(timeout=3)
    finally:
        work_release.set()
        commit_release.set()
        js.shutdown()
