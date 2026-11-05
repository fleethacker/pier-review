"""Persistence and concurrent budget checks for the physics audit ledger."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest

from mooring_agents.physics import ledger
from mooring_agents.physics.schemas import ToolCall


@pytest.fixture(autouse=True)
def isolated_ledger(monkeypatch):
    monkeypatch.delenv("AGENTS_LEDGER_DB", raising=False)
    previous_calls = list(ledger.LEDGER)
    ledger.LEDGER.clear()
    monkeypatch.setattr(ledger, "_SCOPES", {})
    yield
    ledger.LEDGER[:] = previous_calls


def make_call(call_id: str, plan_id: str | None = "plan_a") -> ToolCall:
    return ToolCall(
        call_id=call_id, at_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        caller="planner", plan_id=plan_id, tool="get_ship", request_hash="request_hash",
        result_id=None, status=None, duration_ms=0,
    )


def test_sqlite_is_off_by_default(monkeypatch):
    def unexpected_sqlite(*args, **kwargs):
        pytest.fail("Default ledger must not open SQLite")

    monkeypatch.setattr(ledger.sqlite3, "connect", unexpected_sqlite)
    call = make_call("call_memory")
    ledger.append_call(call)
    assert ledger.LEDGER == [call]
    assert ledger.calls_for("plan_a") == [call]


@pytest.mark.parametrize("persistent", [False, True], ids=["memory", "sqlite"])
def test_filter_order_and_final_outcome(persistent, monkeypatch, tmp_path):
    if persistent:
        monkeypatch.setenv("AGENTS_LEDGER_DB", str(tmp_path / "calls.sqlite"))
    first = make_call("call_first")
    second = make_call("call_second", "plan_b")
    third = make_call("call_third")
    for call in (first, second, third):
        ledger.append_call(call)
    completed = second.model_copy(update={"result_id": "res_ship", "status": "GREEN", "duration_ms": 2.5})
    ledger.update_call(completed)
    assert ledger.calls_for() == [first, completed, third]
    assert ledger.calls_for("plan_a") == [first, third]
    assert ledger.calls_for("plan_b") == [completed]
    assert ledger.calls_for("missing_plan") == []
    if persistent:
        assert ledger.LEDGER == []


@pytest.mark.parametrize("persistent", [False, True], ids=["memory", "sqlite"])
def test_concurrent_reservations_cannot_exceed_budget(persistent, monkeypatch, tmp_path):
    if persistent:
        monkeypatch.setenv("AGENTS_LEDGER_DB", str(tmp_path / "concurrent.sqlite"))
    barrier = Barrier(8)

    def reserve(index):
        call = make_call(f"call_{index}")
        barrier.wait(timeout=10)
        allowed = ledger.reserve_call(call, 3)
        ledger.update_call(call.model_copy(update={"error": None if allowed else "budget_exceeded"}))
        return allowed

    with ThreadPoolExecutor(max_workers=8) as executor:
        allowed = list(executor.map(reserve, range(8)))
    assert sum(allowed) == 3
    calls = ledger.calls_for("plan_a")
    assert len(calls) == 8
    assert len({call.call_id for call in calls}) == 8
    assert sum(call.error == "budget_exceeded" for call in calls) == 5
    assert ledger.reserve_call(make_call("independent", "plan_b"), 3)


@pytest.mark.parametrize("persistent", [False, True], ids=["memory", "sqlite"])
def test_anonymous_scopes_have_independent_budgets(persistent, monkeypatch, tmp_path):
    if persistent:
        monkeypatch.setenv("AGENTS_LEDGER_DB", str(tmp_path / "anonymous.sqlite"))
    assert ledger.reserve_call(make_call("call_one", None), 1, scope_id="toolkit_a")
    assert not ledger.reserve_call(make_call("call_two", None), 1, scope_id="toolkit_a")
    assert ledger.reserve_call(make_call("call_three", None), 1, scope_id="toolkit_b")
    assert all(call.plan_id is None for call in ledger.calls_for())


def run_python(source: str, *args: str) -> str:
    return subprocess.run(
        [sys.executable, "-c", source, *args], env=os.environ.copy(),
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout


def test_sqlite_survives_process_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTS_LEDGER_DB", str(tmp_path / "restart.sqlite"))
    run_python("""
