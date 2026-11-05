"""Agents service tests. The modeling service runs in-process behind an httpx ASGI transport, so the agents
talk to it over (in-memory) HTTP exactly as they will in deployment."""

import json
from datetime import UTC, datetime

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


def completed_status(url):
    # Wait for actual worker completion; MOCK_JOB_DELAY_S no longer controls agent work.
    from mooring_agents.api.state import JOBS
    job = JOBS.get(url.rsplit('/', 1)[-1])
    if job.future is not None:
        job.future.result(timeout=30)
    status = client.get(url).json()
    assert status['state'] == 'succeeded', status
    return status


def completed_plan(accepted):
    completed_status(f"{P}/jobs/{accepted['job_id']}")
    return accepted['plan_id']


@pytest.fixture(scope="module", autouse=True)
def fixed_environment_clock():
    # Mock forecast rounds to the hour: freeze the clock so coverage assertions never depend on wall time.
    from mooring.environment import mock as environment_mock
    from mooring_agents.intake import core
    from mooring import scenarios
    with pytest.MonkeyPatch.context() as patch:
        now = datetime(2026, 11, 4, 12, tzinfo=UTC)
        patch.setattr(environment_mock, "utcnow", lambda: now)
        patch.setattr(core, "utcnow", lambda: now)
        patch.setattr(scenarios, "utcnow", lambda: now)
        yield


@pytest.fixture(scope="module")
def plan_id() -> str:
    sid = modeling.post(f"{P}/scenarios", json=EXAMPLES["scenario"]).json()["scenario_id"]
    r = client.post(f"{P}/agent/plans", json={"scenario_id": sid})
    assert r.status_code == 202, r.text
    return completed_plan(r.json())


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
    st = completed_status(r.json()["status_url"])
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
    report = IntakeReport.model_validate(completed_status(r.json()["status_url"])["result"])
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
    report = IntakeReport.model_validate(completed_status(r.json()["status_url"])["result"])
    assert any(w.kind == "gust" and w.severity == "RED" for w in report.windows)
    assert report.mst.mst_required == "II" and not report.mst.exceeds_ship_mst


@pytest.fixture(scope="module")
def planned(scenario_id, intake_report) -> str:
    r = client.post(f"{P}/agent/plans", json={"scenario_id": scenario_id, "intake_report_id": intake_report.report_id})
    assert r.status_code == 202, r.text
    return completed_plan(r.json())


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
    rv = SafetyReview.model_validate(completed_status(r.json()["status_url"])["result"])
    by_id = {c.check_id: c for c in rv.checks}
    assert by_id["CITES-RESOLVE"].passed and by_id["CITES-IN-LEDGER"].passed
    # A WLL envelope with current, pretension and fenders cannot establish a line-breaking speed by square-root scaling.
    assert rv.thresholds.limit_breaking_gust_kt is None
    # Preserving installation tide exposes an unresolved envelope bearing in this fixed multi-tide fixture.
    # Unknown directional evidence must block a usable aggregate threshold, not be silently discarded.
    assert rv.thresholds.limit_wll_gust_kt is None
    assert any(point.limit_wll_gust_kt is None for point in rv.thresholds.directions)
    assert not by_id["GUST-THRESHOLD"].passed and rv.verdict != "ready_for_signature"
    sheet_r = client.post(f"{P}/safety-sheets", json={"plan_id": planned, "review_id": rv.review_id})
    assert sheet_r.status_code == 201, sheet_r.text
    sheet = SafetySheet.model_validate(client.get(f"{P}/safety-sheets/{sheet_r.json()['sheet_id']}").json())
    assert sheet.review_id == rv.review_id
    assert not any("estimated line breaking" in g.condition for g in sheet.go_no_go)


def test_safety_watch_streams_gust_warnings(planned):
    with client.stream("GET", f"{P}/safety/watch/{planned}",
                       params={"interval_s": 0, "limit": 2, "heartbeat_minutes": 0}) as s:
        text = "".join(s.iter_text())
    assert text.count("event: warning") == 2 and "pct_of_wll_limit" in text


