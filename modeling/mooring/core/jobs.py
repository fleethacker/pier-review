"""Jobs with Server-Sent Events, shared by the modeling and agents services.

Two ways to submit:

* `submit(kind, result)`: legacy (retained for compatibility tests). The result already exists; it is revealed
  after MOCK_JOB_DELAY_S seconds (default 3) so UIs can exercise progress bars. Tests set MOCK_JOB_DELAY_S=0.
* `submit_task(kind, fn)`: real background work. The callable runs on a bounded worker pool after the acknowledgement
  is returned; progress reflects work the callable reports; jobs can be cancelled and given deadlines.

Single-host limits (S02b): workers are threads in this process, so CPU-bound Python shares the GIL. Cancellation and
deadlines are cooperative: a running callable is not killed, its result is discarded and its job is terminal at once.
The queue is bounded (overload raises JobQueueFull, served as HTTP 429 with Retry-After). With `persist=True` job
records survive restart as terminal rows; work that was queued or running at the time is marked failed ("interrupted
by restart") and is never resumed. There is no distributed durability.
"""

import asyncio
import json
import os
import threading
from contextvars import copy_context
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from pydantic import BaseModel

from . import store, access, metrics
from .envelopes import new_id, utcnow
from .schemas import JobAccepted, JobStatus

TERMINAL = ("succeeded", "failed", "cancelled")


def job_delay_s() -> float:
    return float(os.environ.get("MOCK_JOB_DELAY_S", "3"))


class JobQueueFull(RuntimeError):
    """Overload: every worker is busy and the queue is full. Clients should retry after `retry_after_s`."""

    def __init__(self, retry_after_s: int = 5):
        super().__init__(f"job queue is full; retry after {retry_after_s} s")
        self.retry_after_s = retry_after_s


class JobCancelled(Exception):
    """Raised inside a task by `JobContext.check_cancelled()` to stop work early."""


class JobContext:
    """Handed to a task callable: report progress, emit events, and notice cancellation."""

    def __init__(self, job: "Job"):
        self._job = job

    def progress(self, fraction: float, message: str = "") -> None:
        self._job.report(fraction, message)

    def emit(self, name: str, data: dict) -> None:
        self._job.append_event(name, data)

    @property
    def cancelled(self) -> bool:
        return self._job.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled()
        if self._job.deadline_s and self._job.started and (utcnow()-self._job.started).total_seconds()>self._job.deadline_s:
            raise TimeoutError("job deadline exceeded")


