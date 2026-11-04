"""Agents service tests. The modeling service runs in-process behind an httpx ASGI transport, so the agents
talk to it over (in-memory) HTTP exactly as they will in deployment."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app as modeling_app
from mooring.examples import EXAMPLES
from mooring_agents.api.main import app, get_client
from mooring_agents.physics.client import ModelingClient
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
    pdf = client.get(f"{P}/safety-sheets/{sid}/render?format=pdf")
    from mooring_agents.safety.sheet import pdf_available

    if pdf_available():
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")
    else:  # system libraries missing: a clear 501, never a crash
        assert pdf.status_code == 501 and "pango" in pdf.json()["detail"].lower()
    approved = client.post(f"{P}/safety-sheets/{sid}/approvals",
                           json={"role": "co", "name": "Commanding Officer", "decision": "approve"}).json()
    assert approved["locked"] and approved["approvals"][0]["role"] == "co"
    revised = client.post(f"{P}/safety-sheets", json={"plan_id": plan_id})
    assert revised.status_code == 201 and revised.json()["version"] == 2


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


# ---------- Intake, Physics gateway, Safety review and warnings ----------

from mooring_agents.schemas import IntakeReport, SafetyReview  # noqa: E402


@pytest.fixture(scope="module")
def scenario_id() -> str:
    return modeling.post(f"{P}/scenarios", json=EXAMPLES["scenario"]).json()["scenario_id"]


@pytest.fixture(scope="module")
def intake_report(scenario_id) -> IntakeReport:
    r = client.post(f"{P}/intake/reports", json={"scenario_id": scenario_id, "horizon_hours": 12})
    assert r.status_code == 202, r.text
    report = IntakeReport.model_validate(client.get(r.json()["status_url"]).json()["result"])
    assert client.get(f"{P}/intake/reports/{report.report_id}").status_code == 200
    return report


def test_intake_report_shape(intake_report):
    assert intake_report.planning_conditions[0].label == "Worst gust in horizon"
    assert intake_report.mst.ship_mst == "II"
    assert any(q.issue == "mock" for q in intake_report.data_quality)
    assert intake_report.tool_call_ids


def test_intake_with_storm_scenario_flags_red_windows():
    envsc = modeling.post(f"{P}/env/scenarios", json=EXAMPLES["env_scenario"]).json()["env_scenario_id"]
    r = client.post(f"{P}/intake/reports", json={"berth_id": "NAVSTA-NORFOLK-P12-N", "ship_class_id": "DDG-51-FIIA",
                                                  "side_to": "starboard", "horizon_hours": 2, "env_scenario_id": envsc})
    report = IntakeReport.model_validate(client.get(r.json()["status_url"]).json()["result"])
    assert any(w.kind == "gust" and w.severity == "RED" for w in report.windows)
    assert report.mst.mst_required == "II" and not report.mst.exceeds_ship_mst


@pytest.fixture(scope="module")
def planned(scenario_id, intake_report) -> str:
    r = client.post(f"{P}/agent/plans", json={"scenario_id": scenario_id, "intake_report_id": intake_report.report_id})
    assert r.status_code == 202, r.text
    return r.json()["plan_id"]


def test_plan_uses_intake_and_logs_every_tool_call(planned, intake_report):
    plan = AgentPlan.model_validate(client.get(f"{P}/agent/plans/{planned}").json())
    assert plan.intake_report_id == intake_report.report_id
    calls = client.get(f"{P}/physics/calls", params={"plan_id": planned}).json()
    logged = {c["result_id"] for c in calls if c["result_id"]}
    assert {c for item in plan.rationale for c in item.cites} <= logged


def test_physics_gateway_runs_and_logs_a_tool():
    r = client.post(f"{P}/physics/tools/analyze_mooring",
                    json={"input": EXAMPLES["mooring_analyze"], "caller": "ui", "plan_id": "plan_gateway_test"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["output"]["result_id"] == body["call"]["result_id"]
    assert client.get(f"{P}/physics/calls", params={"plan_id": "plan_gateway_test"}).json()[0]["tool"] == "analyze_mooring"
    assert client.post(f"{P}/physics/tools/do_magic", json={"input": {}}).status_code == 404


def test_physics_gateway_path_params_and_jobs():
    ship = client.post(f"{P}/physics/tools/get_ship", json={"input": {"class_id": "DDG-51-FIIA"}}).json()
    assert ship["output"]["class_id"] == "DDG-51-FIIA"
    rec = client.post(f"{P}/physics/tools/recommend_config", json={"input": EXAMPLES["mooring_recommend"]}).json()
    assert rec["output"]["result"]["candidates"]


def test_safety_review_and_sheet(planned, intake_report):
    r = client.post(f"{P}/safety/reviews", json={"plan_id": planned, "intake_report_id": intake_report.report_id})
    assert r.status_code == 202, r.text
    rv = SafetyReview.model_validate(client.get(r.json()["status_url"]).json()["result"])
    by_id = {c.check_id: c for c in rv.checks}
    assert by_id["CITES-RESOLVE"].passed and by_id["CITES-IN-LEDGER"].passed
    assert rv.thresholds.limit_breaking_gust_kt > rv.thresholds.limit_wll_gust_kt
    sheet_r = client.post(f"{P}/safety-sheets", json={"plan_id": planned, "review_id": rv.review_id})
    assert sheet_r.status_code == 201, sheet_r.text
    sheet = SafetySheet.model_validate(client.get(f"{P}/safety-sheets/{sheet_r.json()['sheet_id']}").json())
    assert sheet.review_id == rv.review_id
    assert any("breaking" in g.condition for g in sheet.go_no_go)


def test_safety_watch_streams_gust_warnings(planned):
    with client.stream("GET", f"{P}/safety/watch/{planned}",
                       params={"interval_s": 0, "limit": 2, "heartbeat_minutes": 0}) as s:
        text = "".join(s.iter_text())
    assert text.count("event: warning") == 2 and "pct_of_wll_limit" in text
