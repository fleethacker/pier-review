"""Shared API state and dependencies: job store, modeling client, per-agent physics toolkits."""

import os
from typing import Annotated

from fastapi import Depends

from mooring.core.jobs import JobStore

from ..shared.storage import persistence_enabled
from ..physics.client import ModelingClient
from ..physics.toolkit import PhysicsToolkit

API_PREFIX = "/api/v1"
_workers = int(os.environ.get("AGENTS_WORKERS", "2"))
_queue = int(os.environ.get("AGENTS_QUEUE", "16"))
if _workers < 1 or _queue < 0:
    raise ValueError("AGENTS_WORKERS must be positive and AGENTS_QUEUE nonnegative")
JOBS = JobStore(API_PREFIX, workers=_workers, queue_size=_queue, persist=persistence_enabled(), namespace="agents")


def get_client() -> ModelingClient:
    """Overridden in tests to talk to an in-process modeling app."""
    from .security import credential
    return ModelingClient(authorization=credential.get())


Client = Annotated[ModelingClient, Depends(get_client)]


def _toolkit(caller: str):
    def dep(client: Client) -> PhysicsToolkit:
        return PhysicsToolkit(client, caller)

    return Annotated[PhysicsToolkit, Depends(dep)]


IntakeTools = _toolkit("intake")
PlannerTools = _toolkit("planner")
SafetyTools = _toolkit("safety")
VisionTools = _toolkit("vision")
