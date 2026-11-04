"""Result envelopes, ids and the in-memory results store, shared by the modeling and agents services."""

import hashlib
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel

from mooring.core.store import ResultStore
from mooring.core.schemas import Finding, ResultManifest, Validity, ValidityState

MOCK_NOTE = "MOCK BACKEND: placeholder values for UI development, not validated physics."
MOCK_VERSION = "0.0.0-mock"

# result_id -> envelope (JSON-ready dict). Lets the agent and safety sheet cite results by id.
# Persistent (SQLite, see core/store.py) and write-once.
RESULTS = ResultStore()


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


def resolved_inputs_hash(resolved: BaseModel | dict) -> str:
    """Hash of the inputs after defaults and references are resolved (canonical, key-sorted JSON).

    Distinct from `inputs_hash`, whose meaning (the request as sent) is unchanged. Stable across dict ordering.
    """
    import json

    data = resolved.model_dump(mode="json") if isinstance(resolved, BaseModel) else resolved
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validity_state(env: BaseModel | dict) -> ValidityState:
    """Validity of an envelope or its JSON dict. A response without validity is `unknown`, never `valid`."""
    v = env.get("validity") if isinstance(env, dict) else getattr(env, "validity", None)
    if v is None:
        return "unknown"
    return v["state"] if isinstance(v, dict) else v.state


def status_with_validity(status: str, validity: Validity | None) -> str:
    """Lift a computed status so it agrees with its validity: invalid is RED, limited is at least AMBER."""
    if validity is None:
        return status
    if validity.state == "invalid":
        return "RED"
    if validity.state == "limited":
        return worst([status, "AMBER"])
    return status


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
    validity: Validity | None = None,
    manifest: ResultManifest | None = None,
    backend: str = "mock",
    model_version: str = MOCK_VERSION,
):
    env = cls(
        result_id=new_id("res"),
        model=model,
        model_version=model_version,
        backend=backend,
        inputs_hash=inputs_hash(request),
        computed_at_utc=utcnow(),
        status=status_with_validity(status, validity),
        assumptions=[MOCK_NOTE, *assumptions] if backend == "mock" else list(assumptions),
        warnings=list(warnings),
        validity=validity,
        manifest=manifest,
        result=result,
    )
    RESULTS[env.result_id] = env.model_dump(mode="json")
    return env
