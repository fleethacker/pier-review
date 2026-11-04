"""Agents service tests. The modeling service runs in-process behind an httpx ASGI transport, so the agents
talk to it over (in-memory) HTTP exactly as they will in deployment."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app as modeling_app
from mooring.mock.examples import EXAMPLES
from mooring_agents.api.main import app, get_client
from mooring_agents.clients import ModelingClient
from mooring_agents.schemas import AgentPlan, SafetySheet

P = "/api/v1"
modeling = TestClient(modeling_app)
app.dependency_overrides[get_client] = lambda: ModelingClient(
    base_url="http://modeling/api/v1", transport=httpx.ASGITransport(app=modeling_app))
client = TestClient(app)


@pytest.fixture(scope="module")
def plan_id() -> str:
    sid = modeling.post(f"{P}/scenarios", json=EXAMPLES["scenario"]).json()["scenario_id"]
    r = client.post(f"{P}/agent/plans", json={"scenario_id": sid})
    assert r.status_code == 202, r.text
    return r.json()["plan_id"]


def test_plan_runs_and_cites_results(plan_id):
    plan = AgentPlan.model_validate(client.get(f"{P}/agent/plans/{plan_id}").json())
    assert plan.state == "succeeded" and plan.config and plan.tug_plan and plan.sequence
    assert all(item.cites for item in plan.rationale)
    for rid in {c for item in plan.rationale for c in item.cites}:
        assert modeling.get(f"{P}/results/{rid}").status_code == 200, rid


def test_plan_events_stream(plan_id):
    with client.stream("GET", f"{P}/agent/plans/{plan_id}/events?follow=false") as s:
        text = "".join(s.iter_text())
    assert "event: step" in text and "event: proposal" in text and text.rstrip().split("\n")[-2] == "event: done"


def test_follow_up_message(plan_id):
    r = client.post(f"{P}/agent/plans/{plan_id}/messages", json={"text": "What if the wind backs to NW at 35 kt?"})
    assert r.status_code == 202


def test_safety_sheet_lifecycle(plan_id):
    r = client.post(f"{P}/safety-sheets", json={"plan_id": plan_id})
    assert r.status_code == 201, r.text
    sid = r.json()["sheet_id"]
    sheet = SafetySheet.model_validate(client.get(f"{P}/safety-sheets/{sid}").json())
    assert sheet.line_plan and not sheet.locked
    html = client.get(f"{P}/safety-sheets/{sid}/render?format=html")
    assert html.status_code == 200 and "Mooring Evolution Safety Sheet" in html.text
    assert client.get(f"{P}/safety-sheets/{sid}/render?format=pdf").status_code == 501
    approved = client.post(f"{P}/safety-sheets/{sid}/approvals",
                           json={"role": "co", "name": "Commanding Officer", "decision": "approve"}).json()
    assert approved["locked"] and approved["approvals"][0]["role"] == "co"


def test_berth_vision_round_trip():
    meta = {"image_kind": "satellite", "georef": {"scale_ft_per_px": 0.5}, "ship_class_id": "DDG-51-FIIA",
            "side_to": "starboard"}
    r = client.post(f"{P}/berth-vision/analyze", files={"image": ("pier.png", b"\x89PNG fake", "image/png")},
                    data={"metadata": json.dumps(meta)})
    assert r.status_code == 202, r.text
    st = client.get(r.json()["status_url"]).json()
    assert st["state"] == "succeeded"
    result = st["result"]["result"]
    assert result["detections"] and result["recommended_config"] and result["questions"]
    saved = client.post(f"{P}/berth-vision/{r.json()['job_id']}/confirm", json={"berth": result["draft_berth"]})
    assert saved.status_code == 201
    assert modeling.get(f"{P}/berths/{saved.json()['berth_id']}").status_code == 200


def test_bad_vision_metadata_is_422():
    r = client.post(f"{P}/berth-vision/analyze", files={"image": ("x.png", b"x", "image/png")},
                    data={"metadata": '{"image_kind": "selfie"}'})
    assert r.status_code == 422


def test_tools_catalog():
    names = {t["name"] for t in client.get(f"{P}/tools").json()}
    assert {"analyze_mooring", "plan_tugs", "recommend_config"} <= names


def test_unknown_scenario_passes_through_404():
    assert client.post(f"{P}/agent/plans", json={"scenario_id": "scn_missing"}).status_code == 404
