"""A3: canonical HTTP forecast resolution remains bound through planning and review."""

import asyncio
from dataclasses import replace
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from modeling_api.main import app as modeling_app
from mooring import environment
from mooring.core import store
from mooring.core.schemas import EnvScenario
from mooring.core.schemas.forecast_planning import ForecastBinding, ForecastResolveRequest
from mooring.examples import EXAMPLES
from mooring_agents.intake import agent as intake
from mooring_agents.intake.schemas import IntakeRequest
from mooring_agents.physics.client import ModelingClient, ModelingError
from mooring_agents.physics.toolkit import PhysicsToolkit, calls_for
from mooring_agents.planner import agent as planner
from mooring_agents.planner.schemas import AgentPlanRequest
from mooring_agents.planner.schemas import AgentPlan
from mooring_agents.intake.schemas import IntakeReport
from mooring_agents.safety import agent as safety
from mooring_agents.safety.schemas import SafetyReviewRequest


def request():
    path = Path(__file__).resolve().parents[2] / "contract/examples/modeling/mooring_forecast_resolve.json"
    req = ForecastResolveRequest.model_validate(json.loads(path.read_text()))
    req.from_utc = req.as_of_utc
    req.to_utc = req.as_of_utc + timedelta(hours=2)
    req.forecast = req.forecast[:3]
    req.forecast_binding = ForecastBinding(source="supplied", source_id="explicit-training", revision="v1")
    return req


def client():
    return ModelingClient(base_url="http://modeling/api/v1", transport=httpx.ASGITransport(app=modeling_app))


def scenario():
    response = TestClient(modeling_app).post("/api/v1/scenarios", json=EXAMPLES["scenario"])
    assert response.status_code == 201, response.text
    return response.json()["scenario_id"]


def assess(req, sid=None):
    return asyncio.run(intake.assess(IntakeRequest(scenario_id=sid, berth_id=req.berth_id,
        ship_class_id="DDG-51-FIIA", side_to="starboard", horizon_hours=2, forecast_request=req),
        PhysicsToolkit(client(), "intake")))


@pytest.fixture(scope="module")
def chain():
    sid = scenario()
    report = assess(request(), sid)
    record = asyncio.run(planner.run(AgentPlanRequest(scenario_id=sid, intake_report_id=report.report_id,
        max_iterations=1), PhysicsToolkit(client(), "planner")))
    review = asyncio.run(safety.review(SafetyReviewRequest(plan_id=record.plan.plan_id),
        PhysicsToolkit(client(), "safety", operation_id="a3-initial-review")))
    return report, record, review


def test_one_manifest_survives_canonical_http_intake_plan_review_and_persistence(chain):
    report, record, review = chain
    assert report.forecast_manifest == record.plan.forecast_manifest == review.forecast_manifest
    assert len({report.forecast_result_id, record.plan.forecast_result_id, review.forecast_result_id}) == 3
    assert report.forecast_manifest.source_id == "explicit-training"
    restored = planner._load_record(planner.SavedPlan.model_validate_json(planner._save_record(record).model_dump_json()))
    assert restored.plan.forecast_manifest == report.forecast_manifest
    assert restored.plan.forecast_request == report.forecast_request
    for owner, rid in ((report.report_id, report.forecast_result_id),
                       (record.plan.plan_id, record.plan.forecast_result_id),
                       (record.plan.plan_id, review.forecast_result_id)):
        assert any(call.tool == "resolve_forecast" and call.result_id == rid for call in calls_for(owner))


