"""Integration tests for validation, limits and the public Physics gateway."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app as modeling_app
from mooring.core.envelopes import inputs_hash
from mooring.examples import EXAMPLES
from mooring_agents.physics import PhysicsToolkit, calls_for, summarize, tool_definitions
from mooring_agents.physics.client import ModelingClient, ModelingError
from mooring_agents.physics.toolkit import LEDGER, UnknownTool


@pytest.fixture(autouse=True)
def isolated_ledger(monkeypatch):
    for variable in ("AGENTS_LEDGER_DB", "AGENTS_MAX_TOOL_CALLS", "AGENTS_TOOL_TIMEOUT_S"):
        monkeypatch.delenv(variable, raising=False)
    saved = LEDGER[:]
    LEDGER.clear()
    yield
    LEDGER[:] = saved


@pytest.fixture
def recorded_client():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"result_id": "res_test", "status": "AMBER", "result": {}})

    return ModelingClient(base_url="http://modeling/api/v1", transport=httpx.MockTransport(respond)), requests


def test_public_imports_are_ready_for_planner():
    assert len(tool_definitions()) == 18  # Includes canonical saved-scenario environment resolution.
    assert summarize("analyze_mooring", {"status": "AMBER"}) == "analyze_mooring: AMBER"


@pytest.mark.parametrize(("name", "input", "path"), [
    ("get_ship", {}, "$.class_id"),
    ("get_forecast", {"berth_id": "pier", "hours": 121}, "$.hours"),
    ("get_forecast", {"berth_id": "pier", "hours": True}, "$.hours"),
    ("get_ship", [], "$"),
    ("get_environment", {"berth_id": "pier", "heading_true_deg": float("nan")}, "$.heading_true_deg"),
])
def test_invalid_input_rejected_before_http_and_logged(recorded_client, name, input, path):
    client, requests = recorded_client
    toolkit = PhysicsToolkit(client, "planner", "invalid")
    output = asyncio.run(toolkit.call(name, input))
    assert output["error"]["code"] == "invalid_input"
    assert any(issue["path"] == path and issue["message"] for issue in output["error"]["fields"])
    assert requests == []
    entry, = calls_for("invalid")
    assert json.loads(entry.error) == output["error"]
    assert entry.caller == "planner" and entry.tool == name
    assert entry.request_hash == inputs_hash(input)
    assert entry.result_id is None and entry.status is None and toolkit.last_call == entry


def test_nested_post_and_circular_inputs_rejected(recorded_client):
    client, requests = recorded_client
    toolkit = PhysicsToolkit(client, "planner", "nested")
    body = deepcopy(EXAMPLES["mooring_analyze"])
    body["config"]["lines"][0]["parts"] = 7
    output = asyncio.run(toolkit.call("analyze_mooring", body))
    assert output["error"]["code"] == "invalid_input"
    assert any(issue["path"].startswith("$.config") for issue in output["error"]["fields"])
    circular = {}
    circular["cycle"] = circular
    output = asyncio.run(toolkit.call("get_ship", circular))
    assert output["error"]["fields"][0]["path"] == "$.cycle"
    assert len(calls_for("nested")) == 2 and all(entry.error for entry in calls_for("nested"))
    assert requests == []


def test_valid_post_passes_through_unchanged(recorded_client):
    client, requests = recorded_client
    toolkit = PhysicsToolkit(client, "planner", "valid")
    body = deepcopy(EXAMPLES["mooring_analyze"])
    before = deepcopy(body)
    output = asyncio.run(toolkit.call("analyze_mooring", body))
    assert body == before
    assert output == {"result_id": "res_test", "status": "AMBER", "result": {}}
    assert requests[0].method == "POST" and requests[0].url.path == "/api/v1/mooring/analyze"
    assert json.loads(requests[0].content) == body
    entry, = calls_for("valid")
    assert entry.result_id == output["result_id"] and entry.status == output["status"]
    assert entry.error is None and entry.duration_ms >= 0


def test_get_encoding_and_optional_null_query(recorded_client):
    client, requests = recorded_client
    toolkit = PhysicsToolkit(client, "planner")
    asyncio.run(toolkit.call("get_ship", {"class_id": "ship ?#"}))
    assert requests[0].url.raw_path == b"/api/v1/ships/ship%20%3F%23"
    asyncio.run(toolkit.call("get_environment", {"berth_id": "pier", "env_scenario_id": None}))
    assert dict(requests[1].url.params) == {"berth_id": "pier"}


def test_default_budget_stops_call_41(recorded_client):
    client, requests = recorded_client
    toolkit = PhysicsToolkit(client, "planner", "default")
    assert toolkit.timeout_s == 30

    async def run():
        for _ in range(40):
            assert "error" not in await toolkit.call("get_ship", {"class_id": "ship"})
        return await toolkit.call("get_ship", {"class_id": "ship"})

    output = asyncio.run(run())
    assert output["error"]["code"] == "budget_exceeded" and output["error"]["max_calls"] == 40
    assert len(requests) == 40 and len(calls_for("default")) == 41
    assert json.loads(calls_for("default")[-1].error) == output["error"]


def test_budget_shared_across_instances_and_invalid_attempts(monkeypatch, recorded_client):
    monkeypatch.setenv("AGENTS_MAX_TOOL_CALLS", "2")
    client, requests = recorded_client
    first, second = PhysicsToolkit(client, "planner", "shared"), PhysicsToolkit(client, "planner", "shared")
    asyncio.run(first.call("get_ship", {}))  # invalid input still consumes the budget
    asyncio.run(second.call("get_ship", {"class_id": "ship"}))
    output = asyncio.run(first.call("get_ship", {"class_id": "ship"}))
    assert output["error"]["code"] == "budget_exceeded" and len(requests) == 1
    independent = PhysicsToolkit(client, "planner", "separate")
    assert "error" not in asyncio.run(independent.call("get_ship", {"class_id": "ship"}))
    assert len(calls_for("shared")) == 3 and len(calls_for("separate")) == 1


def test_safety_budget_is_not_consumed_by_the_planner(monkeypatch, recorded_client):
    monkeypatch.setenv("AGENTS_MAX_TOOL_CALLS", "1")
    client, requests = recorded_client
    planner, safety = PhysicsToolkit(client, "planner", "plan-x"), PhysicsToolkit(client, "safety", "plan-x")
    asyncio.run(planner.call("get_ship", {"class_id": "ship"}))
    assert asyncio.run(planner.call("get_ship", {"class_id": "ship"}))["error"]["code"] == "budget_exceeded"
    assert "error" not in asyncio.run(safety.call("get_ship", {"class_id": "ship"}))


def test_anonymous_toolkit_budgets_are_independent(monkeypatch, recorded_client):
    monkeypatch.setenv("AGENTS_MAX_TOOL_CALLS", "1")
    client, requests = recorded_client
    first = PhysicsToolkit(client, "planner")
    second = PhysicsToolkit(client, "planner")
    for toolkit in (first, second):
        assert "error" not in asyncio.run(toolkit.call("get_ship", {"class_id": "ship"}))
        rejected = asyncio.run(toolkit.call("get_ship", {"class_id": "ship"}))
        assert rejected["error"]["code"] == "budget_exceeded"
    assert len(requests) == 2
    entries = calls_for()
    assert len(entries) == 4 and all(entry.plan_id is None for entry in entries)
    assert sum(entry.error is not None for entry in entries) == 2


def test_zero_budget_rejects_before_http(monkeypatch, recorded_client):
    monkeypatch.setenv("AGENTS_MAX_TOOL_CALLS", "0")
    client, requests = recorded_client
    toolkit = PhysicsToolkit(client, "planner", "disabled")
    output = asyncio.run(toolkit.call("get_ship", {"class_id": "ship"}))
    assert output["error"]["code"] == "budget_exceeded"
    assert output["error"]["max_calls"] == 0
    assert requests == []
    entry, = calls_for("disabled")
    assert json.loads(entry.error) == output["error"]


@pytest.mark.parametrize(("variable", "value"), [
    ("AGENTS_MAX_TOOL_CALLS", "-1"),
    ("AGENTS_TOOL_TIMEOUT_S", "0"),
    ("AGENTS_TOOL_TIMEOUT_S", "nan"),
    ("AGENTS_TOOL_TIMEOUT_S", "inf"),
])
def test_invalid_limit_configuration_fails_early(monkeypatch, recorded_client, variable, value):
    monkeypatch.setenv(variable, value)
    client, requests = recorded_client
    with pytest.raises(ValueError):
        PhysicsToolkit(client, "planner", "bad_config")
    assert requests == [] and calls_for() == []


@pytest.mark.parametrize("sqlite", [False, True])
def test_concurrent_calls_reserve_before_http(monkeypatch, tmp_path, sqlite):
    monkeypatch.setenv("AGENTS_MAX_TOOL_CALLS", "3")
    if sqlite:
        monkeypatch.setenv("AGENTS_LEDGER_DB", str(tmp_path / "calls.db"))
    requests = []

    async def respond(request):
        requests.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"class_id": "ship"})

    client = ModelingClient(transport=httpx.MockTransport(respond))

    async def run():
        return await asyncio.gather(*[PhysicsToolkit(client, "planner", "concurrent").call(
            "get_ship", {"class_id": "ship"}) for _ in range(9)])

    outputs = asyncio.run(run())
    assert len(requests) == 3 and sum("error" in output for output in outputs) == 6
    entries = calls_for("concurrent")
    assert len(entries) == 9 and sum(entry.error is not None for entry in entries) == 6


@pytest.mark.parametrize("job", [False, True])
def test_timeout_covers_request_and_job_polling(monkeypatch, job):
    monkeypatch.setenv("AGENTS_TOOL_TIMEOUT_S", "0.02")
    requests, cancelled = [], []

    async def respond(request):
        requests.append(request)
        if job:
            if request.method == "POST":
                return httpx.Response(202, json={"job_id": "job_wait", "status_url": "/api/v1/jobs/job_wait"})
            return httpx.Response(200, json={"state": "running"})
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    toolkit = PhysicsToolkit(ModelingClient(transport=httpx.MockTransport(respond)), "planner", "timeout")
    name, body = ("recommend_config", EXAMPLES["mooring_recommend"]) if job else ("get_ship", {"class_id": "ship"})
    output = asyncio.run(toolkit.call(name, body))
    assert output["error"]["code"] == "timeout" and output["error"]["timeout_s"] == 0.02
    entry, = calls_for("timeout")
    assert json.loads(entry.error) == output["error"]
    assert [r.method for r in requests] == (["POST", "GET", "DELETE"] if job else ["GET"])
    assert job or cancelled == [True]


def test_external_cancellation_is_logged_and_reraised():
    requests = []

    async def run():
        started = asyncio.Event()

        async def respond(request):
            requests.append(request)
            started.set()
            await asyncio.Future()

        toolkit = PhysicsToolkit(ModelingClient(transport=httpx.MockTransport(respond)), "planner", "cancelled")
        task = asyncio.create_task(toolkit.call("get_ship", {"class_id": "ship"}))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return toolkit

    toolkit = asyncio.run(run())
    assert len(requests) == 1
    entry, = calls_for("cancelled")
    assert "cancel" in entry.error.lower()
    assert entry.result_id is None and entry.duration_ms >= 0
    assert toolkit.last_call == entry


def test_typed_helpers_share_guards_and_keep_types(monkeypatch):
    monkeypatch.setenv("AGENTS_MAX_TOOL_CALLS", "2")
    toolkit = PhysicsToolkit(ModelingClient(base_url="http://modeling/api/v1",
                                           transport=httpx.ASGITransport(app=modeling_app)), "planner", "typed")
    assert asyncio.run(toolkit.ship("DDG-51-FIIA")).class_id == "DDG-51-FIIA"
    with pytest.raises(ModelingError) as invalid:
        asyncio.run(toolkit.forecast("pier", hours=999))
    assert invalid.value.status == 422
    with pytest.raises(ModelingError) as exhausted:
        asyncio.run(toolkit.ship("DDG-51-FIIA"))
    assert exhausted.value.status == 429 and len(calls_for("typed")) == 3


def test_invalid_typed_response_is_logged_with_result_id(recorded_client):
    client, requests = recorded_client
    toolkit = PhysicsToolkit(client, "planner", "invalid_response")
    with pytest.raises(ModelingError) as invalid:
        asyncio.run(toolkit.ship("ship"))
    assert invalid.value.status == 502 and len(requests) == 1
    entry, = calls_for("invalid_response")
    assert entry.result_id == "res_test"
    assert entry.error == invalid.value.detail
    assert toolkit.last_call == entry


@pytest.mark.parametrize("failure", ["http", "transport", "unknown"])
def test_failures_are_logged(failure):
    def respond(request):
        if failure == "transport":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(404, json={"detail": "missing"})

    toolkit = PhysicsToolkit(ModelingClient(transport=httpx.MockTransport(respond)), "planner", "failed")
    with pytest.raises(UnknownTool if failure == "unknown" else ModelingError):
        asyncio.run(toolkit.call("unknown" if failure == "unknown" else "get_ship", {"class_id": "missing"}))
    entry, = calls_for("failed")
    assert entry.error and entry.result_id is None


def test_sqlite_survives_new_toolkit_and_preserves_budget(monkeypatch, tmp_path, recorded_client):
    monkeypatch.setenv("AGENTS_LEDGER_DB", str(tmp_path / "ledger.sqlite"))
    monkeypatch.setenv("AGENTS_MAX_TOOL_CALLS", "1")
    client, requests = recorded_client
    toolkit = PhysicsToolkit(client, "planner", "persisted")
    asyncio.run(toolkit.call("get_ship", {"class_id": "ship"}))
    saved = toolkit.last_call
    del toolkit
    LEDGER.clear()
    replacement = PhysicsToolkit(client, "planner", "persisted")  # same plan and caller after a restart
    assert calls_for("persisted") == [saved]
    output = asyncio.run(replacement.call("get_ship", {"class_id": "ship"}))
    assert output["error"]["code"] == "budget_exceeded"
    assert len(requests) == 1 and len(calls_for("persisted")) == 2 and calls_for("other") == []


def test_gateway_returns_structured_errors(monkeypatch, recorded_client):
    from mooring_agents.api.main import app, get_client

    modeling, requests = recorded_client
    monkeypatch.setenv("AGENTS_MAX_TOOL_CALLS", "1")
    monkeypatch.setitem(app.dependency_overrides, get_client, lambda: modeling)
    with TestClient(app) as gateway:
        response = gateway.post("/api/v1/physics/tools/get_ship", json={"input": {}, "plan_id": "gateway"})
        assert response.status_code == 200
        body = response.json()
        assert body["output"]["error"]["fields"][0]["path"] == "$.class_id"
        assert json.loads(body["call"]["error"]) == body["output"]["error"]
        response = gateway.post("/api/v1/physics/tools/get_ship",
                                json={"input": {"class_id": "ship"}, "plan_id": "gateway"})
        assert response.json()["output"]["error"]["code"] == "budget_exceeded"
    assert requests == []