from datetime import datetime, timezone
from mooring_agents.physics.ledger import reserve_call, update_call
from mooring_agents.physics.schemas import ToolCall
call = ToolCall(call_id='call_before_restart', at_utc=datetime.now(timezone.utc),
                caller='planner', plan_id='persistent_plan', tool='analyze_mooring',
                request_hash='hash', result_id=None, status=None, duration_ms=0)
assert reserve_call(call, 1)
update_call(call.model_copy(update={'result_id': 'res_persisted', 'status': 'AMBER'}))
""")
    output = run_python("""
import json
from mooring_agents.physics.ledger import calls_for, reserve_call, update_call
before = calls_for('persistent_plan')
assert len(before) == 1
next_call = before[0].model_copy(update={'call_id': 'call_after_restart', 'result_id': None, 'status': None})
allowed = reserve_call(next_call, 1)
assert not allowed
update_call(next_call.model_copy(update={'error': 'budget_exceeded'}))
print(json.dumps([call.model_dump(mode='json') for call in calls_for('persistent_plan')]))
""")
    calls = json.loads(output)
    assert [call["call_id"] for call in calls] == ["call_before_restart", "call_after_restart"]
    assert calls[0]["result_id"] == "res_persisted"
    assert calls[0]["status"] == "AMBER"
    assert calls[1]["error"] == "budget_exceeded"
    assert [call.model_dump(mode="json") for call in ledger.calls_for("persistent_plan")] == calls


def test_sqlite_budget_is_shared_across_processes(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTS_LEDGER_DB", str(tmp_path / "processes.sqlite"))
    source = """
import json
import sys
import time
from datetime import datetime, timezone
from mooring_agents.physics.ledger import reserve_call, update_call
from mooring_agents.physics.schemas import ToolCall
allowed = []
for index in range(8):
    call = ToolCall(call_id=f'call_{sys.argv[1]}_{index}', at_utc=datetime.now(timezone.utc),
                    caller='planner', plan_id='shared_plan', tool='get_ship', request_hash='hash',
                    result_id=None, status=None, duration_ms=0)
    accepted = reserve_call(call, 5)
    allowed.append(accepted)
    update_call(call.model_copy(update={'error': None if accepted else 'budget_exceeded'}))
    time.sleep(0.01)
print(json.dumps(allowed))
"""
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda worker: json.loads(run_python(source, str(worker))), range(3)))
    assert sum(sum(allowed) for allowed in results) == 5
    calls = ledger.calls_for("shared_plan")
    assert len(calls) == 24
    assert len({call.call_id for call in calls}) == 24
    assert sum(call.error == "budget_exceeded" for call in calls) == 19


@pytest.mark.parametrize('persistent', [False, True], ids=['memory', 'sqlite'])
def test_operation_budgets_are_atomic_but_later_reviews_get_new_allowance(persistent, monkeypatch, tmp_path):
    if persistent: monkeypatch.setenv('AGENTS_LEDGER_DB', str(tmp_path / 'operations.sqlite'))
    barrier = Barrier(8)
    def reserve(index):
        call = make_call(f'operation_call_{index}').model_copy(update={'caller':'safety','operation_id':'review_one'})
        barrier.wait(timeout=10)
        return ledger.reserve_call(call, 3)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 3
    next_review = make_call('next_review').model_copy(update={'caller':'safety','operation_id':'review_two'})
    assert ledger.reserve_call(next_review, 3)
    assert {call.operation_id for call in ledger.calls_for('plan_a')} == {'review_one','review_two'}
    # A newly constructed toolkit using the same operation cannot reset its allowance.
    replay = next_review.model_copy(update={'call_id':'same_operation','operation_id':'review_one'})
    assert not ledger.reserve_call(replay, 3)
