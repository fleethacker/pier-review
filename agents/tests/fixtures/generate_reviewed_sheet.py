"""Regenerate the offline consumer fixture through both services' HTTP APIs.

Run from the repository root with PYTHONPATH=modeling:agents. Existing fixture
bytes are replaced deliberately; identifiers and capture timestamps will change.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import time

import httpx
from fastapi.testclient import TestClient

os.environ.update(AGENTS_LLM_PROVIDER="none", MOORING_ENV_SOURCE="mock",
                  MOORING_RATE_PER_MINUTE="0", AGENTS_RATE_PER_MINUTE="0",
                  AGENTS_PERSIST="0", MOORING_DB=":memory:",
                  MOORING_AUTH_REQUIRED="0", AGENTS_AUTH_REQUIRED="0",
                  MOORING_API_KEYS="", AGENTS_API_KEYS="")

from modeling_api.main import app as modeling_app  # noqa: E402
from mooring_agents.api.main import app as agents_app, get_client  # noqa: E402
from mooring_agents.physics.client import ModelingClient  # noqa: E402


def generate():
    agents_app.dependency_overrides[get_client] = lambda: ModelingClient(
        base_url="http://modeling/api/v1", transport=httpx.ASGITransport(app=modeling_app))
    with TestClient(modeling_app) as modeling, TestClient(agents_app) as agents:
        def call(client, method, path, body=None):
            result = client.request(method, "/api/v1" + path, json=body)
            result.raise_for_status()
            return result.json()

        def finish(accepted):
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                job = call(agents, "GET", "/jobs/" + accepted["job_id"])
                if job["state"] == "succeeded":
                    return job["result"]
                assert job["state"] in ("queued", "running"), job
                time.sleep(0.1)
            raise AssertionError("Fixture job exceeded its deadline")

        case = next(c for c in call(modeling, "GET", "/demo/docking-cases")
                    if c["case_id"] == "ddg-supported-limited")
        weather = call(modeling, "POST", "/env/scenarios", case["environment_request"])
        body = deepcopy(case["scenario_request"])
        body.update(name="Reviewed sheet consumer fixture", env_source={
            "mode": "scenario", "env_scenario_id": weather["env_scenario_id"]})
        scenario = call(modeling, "POST", "/scenarios", body)
        report = finish(call(agents, "POST", "/intake/reports", {
            "scenario_id": scenario["scenario_id"], "horizon_hours": 48}))
        accepted = call(agents, "POST", "/agent/plans", {
            "scenario_id": scenario["scenario_id"], "intake_report_id": report["report_id"],
            "objective": "moor_for_forecast", "target_margin_pct_wll": 60, "max_iterations": 8})
        events = agents.get(accepted["events_url"] + "?follow=false")
        events.raise_for_status()
        assert "event: done" in events.text, events.text
        plan = call(agents, "GET", "/agent/plans/" + accepted["plan_id"])
        assert plan["state"] == "succeeded", plan
        review = finish(call(agents, "POST", "/safety/reviews", {"plan_id": plan["plan_id"]}))
        created = call(agents, "POST", "/safety-sheets", {
            "plan_id": plan["plan_id"], "review_id": review["review_id"]})
        sheet = call(agents, "GET", "/safety-sheets/" + created["sheet_id"])
        assert sheet["status"] == "AMBER" and sheet["validity"]["state"] == "limited"
        assert sheet["layout"]["state"] == "available", sheet["layout"]
        assert not sheet["approvals"] and not sheet["locked"]
        path = Path(__file__).with_name("reviewed_sheet.json")
        path.write_text(json.dumps(sheet, indent=2) + "\n")
        print(json.dumps({k: sheet[k] for k in ("sheet_id", "plan_id", "review_id", "analysis_result_id")}, indent=2))


if __name__ == "__main__":
    generate()
