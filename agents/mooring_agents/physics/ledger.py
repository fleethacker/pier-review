"""Tool-call ledger with optional SQLite persistence.

Set AGENTS_LEDGER_DB to a SQLite filename to persist the ledger. Otherwise calls
stay in the process-local LEDGER list. Reservations count pending calls as well
as completed calls, so concurrent toolkits cannot bypass a plan's budget.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock

from .schemas import ToolCall
from mooring.core import access

LEDGER: list[ToolCall] = []
_SCOPES: dict[str, str | None] = {}
_LOCK = RLock()


def _database_path() -> str | None:
    from ..shared.storage import persistence_enabled
    path = os.environ.get("AGENTS_LEDGER_DB") or (os.environ["MOORING_DB"] if persistence_enabled() else None)
    if path == ":memory:":
        raise ValueError("AGENTS_LEDGER_DB must name a file; unset it to use the in-memory ledger")
    return path


@contextmanager
def _database(path: str) -> Iterator[sqlite3.Connection]:
    # A fresh connection per operation works across event loops and threads.
    # Errors deliberately propagate: a call must not proceed without its audit.
    db = sqlite3.connect(os.path.expanduser(path), timeout=5)
    try:
        db.execute(
            "CREATE TABLE IF NOT EXISTS physics_tool_calls ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "call_id TEXT NOT NULL UNIQUE, plan_id TEXT, budget_key TEXT, "
            "payload TEXT NOT NULL)"
        )
        db.execute("CREATE INDEX IF NOT EXISTS physics_calls_plan ON physics_tool_calls (plan_id)")
        db.execute("CREATE INDEX IF NOT EXISTS physics_calls_budget ON physics_tool_calls (budget_key)")
        with db:
            yield db
    finally:
        db.close()


def _budget_key(call: ToolCall, scope_id: str | None = None) -> str | None:
    """Budgets are per plan and per caller (shared across instances of the same caller). The budget exists to stop
    a runaway LLM loop; the deterministic Safety review must never be starved by the Planner's spending."""
    if call.plan_id is not None:
        return f"plan:{call.plan_id}:{call.caller}"
    return f"toolkit:{scope_id}" if scope_id is not None else None


def calls_for(plan_id: str | None = None) -> list[ToolCall]:
    """Return calls in reservation order, optionally limited to a plan."""
    path = _database_path()
    if path is None:
        with _LOCK:
            return [call for call in LEDGER if (plan_id is None or call.plan_id == plan_id)
                    and access.allowed("agent_call", call.call_id)]
    with _database(path) as db:
        if plan_id is None:
            rows = db.execute("SELECT payload FROM physics_tool_calls ORDER BY sequence").fetchall()
        else:
            rows = db.execute(
                "SELECT payload FROM physics_tool_calls WHERE plan_id = ? ORDER BY sequence", (plan_id,)
            ).fetchall()
    return [call for row in rows if access.allowed("agent_call", (call := ToolCall.model_validate_json(row[0])).call_id)]


def append_call(call: ToolCall) -> None:
    """Record a call without applying a budget (for non-tool audit entries)."""
    access.claim("agent_call", call.call_id)
    path = _database_path()
    key = _budget_key(call)
    if path is None:
        with _LOCK:
            LEDGER.append(call)
            _SCOPES[call.call_id] = key
        return
    with _database(path) as db:
        db.execute(
            "INSERT INTO physics_tool_calls (call_id, plan_id, budget_key, payload) VALUES (?, ?, ?, ?)",
            (call.call_id, call.plan_id, key, call.model_dump_json()),
        )


def reserve_call(call: ToolCall, max_calls: int, *, scope_id: str | None = None) -> bool:
    """Atomically record an attempt and return whether it is within budget.

    Every attempt is retained, including rejected and invalid calls. The caller
    completes the pending entry with update_call(), including the error when a
    reservation is denied. Anonymous calls use an optional toolkit-local scope;
    without one they are logged but have no shared anonymous budget.
    """
    access.claim("agent_call", call.call_id)
    path = _database_path()
    key = _budget_key(call, scope_id)
    if path is None:
        with _LOCK:
            used = sum(
                1 for entry in LEDGER
                if (_budget_key(entry) if entry.plan_id is not None else _SCOPES.get(entry.call_id)) == key
            ) if key is not None else 0
            allowed = key is None or used < max_calls
            LEDGER.append(call)
            _SCOPES[call.call_id] = key
            return allowed
    with _database(path) as db:
        # Serializes count + insert across processes as well as toolkit instances.
        db.execute("BEGIN IMMEDIATE")
        used = db.execute(
            "SELECT COUNT(*) FROM physics_tool_calls WHERE budget_key = ?", (key,)
        ).fetchone()[0] if key is not None else 0
        allowed = key is None or used < max_calls
        db.execute(
            "INSERT INTO physics_tool_calls (call_id, plan_id, budget_key, payload) VALUES (?, ?, ?, ?)",
            (call.call_id, call.plan_id, key, call.model_dump_json()),
        )
        return allowed


def update_call(call: ToolCall) -> None:
    """Replace a pending entry with its final outcome without changing order."""
    path = _database_path()
    if path is None:
        with _LOCK:
            for index, entry in enumerate(LEDGER):
                if entry.call_id == call.call_id:
                    LEDGER[index] = call
                    return
        raise KeyError(f"Tool call {call.call_id!r} was not reserved")
    with _database(path) as db:
        cursor = db.execute(
            "UPDATE physics_tool_calls SET payload = ? WHERE call_id = ?", (call.model_dump_json(), call.call_id)
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Tool call {call.call_id!r} was not reserved")