def test_supported_demo_chain_preserves_limited_validity_and_forecast_review():
    from mooring.demo_cases import docking_cases
    case = docking_cases()[0]
    env_id = modeling.post(f'{P}/env/scenarios', json=case.environment_request.model_dump(mode='json')).json()['env_scenario_id']
    body = case.scenario_request.model_dump(mode='json')
    body['env_source']['env_scenario_id'] = env_id
    sid = modeling.post(f'{P}/scenarios', json=body).json()['scenario_id']
    intake = client.post(f'{P}/intake/reports', json={'scenario_id':sid,'horizon_hours':48})
    assert intake.status_code == 202
    report = completed_status(intake.json()['status_url'])['result']
    assert not report['windows']
    accepted = client.post(f'{P}/agent/plans', json={'scenario_id':sid,'intake_report_id':report['report_id']})
    assert accepted.status_code == 202, accepted.text
    completed_plan(accepted.json())
    plan = client.get(f"{P}/agent/plans/{accepted.json()['plan_id']}").json()
    assert plan['status'] == 'AMBER'
    review_job = client.post(f'{P}/safety/reviews', json={'plan_id':plan['plan_id']})
    assert review_job.status_code == 202
    review = completed_status(review_job.json()['status_url'])['result']
    assert review['intake_report_id'] == report['report_id']
    assert review['status'] == 'AMBER' and review['validity']['state'] == 'limited'
    assert review['verdict'] == 'ready_for_signature'
    created = client.post(f'{P}/safety-sheets',json={'plan_id':plan['plan_id'],'review_id':review['review_id']})
    assert created.status_code == 201
    sheet_id=created.json()['sheet_id']
    saved=client.get(f'{P}/safety-sheets/{sheet_id}').json()
    assert saved['status']=='AMBER' and saved['validity']['state']=='limited'
    html=client.get(f'{P}/safety-sheets/{sheet_id}/render').text
    assert 'Validity: limited' in html and 'not qualified for operational use' in html
    assert 'Fender-loading direction' not in html
    assert 'Unavailable; not established' in html


def test_vision_confirmation_cannot_overwrite_catalog_or_claim_certification(monkeypatch):
    monkeypatch.setenv('AGENTS_LLM_PROVIDER', 'none')
    r = client.post(f'{P}/berth-vision/analyze',
                    files={'image': ('pier.png', b'catalog draft', 'image/png')},
                    data={'metadata': json.dumps({'image_kind': 'satellite', 'berth_id': 'NAVSTA-NORFOLK-P12-N'})})
    assert r.status_code == 202, r.text
    job = r.json()
    draft = completed_status(job['status_url'])['result']['result']['draft_berth']
    original_id = draft['berth_id']
    draft['berth_id'] = 'NAVSTA-NORFOLK-P12-N'
    rejected = client.post(f"{P}/berth-vision/{job['job_id']}/confirm", json={'berth': draft})
    assert rejected.status_code == 422
    draft['berth_id'] = original_id
    draft['provenance']['confidence'] = 'published'
    saved = client.post(f"{P}/berth-vision/{job['job_id']}/confirm", json={'berth': draft})
    assert saved.status_code == 201, saved.text
    berth = modeling.get(f"{P}/berths/{original_id}").json()
    assert berth['provenance']['confidence'] == 'estimated'
    assert 'qualification not established' in berth['provenance']['notes']


def test_safety_watch_provider_failure_is_explicit_stream_event(planned, monkeypatch):
    from mooring_agents.api.routers import safety as router
    from mooring_agents.physics.client import ModelingError
    from mooring_agents.safety.schemas import SafetyWatchUnavailable
    async def failed(*args, **kwargs):
        raise ModelingError(503, "provider timeout")
        yield  # async generator contract
    monkeypatch.setattr(router.safety, 'watch', failed)
    response = client.get(f"{P}/safety/watch/{planned}", params={"limit":1})
    assert response.status_code == 200
    assert "event: source_unavailable" in response.text
    payload = json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith('data: ')))
    event = SafetyWatchUnavailable.model_validate(payload)
    assert event.severity == 'RED' and event.retryable
    assert 'gust_kt' not in payload and 'wind_from_true_deg' not in payload


def test_safety_watch_rejects_negative_and_unbounded_zero_interval(planned):
    for params in ({"interval_s":-1}, {"limit":-1}, {"heartbeat_minutes":-1}, {"interval_s":0, "limit":0}):
        assert client.get(f"{P}/safety/watch/{planned}", params=params).status_code == 422


