"""Intake core regression and adversarial narration tests; no live LLM calls."""

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from mooring import refdata
from mooring.core.schemas import EnvironmentSnapshot, ForecastSeries
from mooring_agents.intake import agent, core, mock, thresholds
from mooring_agents.intake.schemas import IntakeRequest
from mooring_agents.shared import llm

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


class FakeToolkit:
    caller = "intake"
    plan_id = None

    def __init__(self, calm=False):
        self.requests = []
        self.current = EnvironmentSnapshot(
            valid_at_utc=NOW, source="mock", wind_speed_kt=5 if calm else 64,
            wind_gust_kt=8 if calm else 64, wind_from_true_deg=37,
            current_speed_kt=0.2 if calm else 2, current_set_true_deg=127,
            water_level_mllw_ft=0,
            quality=[dict(station_id="TEST", age_s=1000, flags=["mock"])],
        )
        self.series = [self.current,
                       self.current.model_copy(update={"valid_at_utc": NOW + timedelta(hours=1),
                                                       "wind_speed_kt": 5, "wind_gust_kt": 8,
                                                       "current_speed_kt": 0.2}),
                       self.current.model_copy(update={"valid_at_utc": NOW + timedelta(hours=2),
                                                       "wind_speed_kt": 5 if calm else 20,
                                                       "wind_gust_kt": 8 if calm else 40,
                                                       "wind_from_true_deg": 37 if calm else 127,
                                                       "current_speed_kt": 0.2})]

    async def scenario(self, sid):
        return SimpleNamespace(berth_id="NAVSTA-NORFOLK-P12-N", ship_class_id="DDG-51-FIIA", side_to="starboard")

    async def berth(self, bid):
        # Freeze the geometry/name used to record the pre-extraction golden reports.
        return refdata.berth(bid).model_copy(update={
            "name": "Mock Pier 12 North face (NAVSTA Norfolk)", "face_bearing_true_deg": 105.0,
        })

    async def ship(self, sid):
        return refdata.ship(sid)

    async def env_now(self, bid, env_scenario_id):
        self.requests.append("now")
        return self.current

    async def forecast(self, bid, hours, step):
        self.requests.append("forecast")
        return ForecastSeries(berth_id=bid, step_min=step, series=self.series)

    async def windows(self, body):
        self.requests.append(body)
        return SimpleNamespace(result=SimpleNamespace(windows=[]))


def request(**kwargs):
    return IntakeRequest(scenario_id="scenario_test", horizon_hours=2, **kwargs)


def run(req=None, tk=None):
    return asyncio.run(agent.assess(req or request(), tk or FakeToolkit()))


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append((messages, tools))
        if isinstance(self.payload, Exception):
            raise self.payload
        return llm.Reply(text=self.payload if isinstance(self.payload, str) else json.dumps(self.payload),
                         stop_reason="stop")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("AGENTS_LLM_PROVIDER", "none")
    monkeypatch.setattr(core, "utcnow", lambda: NOW)


def install(monkeypatch, proposal):
    fake = FakeLLM(proposal)
    monkeypatch.setattr(llm, "get_llm", lambda: fake)
    return fake


def proposal(**updates):
    return dict(summary_sentences=[
        "Gusts reach {{/planning_conditions/0/environment/wind_gust_kt}}.",
        "The peak occurs at {{/planning_conditions/0/environment/valid_at_utc}}.",
        "Prepare the mooring plan for MST {{/mst/mst_required}} conditions and verify the stale observations.",
    ], window_priorities=[], data_quality_explanations=[], extra_condition=None) | updates


def _without_additive_nulls(value):
    """Drop keys added after the golden fixture was recorded whose value is null (S00a: EnvironmentSnapshot.metadata)."""
    if isinstance(value, dict):
        return {k: _without_additive_nulls(v) for k, v in value.items() if not (k == "metadata" and v is None)}
    if isinstance(value, list):
        return [_without_additive_nulls(v) for v in value]
    return value


def normalized(report):
    return _without_additive_nulls(report.model_dump(
        mode="json", exclude={"report_id", "created_at_utc", "tool_call_ids", "backend", "summary_source", "narration_note"}))


@pytest.mark.parametrize("name,calm,synthetic", [("forecast", False, False), ("calm", True, False), ("storm", False, True)])
def test_core_matches_pre_extraction_reports(name, calm, synthetic):
    # Fixture generated from the pre-change intake/mock.py at 67dd786, with the same frozen toolkit/clock.
    golden = json.loads(Path(__file__).with_name("intake_core_golden.json").read_text())
    req = request(env_scenario_id="storm" if synthetic else None)
    assert normalized(asyncio.run(core.assess(req, FakeToolkit(calm)))) == golden[name]


