"""Safety/Brief narration and warning-stream guardrail tests."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from mooring.core.schemas import EnvironmentSnapshot, LimitEnvelopePoint
from mooring_agents.safety import agent
from mooring_agents.safety.schemas import CheckResult, DirectionalThreshold, SafetyReview, Thresholds
from mooring_agents.shared import llm

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def chat(self, messages, tools=None, **kwargs):
        return llm.Reply(text=json.dumps(self.payload), stop_reason="stop")


def safety_review(**updates):
    checks = [CheckResult(check_id=check_id, title=f"Check {index}", passed=index != 5,
                          severity="AMBER" if index == 5 else "INFO",
                          detail=f"Check detail {index}.", cites=["result_test"] if index < 6 else [])
              for index, check_id in enumerate((
                  "CITES-RESOLVE", "CITES-IN-LEDGER", "REANALYSIS-NOT-RED", "MARGIN",
                  "NO-RED-FINDINGS", "GUST-THRESHOLD", "TUGS-FEASIBLE", "MST-WITHIN-SHIP"))]
    threshold = Thresholds(wind_rel_deg=90, governing_element="line-2", limit_wll_gust_kt=50,
                           limit_breaking_gust_kt=86.6, forecast_max_gust_kt=42,
                           cites=["result_test"], directions=[DirectionalThreshold(
                               wind_rel_deg=90, governing_element="line-2", limit_wll_gust_kt=50,
                               estimated_breaking_gust_kt=86.6)])
    values = dict(review_id="review_test", plan_id="plan_test", created_at_utc=NOW,
                  verdict="ready_for_signature", status="AMBER", checks=checks, thresholds=threshold,
                  summary="Verdict: ready for signature; 7 of 8 checks passed; limiting gust is 50 kt.",
                  summary_source="deterministic", backend="real")
    return SafetyReview(**(values | updates))


def test_guarded_brief_uses_only_fact_references(monkeypatch):
    proposal = {"sentences": [
        "The governing element is {{/thresholds/governing_element}} at {{/thresholds/limit_wll_gust_kt}}.",
        "Watch the forecast maximum of {{/thresholds/forecast_max_gust_kt}}.",
        "Act if the {{/checks/5/title}} result changes from {{/checks/5/severity}}.",
    ]}
    monkeypatch.setattr(llm, "get_llm", lambda: FakeLLM(proposal))
    result = asyncio.run(agent._narrate(safety_review()))
    assert result.summary_source == "llm" and result.narration_note is None
    assert result.brief == ("The governing element is line-2 at 50.0 kt. Watch the forecast maximum of 42.0 kt. "
                            "Act if the Check 5 result changes from AMBER.")
    assert result.summary.startswith("Verdict: ready for signature;") and result.summary.endswith(result.brief)


def test_guarded_brief_rejects_model_authored_number_and_unit(monkeypatch):
    monkeypatch.setattr(llm, "get_llm", lambda: FakeLLM({"sentences": [
        "The governing element is {{/thresholds/governing_element}}.", "Act at 99 kt."]}))
    baseline = safety_review()
    result = asyncio.run(agent._narrate(baseline))
    assert result.brief is None and result.summary == baseline.summary
    assert result.summary_source == "deterministic" and result.narration_note == "guardrail: numeric literal"


class FakeClient:
    def __init__(self, environments):
        self.environments = iter(environments)
        self.last = environments[-1]

    async def berth(self, berth_id):
        return SimpleNamespace(face_bearing_true_deg=0)

    async def env_now(self, berth_id):
        self.last = next(self.environments, self.last)
        return self.last


def env(direction, gust=40, at=NOW):
    return EnvironmentSnapshot(valid_at_utc=at, source="mock", wind_speed_kt=gust / 1.3,
                               wind_gust_kt=gust, wind_from_true_deg=direction, current_speed_kt=0.1,
                               current_set_true_deg=0, water_level_mllw_ft=0, quality=[])


def collect(iterator):
    async def run():
        return [item async for item in iterator]
    return asyncio.run(run())


def install_watch_state(monkeypatch, review=None):
    review = review or safety_review()
    record = SimpleNamespace(scenario=SimpleNamespace(berth_id="berth", side_to="starboard"), mst="II")
    monkeypatch.setattr(agent, "plan_record", lambda plan_id: record)
    monkeypatch.setattr(agent, "latest_review", lambda plan_id: review)
    agent.ENVELOPES[review.review_id] = [
        LimitEnvelopePoint(wind_rel_deg=0, limit_wind_kt=100, first_failure_element="line-1", failure_mode="WLL"),
        LimitEnvelopePoint(wind_rel_deg=90, limit_wind_kt=80, first_failure_element="line-2", failure_mode="WLL"),
    ]
    return review


def test_watch_suppresses_repeat_then_emits_governing_sector_change(monkeypatch):
    install_watch_state(monkeypatch)
    warnings = collect(agent.watch("plan_test", FakeClient([env(0), env(0), env(90)]),
                                   interval_s=0.001, limit=2, heartbeat_minutes=60))
    assert [warning.element_id for warning in warnings] == ["line-1", "line-2"]
    assert warnings[1].pct_of_wll_limit > warnings[0].pct_of_wll_limit


def test_watch_emits_forecast_ahead_crossing_with_time(monkeypatch):
    review = install_watch_state(monkeypatch, safety_review(intake_report_id="report_test"))
    forecast = env(90, gust=72, at=NOW + timedelta(hours=2))
    monkeypatch.setitem(agent.REPORTS, "report_test", SimpleNamespace(
        planning_conditions=[SimpleNamespace(environment=forecast)]))
    warning = collect(agent.watch("plan_test", FakeClient([env(0)]), interval_s=1, limit=1))[0]
    assert warning.at_utc == forecast.valid_at_utc and warning.pct_of_wll_limit == 90
    assert "Forecast ahead at 14:00Z 04 Nov" in warning.message