def test_sheet_preserves_holding_assistance_and_visible_result_references(plan_id):
    from dataclasses import replace
    from mooring_agents.planner.agent import PLANS
    from mooring_agents.safety import sheet as renderer
    from mooring_agents.safety.agent import latest_review
    from mooring_agents.planner.schemas import RationaleItem
    # Exercise the document boundary with an assessment record declaring continuous assistance.
    record = replace(PLANS[plan_id], holding_tugs=[{'tug_id':'T4', 'push_point_id':'PP-FWD-P',
        'mode':'push', 'force_lbf':1000}])
    sheet = renderer.build(record, latest_review(plan_id))
    assert sheet.holding_tugs[0].force_lbf == 1000
    assert sheet.analysis_result_id == record.analysis.result_id
    assert sheet.installed_at_water_level_mllw_ft == record.plan.installed_at_water_level_mllw_ft
    assert sheet.sequence_result_id == record.plan.sequence_result_id
    assert sheet.sequence_result_id in sheet.cited_result_ids
    assert set(sheet.threshold_result_ids) <= set(sheet.cited_result_ids)
    rendered = renderer.render_html(sheet)
    assert 'Line-installation water level:' in rendered
    assert 'held fixed across assessed conditions' in rendered
    assert 'Holding assistance' in rendered and 'continuous availability' in rendered
    assert 'Berthing tug plan' in rendered and 'PP-FWD-P' in rendered and '1,000 lbf' in rendered
    assert sheet.analysis_result_id in rendered
    assert sheet.sequence_result_id in rendered and 'Sequence assessment:' in rendered
    assert all(cite in rendered for cite in sheet.cited_result_ids)
    injection = '<img src="https://example.invalid/resource">'
    sheet.rationale = [RationaleItem(text='Document text', cites=[injection])]
    assert injection not in renderer.render_html(sheet)
    assert '&lt;img' in renderer.render_html(sheet)
    sheet.sequence[0].state_ok = False
    sheet.sequence[0].state_note = injection
    rendered = renderer.render_html(sheet)
    assert 'Static check: blocking' in rendered and injection not in rendered
    # Absent legacy data means unknown, never zero assistance.
    old = sheet.model_dump(mode='json')
    for field in ('holding_tugs','analysis_result_id','threshold_result_ids','sequence_result_id','installed_at_water_level_mllw_ft'):
        old.pop(field)
    legacy = SafetySheet.model_validate(old)
    assert legacy.holding_tugs is None and 'not recorded in this archived sheet' in renderer.render_html(legacy)
    assert legacy.installed_at_water_level_mllw_ft is None and 'not recorded in this legacy sheet' in renderer.render_html(legacy)
    assert legacy.sequence_result_id is None and 'sequence_result_id' not in legacy.model_dump()


def test_printed_sheet_preserves_environment_basis_direction_and_forecast_provenance(plan_id):
    from mooring.core.schemas import EnvironmentMetadata, EnvironmentComponentProvenance
    from mooring_agents.planner.agent import PLANS
    from mooring_agents.safety import sheet as renderer
    sheet = renderer.build(PLANS[plan_id])
    env = sheet.environment.observed.model_copy(deep=True)
    env.current_set_true_deg = 217
    env.water_level_mllw_ft = 2.75
    env.metadata = EnvironmentMetadata(basis='prediction', wind_averaging_s=60,
        gust_duration_s=30, wind_reference_height_m=10, components=[
            EnvironmentComponentProvenance(component='water_level', source='<script>source</script>',
                basis='prediction', retrieved_at_utc=datetime.fromisoformat('2026-11-05T08:00:00+02:00'),
                limitations=['Tidal-only <b>unqualified</b>'])])
    sheet.environment.observed = env
    sheet.environment.forecast_summary = 'Coverage incomplete <img src="bad">; use only assessed inputs.'
    text = renderer.render_html(sheet)
    assert 'flowing toward 217° true' in text and '2.75 ft MLLW' in text
    assert 'assessment MST' in text and text.count('<thead>') == 2
    assert 'Wind averaging: 60 s' in text and 'gust duration: 30 s' in text and 'reference height: 10 m' in text
    assert 'issued unknown; retrieved 2026-11-05 06:00Z' in text
    assert 'not a provider issue time or proof of freshness' in text
    assert 'Coverage incomplete &lt;img' in text and '<img src="bad">' not in text
    assert '&lt;script&gt;source&lt;/script&gt;' in text and '<script>source</script>' not in text
    assert 'Tidal-only &lt;b&gt;unqualified&lt;/b&gt;' in text
    env.metadata = None
    assert 'Wind averaging, gust duration and reference height: not recorded' in renderer.render_html(sheet)