def test_storm_and_calm():
    storm = run(request(env_scenario_id="storm"))
    assert storm.mst.mst_required == "II" and not storm.mst.exceeds_ship_mst
    assert any(w.kind == "gust" and w.severity == "RED" for w in storm.windows)
    assert storm.planning_conditions[0].environment.wind_gust_kt == 64
    calm = run(tk=FakeToolkit(calm=True))
    assert not any(w.severity in ("AMBER", "RED") for w in calm.windows)


def test_no_llm_fallback_is_complete_and_uses_shared_store():
    result = run()
    baseline = asyncio.run(core.assess(request(), FakeToolkit()))
    expected = normalized(baseline)
    expected["summary"] = agent._headline(baseline) + " " + baseline.summary
    assert normalized(result) == expected
    assert result.summary_source == "deterministic" and result.narration_note
    assert result.backend == "real" and result.current and result.mst and result.planning_conditions
    assert agent.REPORTS[result.report_id] == result
    assert mock.REPORTS is core.REPORTS is agent.REPORTS


def test_safe_narration_rank_ties_and_forecast_selection(monkeypatch):
    baseline = run()
    n = len(baseline.windows)
    fake = install(monkeypatch, proposal(
        window_priorities=[dict(window_index=n - 1, impact=10), dict(window_index=0, impact=10)],
        data_quality_explanations=[dict(issue_index=0, explanation="Verify this observation before relying on it for mooring.")],
        extra_condition=dict(forecast_index=1, why="Check the forecast interval at {{forecast/1/valid_at_utc}} before berthing."),
    ))
    tk = FakeToolkit()
    result = run(tk=tk)
    assert result.summary.startswith(agent._headline(baseline) + " Gusts reach 64.0 kt.")
    assert result.summary_source == "llm" and result.narration_note is None
    assert len(re.split(r"(?<=[.!?])\s+", result.summary)) == 4
    structured_tokens = set(re.findall(r"\d+(?:\.\d+)?", " ".join(agent._facts(result.model_dump(exclude={"summary"})).values())))
    assert set(re.findall(r"\d+(?:\.\d+)?", result.summary)) <= structured_tokens
    assert [w.model_dump() for w in result.windows] == [baseline.windows[i].model_dump() for i in [0, n-1, *range(1, n-1)]]
    assert result.mst == baseline.mst
    assert result.planning_conditions[:-1] == baseline.planning_conditions
    assert result.planning_conditions[-1].environment == tk.series[1]
    assert "forecast interval" in result.planning_conditions[-1].why
    assert result.data_quality[0].detail.startswith(baseline.data_quality[0].detail)
    assert "Verify" in result.data_quality[0].detail
    assert [(q.station_id, q.issue, q.severity) for q in result.data_quality] == [(q.station_id, q.issue, q.severity) for q in baseline.data_quality]
    assert tk.requests.count("forecast") == 1
    messages, tools = fake.calls[0]
    assert tools is None and messages[0].role == "system"
    context = json.loads(messages[1].content)
    assert context["forecast"] == [s.model_dump(mode="json") for s in tk.series]
    # Numeric output comes from exact structured fields, not model-authored literals.
    assert "64.0" == str(result.planning_conditions[0].environment.wind_gust_kt)
    assert result.planning_conditions[0].environment.valid_at_utc.strftime("%H:%MZ %d %b") in result.summary


@pytest.mark.parametrize("attack", [
    {"windows": []},
    {"windows": [dict(kind="gust", severity="INFO")]},
    {"window_priorities": [dict(window_index=0, impact=1, severity="AMBER")]},
    {"mst": {"mst_required": "I"}},
    {"extra_condition": dict(forecast_index=999, why="A safer interval.")},
    {"extra_condition": dict(forecast_index=1, why="At 99 kt.")},
    {"extra_condition": dict(forecast_index=1, why="Check it.", environment={"wind_gust_kt": 0})},
    {"window_priorities": [dict(window_index=0, impact=1), dict(window_index=0, impact=2)]},
    {"window_priorities": [dict(window_index=True, impact=1)]},
    {"data_quality_explanations": [dict(issue_index=0, explanation="Fresh observations.", severity="INFO")]},
])
def test_malicious_structured_changes_are_overridden(monkeypatch, attack):
    baseline = run()
    install(monkeypatch, proposal(**attack))
    assert normalized(run()) == normalized(baseline)