@dataclass
class Job:
    job_id: str
    kind: str
    created: datetime
    delay_s: float = 0.0
    result: dict | None = None
    error: str | None = None
    # Legacy extra SSE events (name, payload) spread across the delay, e.g. agent steps.
    events: list[tuple[str, dict]] = field(default_factory=list)
    on_done: Callable[[], None] | None = None
    # Task jobs
    task: bool = False
    task_state: str = "queued"
    task_progress: float = 0.0
    finished: datetime | None = None
    started: datetime | None = None
    deadline_s: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    log: list[tuple[str, dict]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    future: Future | None = None
    completed_callbacks: int = 0
    persistence_pending: bool = False

    # ---- legacy ----
    @property
    def progress(self) -> float:
        if self.task:
            return round(self.task_progress, 3) if self.task_state not in TERMINAL else (1.0 if self.task_state == "succeeded" else self.task_progress)
        if self.delay_s <= 0:
            return 1.0
        return min(1.0, (utcnow() - self.created).total_seconds() / self.delay_s)

    @property
    def state(self) -> str:
        if self.task:
            return self.task_state
        if self.progress < 1.0:
            return "running"
        return "failed" if self.error else "succeeded"

    # ---- tasks ----
    def report(self, fraction: float, message: str = "") -> None:
        with self.lock:
            if self.task_state in TERMINAL:
                return
            self.task_progress = max(self.task_progress, min(0.999, max(0.0, fraction)))
            self.log.append(("progress", {"job_id": self.job_id, "progress": round(self.task_progress, 3),
                                          "message": message or f"{self.kind} {self.task_progress:.0%}"}))

    def append_event(self, name: str, data: dict) -> None:
        with self.lock:
            if self.task_state not in TERMINAL:
                self.log.append((name, data))


class JobStore:
    def __init__(self, base_path: str, *, workers: int | None = None, queue_size: int | None = None,
                 persist: bool = False, deadline_s: float | None = None, namespace: str = "modeling"):
        self.base_path = base_path.rstrip("/")
        self.jobs: dict[str, Job] = {}
        self.workers = workers or int(os.environ.get("MOORING_WORKERS", "2"))
        self.queue_size = queue_size if queue_size is not None else int(os.environ.get("MOORING_QUEUE", "16"))
        self.default_deadline_s = deadline_s if deadline_s is not None else (
            float(os.environ["MOORING_JOB_DEADLINE_S"]) if "MOORING_JOB_DEADLINE_S" in os.environ else None)
        if not namespace.strip():
            raise ValueError("Job namespace must not be empty")
        self.namespace = namespace
        self.persist = persist
        self._pool: ThreadPoolExecutor | None = None
        self._guard = threading.Lock()
        if persist:
            self.recover()

    # ---------- submission ----------
    def _accepted(self, jid: str, kind: str) -> JobAccepted:
        return JobAccepted(job_id=jid, kind=kind, status_url=f"{self.base_path}/jobs/{jid}",
                           events_url=f"{self.base_path}/jobs/{jid}/events")

    def submit(self, kind: str, result: BaseModel | dict | None = None, *, error: str | None = None,
               events: list[tuple[str, dict]] | None = None, job_id: str | None = None) -> JobAccepted:
        jid = job_id or new_id("job")
        access.claim("job",jid)
        payload = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
        self.jobs[jid] = Job(jid, kind, utcnow(), job_delay_s(), payload, error, events or [])
        return self._accepted(jid, kind)

    def active_count(self) -> int:
        return sum(1 for j in list(self.jobs.values()) if j.task and (j.task_state not in TERMINAL
                   or (j.future is not None and not j.future.done())))

    def submit_task(self, kind: str, fn: Callable[[JobContext], BaseModel | dict | None], *, job_id: str | None = None,
                    deadline_s: float | None = None, on_done: Callable[[Job], None] | None = None) -> JobAccepted:
        """Queue `fn` and return immediately. Raises JobQueueFull when workers and queue are saturated."""
        with self._guard:
            if self.active_count() >= self.workers + self.queue_size:
                metrics.add("queue_saturation")
                raise JobQueueFull()
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="job")
            jid = job_id or new_id("job")
            access.claim("job",jid)
            job = Job(jid, kind, utcnow(), task=True, deadline_s=deadline_s or self.default_deadline_s)
            job.on_done = on_done  # type: ignore[assignment]
            self.jobs[jid] = job
            try:
                self._persist(job)
            except Exception:
                del self.jobs[jid]
                raise
            job.future = self._pool.submit(copy_context().run, self._run, job, fn)
            metrics.event("job_submitted",job_id=jid,kind=kind)
        return self._accepted(jid, kind)

    def _run(self, job: Job, fn: Callable[[JobContext], BaseModel | dict | None]) -> None:
        with job.lock:
            if job.task_state in TERMINAL:
                return
            job.task_state, job.started = "running", utcnow()
        try:
            out = fn(JobContext(job))
            payload = out.model_dump(mode="json") if isinstance(out, BaseModel) else out
            JobContext(job).check_cancelled()
            self._finish(job, "succeeded", result=payload)
        except JobCancelled:
            self._finish(job, "cancelled", error="cancelled")
        except Exception as e:  # terminal error for the client; the job store never re-raises
            self._finish(job, "failed", error=f"{type(e).__name__}: {e}")

    def _finish(self, job: Job, state: str, *, result: dict | None = None, error: str | None = None) -> bool:
        """Move to a terminal state exactly once. Late results of cancelled/timed-out jobs are discarded."""
        with job.lock:
            if job.task_state in TERMINAL:
                return False
            finished = utcnow()
            if state == "succeeded" and job.deadline_s and job.started and (finished-job.started).total_seconds() > job.deadline_s:
                state, error = "failed", f"deadline of {job.deadline_s:g} s exceeded"
            candidate = replace(job, task_state=state, finished=finished, error=error,
                                result=result if state == "succeeded" else None,
                                log=[*job.log, ("done", {"job_id": job.job_id, "state": state})])
            # Persist a separate candidate: no reader can observe success before the write commits.
            try:
                self._persist(candidate)
            except Exception as exc:
                state = "failed"
                candidate.task_state, candidate.result = state, None
                candidate.error = f"Job persistence failed ({type(exc).__name__}); result was not published"
                candidate.log[-1] = ("done", {"job_id": job.job_id, "state": state})
                metrics.event("job_persistence_failed", job_id=job.job_id, error_type=type(exc).__name__)
                try:
                    self._persist(candidate)
                except Exception:
                    candidate.persistence_pending = True
            job.finished, job.error = candidate.finished, candidate.error
            job.result, job.log = candidate.result, candidate.log
            job.persistence_pending = candidate.persistence_pending
            job.task_state = candidate.task_state
            if state != "succeeded":
                job.cancel_event.set()
            callback, job.on_done = job.on_done, None
            job.completed_callbacks += 1
        metrics.add("jobs_"+state)
        if state == "cancelled": metrics.add("cancellations")
        duration = (job.finished-(job.started or job.created)).total_seconds()
        metrics.add("job_duration_seconds",duration)
        metrics.event("job_finished",job_id=job.job_id,state=state,duration_s=duration,
                      result_id=(job.result or {}).get("result_id"))
        if callback:
            try:
                callback(job)
            except Exception:
                pass
        return True

    # ---------- control ----------
    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None or not job.task:
            return job
        job.cancel_event.set()
        if job.future is not None:
            job.future.cancel()
        self._finish(job, "cancelled", error="cancelled")
        return job

    def _check_deadline(self, job: Job) -> None:
        if job.task and job.task_state == "running" and job.deadline_s and job.started \
                and (utcnow() - job.started).total_seconds() > job.deadline_s:
            self._finish(job, "failed", error=f"deadline of {job.deadline_s:g} s exceeded")

    def shutdown(self) -> None:
        for job in list(self.jobs.values()):
            if job.task:
                job.cancel_event.set()
                self._finish(job, "failed", error="service shut down")
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    # ---------- persistence ----------
    def _persist(self, job: Job) -> None:
        if not self.persist:
            return
        d = store.db()
        with d.lock:
            existing = d.execute("SELECT namespace FROM jobs WHERE job_id=?", (job.job_id,))
            if existing and existing[0][0] != self.namespace:
                raise ValueError("Job id already belongs to another service")
            d.execute("INSERT OR REPLACE INTO jobs "
                      "(job_id,kind,state,created_at_utc,finished_at_utc,error,result,namespace,event_log) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (job.job_id, job.kind, job.state, job.created.isoformat(),
                       job.finished.isoformat() if job.finished else None, job.error,
                       json.dumps(job.result) if job.result is not None else None,
                       self.namespace, json.dumps(job.log)))

    def recover(self) -> int:
        """After a restart: work that was queued or running did not finish and will not be resumed."""
        d = store.db()
        with d.lock:
            n = len(d.execute("SELECT job_id FROM jobs WHERE namespace=? AND state IN ('queued','running')", (self.namespace,)))
            d.execute("UPDATE jobs SET state='failed', error='interrupted by restart', finished_at_utc=? "
                      "WHERE namespace=? AND state IN ('queued','running')", (utcnow().isoformat(), self.namespace))
        return n

    def _retry_persistence(self, job: Job) -> None:
        with job.lock:
            if job.persistence_pending:
                try:
                    self._persist(job)
                except Exception:
                    return
                job.persistence_pending = False

    def purge(self, older_than_s: float) -> int:
        """Drop old terminal records only after their worker exits and their state is durable."""
        cutoff = (utcnow() - timedelta(seconds=older_than_s)).isoformat()
        with self._guard:
            retained = set()
            for jid, job in list(self.jobs.items()):
                self._retry_persistence(job)
                if job.persistence_pending or (job.future is not None and not job.future.done()):
                    retained.add(jid)
                elif job.task and job.finished and job.finished.isoformat() < cutoff:
                    del self.jobs[jid]
            if not self.persist:
                return 0
            d = store.db()
            with d.lock:
                rows = d.execute("SELECT job_id FROM jobs WHERE namespace=? AND finished_at_utc IS NOT NULL AND finished_at_utc < ?", (self.namespace, cutoff))
                eligible = [jid for (jid,) in rows if jid not in retained]
                for jid in eligible:
                    d.execute("DELETE FROM jobs WHERE namespace=? AND job_id=?", (self.namespace, jid))
            return len(eligible)

    def _from_db(self, job_id: str) -> Job | None:
        if not self.persist:
            return None
        rows = store.db().execute("SELECT kind,state,created_at_utc,finished_at_utc,error,result,event_log FROM jobs WHERE job_id=? AND namespace=?", (job_id, self.namespace))
        if not rows:
            return None
        kind, state, created, finished, error, result, event_log = rows[0]
        job = Job(job_id, kind, datetime.fromisoformat(created), task=True, task_state=state, error=error,
                  result=json.loads(result) if result else None,
                  finished=datetime.fromisoformat(finished) if finished else None)
        job.task_progress = 1.0 if state == "succeeded" else 0.0
        job.log = [tuple(event) for event in json.loads(event_log or "[]")]
        if not job.log or job.log[-1][0] != "done":
            job.log.append(("done", {"job_id": job_id, "state": state}))
        return job

    # ---------- reading ----------
    def get(self, job_id: str) -> Job | None:
        if not access.allowed("job",job_id): return None
        job = self.jobs.get(job_id) or self._from_db(job_id)
        if job is not None:
            self._retry_persistence(job)
            self._check_deadline(job)
        return job

    def status(self, job_id: str) -> JobStatus | None:
        j = self.get(job_id)
        if j is None:
            return None
        state = j.state
        done = state not in ("queued", "running")
        if j.task:
            finished = j.finished if done else None
        else:
            finished = j.created + timedelta(seconds=j.delay_s) if done else None
        return JobStatus(job_id=j.job_id, kind=j.kind, state=state, progress=round(j.progress, 3),
                         created_at_utc=j.created, finished_at_utc=finished,
                         result=j.result if state == "succeeded" else None, error=j.error if done else None)

    def event_snapshot(self, job: Job, sent: int):
        """Blocking snapshot for worker threads, including deadline and durable-state checks."""
        self._retry_persistence(job)
        self._check_deadline(job)
        with job.lock:
            return list(enumerate(job.log))[sent:], job.task_state, job.error, len(job.log)

    async def stream(self, job_id: str, last_event_id: int | None = None) -> AsyncIterator[str]:
        """SSE: `progress` events, any job-specific events, then `done`.

        Task jobs number every event. A client that reconnects with `Last-Event-ID` resumes after that event, so
        nothing is replayed and `done` is delivered once per connection that has not seen it."""
        j = await asyncio.to_thread(self.get, job_id)
        if j is None:
            return
        if j.task:
            sent = (last_event_id + 1) if last_event_id is not None else 0
            while True:
                pending, state, _, count = await asyncio.to_thread(self.event_snapshot, j, sent)
                for i, (name, data) in pending:
                    yield sse(name, data, event_id=i)
                    sent = i + 1
                    if name == "done":
                        return
                if state in TERMINAL and sent >= count:
                    return  # reconnected after `done`: nothing left to deliver
                await asyncio.sleep(0.02)
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


def sse(event: str, data: dict, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