def test_explicit_forecast_never_calls_default_provider_and_is_copied(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Explicit forecast must not read the configured weather provider")
    monkeypatch.setattr(environment, "now", forbidden)
    monkeypatch.setattr(environment, "forecast", forbidden)
    req = request()
    report = assess(req)
    assert report.planning_conditions[-1].label == "Forecast interval start"
    assert report.current == req.forecast[0]
    assert report.berthing_windows == []  # Separate synthetic window service cannot replace this binding.
    before = report.forecast_request.forecast[0].wind_gust_kt
    req.forecast[0].wind_gust_kt += 10
    assert report.forecast_request.forecast[0].wind_gust_kt == before


def test_bound_horizon_and_berth_mismatch_are_not_silently_ignored():
    req = request()
    with pytest.raises(ValidationError, match="horizon_hours"):
        IntakeRequest(horizon_hours=3, forecast_request=req)
    with pytest.raises(ValidationError, match="berth must match"):
        IntakeRequest(berth_id="different", horizon_hours=2, forecast_request=req)
    with pytest.raises(ModelingError, match="berth do not match"):
        assess(req.model_copy(update={"berth_id": "NAVSTA-NORFOLK-P12-S"}), scenario())


@pytest.mark.parametrize("model,fields", [(IntakeRequest, ["forecast_request"]),
    (IntakeReport, ["forecast_request", "forecast_manifest", "forecast_result_id"]),
    (AgentPlan, ["forecast_request", "forecast_manifest", "forecast_result_id"])])
def test_additive_forecast_fields_stay_optional_in_generated_clients(model, fields):
    schema = model.model_json_schema(mode="serialization")
    for field in fields:
        assert field not in schema.get("required", [])
        assert "default" not in schema["properties"][field]


def test_incomplete_forecast_fails_without_current_snapshot_fallback():
    req = request()
    req.forecast = req.forecast[:2]
    with pytest.raises(ModelingError, match="Forecast coverage unavailable") as error:
        assess(req)
    assert error.value.status == 422


@pytest.mark.parametrize("change", ["revision", "content", "binding"])
def test_changed_intake_selection_requires_explicit_reassessment_before_planning(chain, change):
    report, record, _ = chain
    changed = report.model_copy(deep=True)
    changed.report_id += "-" + change
    if change == "revision":
        changed.forecast_request.forecast_binding.revision = "v2"
    elif change == "content":
        changed.forecast_request.forecast[0].wind_gust_kt += 1
    else:
        changed.forecast_request.max_gap_min = 90
    intake.REPORTS[changed.report_id] = changed
    with pytest.raises(ModelingError, match="explicitly reassess") as error:
        asyncio.run(planner.run(AgentPlanRequest(scenario_id=record.scenario.scenario_id,
            intake_report_id=changed.report_id), PhysicsToolkit(client(), "planner")))
    assert error.value.status == 409
    assert planner.PLANS[record.plan.plan_id].plan.forecast_manifest == report.forecast_manifest


def test_new_revision_cannot_be_supplemented_into_old_review(chain):
    report, record, review = chain
    req = request()
    req.forecast_binding.revision = "v2"
    changed = assess(req, record.scenario.scenario_id)
    with pytest.raises(ModelingError, match="without transferring prior approvals") as error:
        asyncio.run(safety.review(SafetyReviewRequest(plan_id=record.plan.plan_id,
            intake_report_id=changed.report_id), PhysicsToolkit(client(), "safety", operation_id="a3-changed-review")))
    assert error.value.status == 409
    assert safety.REVIEWS[review.review_id].forecast_manifest == report.forecast_manifest


def test_explicit_new_intake_and_plan_keep_historical_plan_unchanged(chain):
    report, record, review = chain
    historical = record.plan.model_dump_json()
    req = request()
    req.forecast_binding.revision = "explicit-new-revision"
    updated = assess(req, record.scenario.scenario_id)
    new_record = asyncio.run(planner.run(AgentPlanRequest(scenario_id=record.scenario.scenario_id,
        intake_report_id=updated.report_id, max_iterations=1), PhysicsToolkit(client(), "planner")))
    assert new_record.plan.plan_id != record.plan.plan_id
    assert new_record.plan.forecast_manifest == updated.forecast_manifest != report.forecast_manifest
    assert new_record.plan.safety_sheet_id is None
    assert planner.PLANS[record.plan.plan_id].plan.model_dump_json() == historical
    assert safety.REVIEWS[review.review_id].forecast_manifest == report.forecast_manifest


def test_scenario_revision_change_is_detected_even_with_same_declared_revision():
    req = request()
    selected = EnvScenario(env_scenario_id="a3-training-change", name="A3 explicit training", kind="steady",
        created_at_utc=req.as_of_utc, wind_speed_kt=4, wind_gust_kt=5)
    scenarios = store.DocStore("env_scenario", EnvScenario)
    scenarios[selected.env_scenario_id] = selected
    req.forecast = None
    req.forecast_binding = ForecastBinding(source="scenario", env_scenario_id=selected.env_scenario_id, revision="declared")
    sid = scenario()
    report = assess(req, sid)
    scenarios[selected.env_scenario_id] = selected.model_copy(update={"wind_gust_kt": 7})
    with pytest.raises(ModelingError, match="Forecast binding changed") as error:
        asyncio.run(planner.run(AgentPlanRequest(scenario_id=sid, intake_report_id=report.report_id),
            PhysicsToolkit(client(), "planner")))
    assert error.value.status == 409


def test_bound_watch_uses_forecast_and_refuses_outside_interval(chain, monkeypatch):
    report, record, _ = chain
    selected = client()
    async def forbidden(*args, **kwargs):
        pytest.fail("Bound watch must not substitute saved scenario/default provider")
    monkeypatch.setattr(selected, "scenario_environment", forbidden)
    at = report.forecast_manifest.from_utc + timedelta(minutes=30)
    monkeypatch.setattr(safety, "utcnow", lambda: at)
    async def collect():
        return [item async for item in safety.watch(record.plan.plan_id, selected, interval_s=0, limit=1)]
    warnings = asyncio.run(collect())
    assert warnings[0].gust_kt == report.forecast_request.forecast[0].wind_gust_kt
    assert warnings[0].message.startswith("Bound forecast sample:")
    monkeypatch.setattr(safety, "utcnow", lambda: report.forecast_manifest.to_utc + timedelta(minutes=1))
    with pytest.raises(ModelingError, match="outside the assessed forecast interval"):
        asyncio.run(collect())


def test_changed_binding_is_checked_before_forecast_ahead_warning(chain, monkeypatch):
    _, record, review = chain
    changed = record.plan.model_copy(deep=True)
    changed.forecast_request.forecast_binding.revision = "changed-before-watch"
    monkeypatch.setattr(safety, "plan_record", lambda _: replace(record, plan=changed))
    # Force every forecast condition above the warning threshold: emitting before rechecking would leak stale percentages.
    points = [p.model_copy(update={"limit_gust_kt": 1}) for p in safety.ENVELOPES[review.review_id]]
    monkeypatch.setitem(safety.ENVELOPES, review.review_id, points)
    async def collect():
        return [item async for item in safety.watch(record.plan.plan_id, client(), interval_s=0, limit=1)]
    with pytest.raises(ModelingError, match="Forecast binding changed") as error:
        asyncio.run(collect())
    assert error.value.status == 409


def test_bound_watch_resolver_failure_does_not_fall_back(chain, monkeypatch):
    _, record, _ = chain
    selected = client()
    original = selected.request
    async def fail(method, path, **kwargs):
        if path == "/mooring/forecast/resolve":
            raise ModelingError(503, "assessed source unavailable")
        return await original(method, path, **kwargs)
    async def forbidden(*args, **kwargs):
        pytest.fail("Resolver failure must not substitute another source")
    monkeypatch.setattr(selected, "request", fail)
    monkeypatch.setattr(selected, "scenario_environment", forbidden)
    async def collect():
        return [item async for item in safety.watch(record.plan.plan_id, selected, interval_s=0, limit=1)]
    with pytest.raises(ModelingError, match="assessed source unavailable"):
        asyncio.run(collect())


def test_bound_documents_reopen_with_the_same_manifest_and_source_bytes(chain, monkeypatch, tmp_path):
    report, record, review = chain
    path = str(tmp_path / "forecast-documents.sqlite")
    monkeypatch.setenv("MOORING_DB", path)
    monkeypatch.setenv("AGENTS_PERSIST", "1")
    database = store.Database(path)
    monkeypatch.setattr(store, "_db", database)
    try:
        intake.REPORTS[report.report_id] = report
        planner.PLANS[record.plan.plan_id] = record
        safety.REVIEWS[review.review_id] = review
        database.close()
        database = store.Database(path)
        monkeypatch.setattr(store, "_db", database)
        saved = planner.PLANS[record.plan.plan_id]
        assert saved.toolkit is None
        assert saved.plan.forecast_request == report.forecast_request
        assert saved.plan.forecast_manifest == intake.REPORTS[report.report_id].forecast_manifest
        assert saved.plan.forecast_manifest == safety.REVIEWS[review.review_id].forecast_manifest
        saved.plan.forecast_request.forecast[0].wind_gust_kt += 99
        assert planner.PLANS[record.plan.plan_id].plan.forecast_request == report.forecast_request
    finally:
        database.close()