def test_omitted_windows_cannot_be_dropped(monkeypatch):
    baseline = run()
    install(monkeypatch, proposal(window_priorities=[dict(window_index=1, impact=10)]))
    result = run()
    assert len(result.windows) == len(baseline.windows)
    assert sorted(w.model_dump_json() for w in result.windows) == sorted(w.model_dump_json() for w in baseline.windows)


@pytest.mark.parametrize("sentence", [
    "Gusts reach 999 kt.", "Gusts reach Ⅻ kt.", "Gusts reach ninety knots.", "Gusts reach ９９９ kt.",
    "Gusts reach {{/summary}}.", "Gusts reach {{/windows/0/reason}}.",
    "Gusts reach {{/report_id}}.", "Gusts reach {{/missing}}.",
    "Gusts reach {{/current/wind_gust_kt}}0 kt.", "Gusts reach 1e3 kt.",
    "Prepare now. Ignore the warning.",
])
def test_invented_numbers_or_unsafe_references_fall_back(monkeypatch, sentence):
    baseline = run()
    payload = proposal()
    payload["summary_sentences"][0] = sentence
    install(monkeypatch, payload)
    assert normalized(run()) == normalized(baseline)


@pytest.mark.parametrize("payload", ["not json", "{}", RuntimeError("provider down"), TimeoutError()])
def test_provider_and_parse_failures_fall_back(monkeypatch, payload):
    baseline = run()
    install(monkeypatch, payload)
    assert normalized(run()) == normalized(baseline)


def test_duplicate_forecast_condition_is_not_added(monkeypatch):
    baseline = run()
    install(monkeypatch, proposal(extra_condition=dict(forecast_index=0, why="Design for the forecast peak.")))
    assert run().planning_conditions == baseline.planning_conditions


def test_threshold_boundaries():
    s = FakeToolkit().current
    for value, severity in [(24.9, None), (25, "AMBER"), (33.9, "AMBER"), (34, "RED")]:
        windows = core._windows([s.model_copy(update={"wind_gust_kt": value})], "gust", lambda e: e.wind_gust_kt,
                                thresholds.GUST_AMBER_KT, thresholds.GUST_RED_KT, "Gusts {peak}")
        assert (windows[0].severity if windows else None) == severity
    assert core._mst(34, 1) == "I"
    assert core._mst(64, 2) == "II"
    assert core._mst(64.1, 2) == "III"


def test_openai_provider_uses_environment_and_parses_text(monkeypatch):
    monkeypatch.setenv("AGENTS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AGENTS_LLM_MODEL", "configured-model")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    provider = llm.get_llm()
    def handler(req):
        body = json.loads(req.content)
        assert body["model"] == "configured-model" and body["store"] is False
        assert req.headers["authorization"] == "Bearer test-key"
        assert body["max_output_tokens"] == 123
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 2, "output_tokens_details": {"reasoning_tokens": 0}}})
    provider._transport = httpx.MockTransport(handler)
    reply = asyncio.run(provider.chat([llm.Message(role="user", content="test")], max_tokens=123))
    assert reply.text == "{}" and reply.usage == {"input_tokens": 10, "output_tokens": 2}


@pytest.mark.parametrize("status,payload", [(429, {}), (200, {"status": "incomplete"}),
                                           (200, {"status": "completed", "output": []})])
def test_openai_errors_are_bounded(status, payload):
    provider = llm.OpenAIResponsesLLM("test-model", "test-key", transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload)))
    with pytest.raises(llm.LLMError):
        asyncio.run(provider.chat([llm.Message(role="user", content="test")]))


@pytest.mark.parametrize("provider,model,key", [("none", "", ""), ("openai", "", "key"), ("openai", "model", ""), ("unknown", "model", "key")])
def test_unconfigured_provider_fallback(monkeypatch, provider, model, key):
    monkeypatch.setenv("AGENTS_LLM_PROVIDER", provider)
    monkeypatch.setenv("AGENTS_LLM_MODEL", model)
    monkeypatch.setenv("OPENAI_API_KEY", key)
    result = run()
    baseline = asyncio.run(core.assess(request(), FakeToolkit()))
    assert result.summary == agent._headline(baseline) + " " + baseline.summary
    assert result.summary_source == "deterministic"
    assert result.narration_note == "provider not configured or unavailable"


