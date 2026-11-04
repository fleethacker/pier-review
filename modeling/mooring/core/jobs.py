"""In-memory async job store with Server-Sent Events, shared by the modeling and agents services.

Mock behavior: the result is computed when the job is submitted, then revealed after MOCK_JOB_DELAY_S seconds
(default 3) so the UI can exercise progress bars and SSE. Tests set MOCK_JOB_DELAY_S=0. Swap for a real queue later.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import BaseModel

from .envelopes import new_id, utcnow
from .schemas import JobAccepted, JobStatus


def job_delay_s() -> float:
    return float(os.environ.get("MOCK_JOB_DELAY_S", "3"))


@dataclass
class Job:
    job_id: str
    kind: str
    created: datetime
    delay_s: float
    result: dict | None = None
    error: str | None = None
    # Extra SSE events (name, payload) spread across the delay, e.g. agent steps.
    events: list[tuple[str, dict]] = field(default_factory=list)
    on_done: Callable[[], None] | None = None

    @property
    def progress(self) -> float:
        if self.delay_s <= 0:
            return 1.0
        return min(1.0, (utcnow() - self.created).total_seconds() / self.delay_s)

    @property
    def state(self) -> str:
        if self.progress < 1.0:
            return "running"
        return "failed" if self.error else "succeeded"


class JobStore:
    def __init__(self, base_path: str):
        self.base_path = base_path.rstrip("/")
        self.jobs: dict[str, Job] = {}

    def submit(self, kind: str, result: BaseModel | dict | None = None, *, error: str | None = None,
               events: list[tuple[str, dict]] | None = None, job_id: str | None = None) -> JobAccepted:
        jid = job_id or new_id("job")
        payload = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
        self.jobs[jid] = Job(jid, kind, utcnow(), job_delay_s(), payload, error, events or [])
        return JobAccepted(job_id=jid, kind=kind, status_url=f"{self.base_path}/jobs/{jid}",
                           events_url=f"{self.base_path}/jobs/{jid}/events")

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def status(self, job_id: str) -> JobStatus | None:
        j = self.get(job_id)
        if j is None:
            return None
        done = j.state != "running"
        return JobStatus(job_id=j.job_id, kind=j.kind, state=j.state, progress=round(j.progress, 3),
                         created_at_utc=j.created,
                         finished_at_utc=j.created + timedelta(seconds=j.delay_s) if done else None,
                         result=j.result if j.state == "succeeded" else None, error=j.error if done else None)

    async def stream(self, job_id: str) -> AsyncIterator[str]:
        """SSE: `progress` events, any job-specific events, then `done`."""
        j = self.get(job_id)
        if j is None:
            return
        sent = 0
        while True:
            p = j.progress
            due = int(len(j.events) * p) if p < 1 else len(j.events)
            while sent < due:
                name, data = j.events[sent]
                yield sse(name, data)
                sent += 1
            yield sse("progress", {"job_id": j.job_id, "progress": round(p, 3), "message": f"{j.kind} {p:.0%}"})
            if p >= 1.0:
                yield sse("done", {"job_id": j.job_id, "state": j.state})
                return
            await asyncio.sleep(min(0.5, max(j.delay_s / 10, 0.05)))


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
