"""Bounded agent work, using the shared job executor with actual completion and cancellation.

Agent state is process-local until durable storage is explicitly configured. A request
never waits for LLM narration or a complete planning loop merely to acknowledge work.
"""
import asyncio
import math
import os
from collections.abc import Awaitable, Callable

from mooring.core.jobs import JobContext, JobStore

from ..physics.toolkit import PhysicsToolkit


def timeout_seconds() -> float:
    value = float(os.environ.get('AGENTS_JOB_TIMEOUT_S', '300'))
    if not math.isfinite(value) or value <= 0:
        raise ValueError('AGENTS_JOB_TIMEOUT_S must be finite and positive')
    return value


def submit_async(store: JobStore, kind: str, tk: PhysicsToolkit,
                 operation: Callable[[JobContext], Awaitable], *, job_id: str | None = None):
    deadline = timeout_seconds()

    def task(ctx: JobContext):
        tk.checkpoint = ctx.check_cancelled
        tk.client.checkpoint = ctx.check_cancelled

        async def execute():
            ctx.check_cancelled()
            ctx.progress(0, 'Agent work started')
            async with asyncio.timeout(deadline):
                result = await operation(ctx)
            ctx.check_cancelled()
            return result

        return asyncio.run(execute())

    return store.submit_task(kind, task, job_id=job_id, deadline_s=deadline)