def test_intake_ledger_still_belongs_to_report(monkeypatch):
    from modeling_api.main import app
    from mooring_agents.physics.client import ModelingClient
    from mooring_agents.physics.toolkit import PhysicsToolkit, calls_for
    install(monkeypatch, proposal())
    client = ModelingClient(base_url="http://modeling/api/v1", transport=httpx.ASGITransport(app=app))
    tk = PhysicsToolkit(client, "intake")
    req = IntakeRequest(berth_id="NAVSTA-NORFOLK-P12-N", ship_class_id="DDG-51-FIIA", side_to="starboard", horizon_hours=2)
    report = run(req, tk)
    calls = calls_for(report.report_id)
    assert calls and {c.tool for c in calls} == {"get_berth", "get_environment", "get_forecast", "get_ship", "berthing_windows"}
    assert report.tool_call_ids == [c.call_id for c in calls]
    assert all(c.caller == "intake" and c.plan_id == report.report_id for c in calls)


@pytest.mark.parametrize("sentence", [
    "Conditions are calm and safe for berthing.", "The gust window is low risk.",
    "Conditions are MST III.", "Conditions are MST: III.", "The windows are GREEN.",
    "The situation is benign.", "Conditions are amber.", "The window is RED.",
    "Conditions meet Mooring Service Type III limits.", "This is a Type II storm mooring.",
    "There is no risk to the moored ship.", "Gusts are of minimal concern.",
    "Conditions are favourable for berthing.", "There is nothing to worry about.",
])
def test_model_cannot_replace_risk_headline(monkeypatch, sentence):
    baseline = run()
    assert baseline.mst.mst_required == "II"
    assert any(w.severity == "RED" for w in baseline.windows)
    data = proposal()
    data["summary_sentences"][0] = sentence
    install(monkeypatch, data)
    result = run()
    assert result.summary == baseline.summary
    assert result.summary.startswith("Highest window severity is RED; MST required is II; it does not exceed the ship's MST II.")
    assert result.summary_source == "deterministic"
    assert result.narration_note == "guardrail: risk language"


def test_risk_headline_covers_calm_exceedance_and_unknown_ship():
    calm = run(tk=FakeToolkit(calm=True))
    assert calm.summary.startswith("No windows of concern; MST required is I; it does not exceed the ship's MST II.")
    tk = FakeToolkit()
    tk.current.wind_speed_kt = 80
    tk.current.wind_gust_kt = 90
    high = run(tk=tk)
    assert high.summary.startswith("Highest window severity is RED; MST required is III; it exceeds the ship's MST II.")
    req = IntakeRequest(berth_id="NAVSTA-NORFOLK-P12-N", horizon_hours=2)
    unknown = run(req)
    assert "ship MST is unknown, so exceedance cannot be assessed." in unknown.summary


@pytest.mark.parametrize("suffix", ["kt", "knots", "m/s", "mph", "deg", "°", "ft"])
@pytest.mark.parametrize("position", ["before", "after"])
def test_units_cannot_be_supplied_by_model(monkeypatch, suffix, position):
    ref = "{{/current/wind_gust_kt}}"
    sentence = f"Gusts reach {ref} {suffix}." if position == "after" else f"Gusts reach {suffix} {ref}."
    data = proposal()
    data["summary_sentences"][0] = sentence
    install(monkeypatch, data)
    result = run()
    assert result.summary_source == "deterministic"
    assert result.narration_note == "guardrail: unit token"
    assert sentence not in result.summary


def test_units_times_and_severity_references_are_code_owned(monkeypatch):
    install(monkeypatch, proposal(summary_sentences=[
        "Gusts reach {{/current/wind_gust_kt}} from {{/current/wind_from_true_deg}}.",
        "Water level is {{/current/water_level_mllw_ft}}.",
        "The {{/windows/0/severity}} window peaks at {{/windows/0/peak_value}} and starts at {{/windows/0/start_utc}}.",
        "Plan for MST {{/mst/mst_required}}.",
    ]))
    result = run()
    assert result.summary_source == "llm" and result.narration_note is None
    assert "64.0 kt from 37.0°" in result.summary
    assert "Water level is 0.0 ft." in result.summary
    assert "RED window peaks at 64.0 kt and starts at 12:00Z 04 Nov." in result.summary
    assert len(re.split(r"(?<=[.!?])\s+", result.summary)) == 5
    assert agent._format_fact("end_utc", datetime(2026, 11, 4, 7, tzinfo=timezone(timedelta(hours=-5)))) == "12:00Z 04 Nov"


