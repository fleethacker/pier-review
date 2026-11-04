"""Result envelopes, ids and the in-memory results store, shared by the modeling and agents services."""

import hashlib
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel

from mooring.core.schemas import Finding

MOCK_NOTE = "MOCK BACKEND: placeholder values for UI development, not validated physics."
MOCK_VERSION = "0.0.0-mock"

# result_id -> envelope (JSON-ready dict). Lets the agent and safety sheet cite results by id.
RESULTS: dict[str, dict] = {}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


def inputs_hash(request: BaseModel | dict | None) -> str:
    if request is None:
        raw = b""
    elif isinstance(request, BaseModel):
        raw = request.model_dump_json().encode()
    else:
        import json

        raw = json.dumps(request, sort_keys=True, default=str).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def worst(statuses: Iterable[str]) -> str:
    order = {"GREEN": 0, "INFO": 0, "AMBER": 1, "RED": 2}
    w = max((order[s] for s in statuses), default=0)
    return ["GREEN", "AMBER", "RED"][w]


def status_from_pct(pct: float, amber: float = 80.0, red: float = 100.0) -> str:
    if pct > red:
        return "RED"
    if pct > amber:
        return "AMBER"
    return "GREEN"


def envelope(
    cls,
    *,
    model: str,
    request: BaseModel | dict | None,
    result,
    status: str,
    assumptions: Iterable[str] = (),
    warnings: Iterable[Finding] = (),
):
    env = cls(
        result_id=new_id("res"),
        model=model,
        model_version=MOCK_VERSION,
        backend="mock",
        inputs_hash=inputs_hash(request),
        computed_at_utc=utcnow(),
        status=status,
        assumptions=[MOCK_NOTE, *assumptions],
        warnings=list(warnings),
        result=result,
    )
    RESULTS[env.result_id] = env.model_dump(mode="json")
    return env