@pytest.mark.parametrize("path", [
    "/current/air_density_kgm3", "/current/water_density_kgm3", "/current/quality/0/age_s",
    "/current/quality/0/station_id", "/data_quality/0/severity", "/tool_call_ids/0",
    "/horizon_hours", "/created_at_utc", "/current/valid_at_utc", "/mst/reason",
    "/planning_conditions/0/environment/air_density_kgm3",
])
def test_fact_allowlist_rejects_internal_fields(monkeypatch, path):
    baseline = run()
    assert path not in agent._facts(baseline.model_dump())
    data = proposal()
    data["summary_sentences"][0] = "The observation is {{" + path + "}}."
    install(monkeypatch, data)
    result = run()
    assert result.summary_source == "deterministic"
    assert result.narration_note == "guardrail: fact reference"
    assert result.summary == baseline.summary


def test_extra_forecast_facts_use_same_allowlist(monkeypatch):
    install(monkeypatch, proposal(extra_condition={"forecast_index": 1, "why": "Density is {{forecast/1/air_density_kgm3}}."}))
    result = run()
    assert result.summary_source == "deterministic" and result.narration_note == "guardrail: fact reference"


@pytest.mark.parametrize("payload,note", [
    (TimeoutError(), "provider timeout"), (RuntimeError("secret provider detail"), "provider error"),
    ("not json", "guardrail: invalid proposal"),
])
def test_fallback_provenance_is_explicit_and_sanitized(monkeypatch, payload, note):
    install(monkeypatch, payload)
    result = run()
    assert result.summary_source == "deterministic" and result.narration_note == note
    assert agent.REPORTS[result.report_id].narration_note == note
    assert "secret" not in result.model_dump_json()


@pytest.mark.parametrize("count,expected", [(1, "deterministic"), (2, "llm"), (4, "llm"), (5, "deterministic")])
def test_model_contributes_only_two_to_four_sentences(monkeypatch, count, expected):
    install(monkeypatch, proposal(summary_sentences=["Verify the observations before planning."] * count))
    result = run()
    assert result.summary_source == expected
    if expected == "llm":
        assert len(re.split(r"(?<=[.!?])\s+", result.summary)) == count + 1


def test_provenance_is_additive_for_legacy_reports():
    result = run()
    payload = result.model_dump(mode="json")
    assert type(result).model_validate(payload).summary_source == "deterministic"
    del payload["summary_source"]
    del payload["narration_note"]
    legacy = type(result).model_validate(payload)
    assert legacy.summary_source is None and legacy.narration_note is None


def test_real_narration_deadline_reports_timeout(monkeypatch):
    class SlowLLM:
        async def chat(self, *args, **kwargs):
            await asyncio.sleep(1)
            raise AssertionError("The deadline should cancel the provider first")
    monkeypatch.setattr(llm, "get_llm", lambda: SlowLLM())
    monkeypatch.setattr(agent, "LLM_TIMEOUT_S", 0.001)
    result = run()
    assert result.summary_source == "deterministic" and result.narration_note == "provider timeout"


@pytest.mark.parametrize("tool_call", [False, True])
def test_incomplete_or_tool_response_records_guardrail(monkeypatch, tool_call):
    class UnusableLLM:
        async def chat(self, *args, **kwargs):
            return llm.Reply(text=json.dumps(proposal()), stop_reason="stop" if tool_call else "length",
                             tool_uses=[llm.ToolUse(id="test", name="get_ship", arguments={})] if tool_call else [])
    monkeypatch.setattr(llm, "get_llm", lambda: UnusableLLM())
    result = run()
    assert result.summary_source == "deterministic"
    assert result.narration_note == "guardrail: incomplete response or tool call"


@pytest.mark.parametrize("sentence", [
    "Gusts reach {{/current/wind_gust_kt}} during the window.",
    "The strongest window is rated {{/windows/0/severity}}.",
    "The required service type is {{/mst/mst_required}}.",
    "Expect the strongest gusts when the wind backs toward the pier.",
])
def test_legitimate_narration_still_passes(sentence):
    facts = {"/current/wind_gust_kt": "14.0 kt", "/windows/0/severity": "RED", "/mst/mst_required": "II"}
    assert agent._render(sentence, facts, sentence=True)

