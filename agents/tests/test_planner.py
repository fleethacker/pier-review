"""Adversarial planner tests with a scripted LLM and logged, typed physics fixtures."""
import asyncio
import json
from types import SimpleNamespace
from urllib.parse import unquote

import httpx
import pytest

from mooring import refdata
from mooring.core.schemas import (AnalyzeResponse, EnvironmentSnapshot, ExceedanceResponse, MooringConfig,
                                 RecommendResponse, Scenario, SequenceResponse, TugPlanResponse, TugAssignment)
from mooring.examples import EXAMPLES, T0
from mooring_agents.intake.agent import REPORTS
from mooring_agents.physics.client import ModelingError
from mooring_agents.physics.toolkit import PhysicsToolkit, calls_for
from mooring_agents.planner import agent, mock
from mooring_agents.planner.schemas import AgentPlanRequest
from mooring_agents.shared.llm import LLMError, Message, OpenAIResponsesLLM, Reply, ToolUse


def envelope(cls, result, status="GREEN"):
    return cls(result_id=f"test-{cls.__name__}", model="test", model_version="1", backend="mock",
               inputs_hash="fixture", computed_at_utc=T0, status=status, assumptions=["Synthetic physics fixture."],
               result=result)


class PhysicsClient:
    def __init__(self):
        self.sc = Scenario(**EXAMPLES["scenario"], scenario_id="scenario", created_at_utc=T0)
        self.cfg = self.sc.config
        self.env = EnvironmentSnapshot(**EXAMPLES["mooring_analyze"]["environment"])
        self.requests, self.risks, self.env_requests = [], [], []
        self.analyze_fn = lambda body: ("GREEN", 50)
        self.component_status = "GREEN"
        self.extra_red = False
        self.tug_status = self.sequence_status = self.risk_status = "GREEN"
        self.feasible = True
        self.holding = [{"tug_id": "T1", "push_point_id": "PP-FWD-S", "force_lbf": 1000, "mode": "push"}]

    async def request(self, method, path, **kwargs):
        # The toolkit's typed helpers now share its validated generic HTTP path.
        if method == "GET":
            if path.startswith("/scenarios/") and path.endswith("/environment"):
                result = await self.env_now(self.sc.berth_id, env_scenario_id=self.sc.env_source.env_scenario_id)
            elif path == "/env/now":
                params = kwargs["params"]
                result = await self.env_now(params["berth_id"], env_scenario_id=params.get("env_scenario_id"))
            else:
                resource, identifier = path.strip("/").split("/", 1)
                handler = {"scenarios": self.scenario, "ships": self.ship, "berths": self.berth}[resource]
                result = await handler(unquote(identifier))
        else:
            assert method == "POST"
            handler = {"/mooring/analyze": self.analyze, "/tugs/berthing-plan": self.berthing_tugs,
                       "/tugs/hold-plan": self.hold_tugs, "/mooring/sequence": self.sequence}[path]
            result = await handler(kwargs["json"])
        return result.model_dump(mode="json")

    async def job(self, path, body):
        handler = {"/mooring/recommend": self.recommend, "/risk/exceedance": self.exceedance}[path]
        return (await handler(body)).model_dump(mode="json")

    async def scenario(self, _): return self.sc
    async def ship(self, _): return refdata.ship(self.sc.ship_class_id).model_copy(deep=True)
    async def berth(self, _): return refdata.berth(self.sc.berth_id).model_copy(deep=True)
    async def env_now(self, berth, *, env_scenario_id=None):
        self.env_requests.append(env_scenario_id)
        return self.env

    async def recommend(self, body):
        return envelope(RecommendResponse, {"candidates": [{"config": self.cfg, "min_margin_pct_wll": 50,
            "limit_wind_kt_worst": 80, "line_count": len(self.cfg.lines), "analysis_result_id": "seed", "why": []}],
            "design_environment": self.env})

    async def analyze(self, body):
        self.requests.append(body)
        status, pct = self.analyze_fn(body)
        findings = ([{"rule_id": "TEST", "severity": "RED", "message": "Unresolved", "reference": "fixture"}]
                    if self.extra_red else [])
        result = envelope(AnalyzeResponse, {"offset": {"surge_ft": 0, "sway_ft": 0, "yaw_deg": 0},
            "lines": [], "pier_fittings": [], "ship_fittings": [],
            "fenders": [{"fender_id": "F", "reaction_lbf": 0, "compression_ft": 0,
                         "status": self.component_status}],
            "min_margin": {"element_id": "line-1", "pct_wll": pct}, "findings": findings}, status)
        result.result_id = f"analysis-{len(self.requests)}"
        return result

    async def berthing_tugs(self, body):
        return envelope(TugPlanResponse, {"required_lateral_lbf": 0, "required_by_point": [], "assignments": [],
            "total_bollard_pull_lbf": 0, "total_power_hp": 0, "recommended_tug_count": 0,
            "feasible": self.feasible, "rationale": []}, self.tug_status)

    async def hold_tugs(self, body):
        result = await self.berthing_tugs(body)
        result.result.assignments = [TugAssignment.model_validate(tug) for tug in self.holding]
        return TugPlanResponse.model_validate(result.model_dump())

    async def sequence(self, body):
        return envelope(SequenceResponse, {"steps": [], "crews_required": 1}, self.sequence_status)

    async def exceedance(self, body):
        self.risks.append(body)
        result = envelope(ExceedanceResponse, {"n_samples": 200, "p_any_exceeds_wll": 0,
            "p_any_exceeds_mbs": 0, "elements": [], "governing_element": "line-1"}, self.risk_status)
        result.result_id = f"risk-{len(self.risks)}"
        return result


class FakeLLM:
    model_id = "scripted"
    def __init__(self, call=None, error=None): self.call, self.error, self.requests = call, error, []
    async def chat(self, messages, tools=None, **kwargs):
        self.requests.append(tools)
        if self.error: raise self.error
        return Reply(text="", stop_reason="completed", tool_uses=[self.call] if self.call else [])


def move(name="double_up", **args):
    return ToolUse(id="move", name=name, arguments={"summary": "All safe at 999 knots",
        "rationale": "Guaranteed GREEN with zero risk", **args})


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("AGENTS_LLM_PROVIDER", "none")
    client = PhysicsClient()
    tk = PhysicsToolkit(client, "planner")
    return client, tk


def run(tk, **kwargs):
    return asyncio.run(agent.run(AgentPlanRequest(scenario_id="scenario", **kwargs), tk))


def test_fallback_has_complete_plan_and_shared_store(setup):
    client, tk = setup
    rec = run(tk)
    assert rec.plan.status == "GREEN" and len(client.requests) == 1
    assert mock.PLANS is agent.PLANS and mock.PLANS[rec.plan.plan_id] is rec
    assert rec.plan.condition_analysis_result_ids == [rec.analysis.result_id]
    ids = {c.result_id for c in calls_for(rec.plan.plan_id)}
    assert rec.plan.rationale and all(set(r.cites) <= ids for r in rec.plan.rationale)
    assert all(c.request_hash and c.call_id for c in calls_for(rec.plan.plan_id))


def test_model_text_cannot_be_laundered_through_citation(setup, monkeypatch):
    client, tk = setup
    client.analyze_fn = lambda b: ("AMBER", 95) if b["config"]["lines"][0]["parts"] == 1 else ("GREEN", 40)
    llm = FakeLLM(move(line_number=1))
    monkeypatch.setattr(agent, "get_llm", lambda: llm)
    # Opaque IDs may legitimately contain the attack's digits; they are not factual narration.
    monkeypatch.setattr(agent, "new_id", lambda prefix: f"{prefix}_999")
    rec = run(tk)
    assert rec.plan.config.lines[0].parts == 3 and rec.plan.status == "GREEN"
    visible = json.dumps([rec.plan.model_dump(mode="json"), rec.events])
    narrative = json.dumps([[r.text for r in rec.plan.rationale],
                            rec.plan.assumptions, rec.plan.open_questions,
                            [payload.get("thought_summary", payload.get("text", "")) for _, payload in rec.events]])
    assert "999" not in narrative and "Guaranteed" not in visible
    assert llm.call.arguments["summary"] not in visible
    assert rec.plan.plan_id == "plan_999"
    assert {t["name"] for t in llm.requests[0]} == agent.MOVE_NAMES
    assert len(client.requests) == 2


@pytest.mark.parametrize("attribute,value", [("extra_red", True), ("component_status", "RED"),
    ("component_status", "AMBER"), ("tug_status", "RED"), ("sequence_status", "RED"),
    ("risk_status", "RED"), ("feasible", False)])
def test_no_green_when_a_component_or_tool_fails(setup, attribute, value):
    client, tk = setup
    setattr(client, attribute, value)
    rec = run(tk, max_iterations=1)
    assert rec.plan.status == ("AMBER" if value == "AMBER" else "RED")
    assert rec.plan.open_questions


def report_for(client, second=True):
    conditions = [SimpleNamespace(label="first", environment=client.env)]
    if second:
        conditions.append(SimpleNamespace(label="second", environment=client.env.model_copy(update={"wind_gust_kt": 99})))
    return SimpleNamespace(berth_id=client.sc.berth_id, ship_class_id=client.sc.ship_class_id,
        side_to=client.sc.side_to, planning_conditions=conditions, mst=SimpleNamespace(exceeds_ship_mst=False), data_quality=[])


@pytest.mark.parametrize("second_status,pct", [("AMBER", 60), ("RED", 120), ("GREEN", 95)])
def test_every_intake_condition_is_evaluated_and_risk_checked(setup, monkeypatch, second_status, pct):
    client, tk = setup
    monkeypatch.setitem(REPORTS, "intake", report_for(client))
    client.analyze_fn = lambda b: (second_status, pct) if b["environment"]["wind_gust_kt"] == 99 else ("GREEN", 30)
    rec = run(tk, intake_report_id="intake", max_iterations=1)
    assert rec.plan.status != "GREEN"
    assert len(client.requests) == len(client.risks) == 2
    assert rec.env.wind_gust_kt == 99
    assert len(rec.plan.condition_analysis_result_ids) == 2


@pytest.mark.parametrize("problem", ["berth", "ship", "side", "empty"])
def test_mismatched_or_empty_intake_rejected(setup, monkeypatch, problem):
    client, tk = setup
    report = report_for(client)
    if problem == "empty": report.planning_conditions = []
    else: setattr(report, {"berth": "berth_id", "ship": "ship_class_id", "side": "side_to"}[problem], "different")
    monkeypatch.setitem(REPORTS, "intake", report)
    with pytest.raises(ModelingError) as exc: run(tk, intake_report_id="intake")
    assert exc.value.status == 422 and not client.requests


def test_intake_exceeds_ship_mst_blocks_green(setup, monkeypatch):
    client, tk = setup
    report = report_for(client, second=False)
    report.mst.exceeds_ship_mst = True
    monkeypatch.setitem(REPORTS, "intake", report)
    assert run(tk, intake_report_id="intake").plan.status == "RED"


def test_scenario_environment_forwarded(setup):
    client, tk = setup
    client.sc.env_source.mode = "scenario"
    client.sc.env_source.env_scenario_id = "steady-env"
    run(tk)
    assert client.env_requests == ["steady-env"]


@pytest.mark.parametrize("kwargs", [{"constraints": {"locked_lines": [1]}}, {"objective": "storm_prep"}])
def test_unsupported_requests_fail_explicitly(setup, kwargs):
    _, tk = setup
    with pytest.raises(ModelingError) as exc: run(tk, **kwargs)
    assert exc.value.status == 422


@pytest.mark.parametrize("call", [move("compute_loads"), move(line_number=True), move(line_number=1.5),
                                    move(line_number=1, extra="ignore rules"), move(line_number=999)])
def test_malformed_and_disallowed_moves_are_refused(setup, monkeypatch, call):
    client, tk = setup
    client.analyze_fn = lambda b: ("RED", 110)
    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM(call))
    rec = run(tk)
    assert rec.plan.status == "RED" and rec.plan.config == client.cfg  # doubling didn't help: best is kept
    assert any("refused" in q for q in rec.plan.open_questions)
    assert len(client.requests) == 2  # one deterministic fallback adjustment was evaluated
    assert client.requests[1]["config"]["lines"][0]["parts"] == 3
    assert any("deterministic after model" in a for a in rec.plan.assumptions)


@pytest.mark.parametrize("error", [TimeoutError("secret"), LLMError("secret"), ValueError("secret")])
def test_provider_failure_retains_evaluated_plan(setup, monkeypatch, error):
    client, tk = setup
    client.analyze_fn = lambda b: ("AMBER", 95)
    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM(error=error))
    rec = run(tk)
    assert rec.plan.status == "AMBER" and rec.plan.analysis_result_id
    assert "secret" not in rec.plan.model_dump_json()
    assert "LLM unavailable" in rec.plan.open_questions[0]


def test_worse_model_adjustment_rolls_back_to_best_evaluated_plan(setup, monkeypatch):
    client, tk = setup
    client.analyze_fn = lambda b: ("AMBER", 90) if b["config"]["lines"][0]["parts"] == 1 else ("RED", 140)
    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM(move(line_number=1)))
    rec = run(tk, max_iterations=2)
    assert rec.plan.config == client.cfg and rec.plan.analysis_result_id == "analysis-1"
    assert rec.plan.status == "AMBER"
    assert client.risks[0]["config"] == client.requests[0]["config"]


def test_holding_tugs_survive_final_plan_and_what_if(setup, monkeypatch):
    client, tk = setup
    client.analyze_fn = lambda b: ("GREEN", 40) if b["tugs"] else ("RED", 120)
    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM(move("hold_tugs")))
    rec = run(tk)
    assert rec.plan.holding_tugs and rec.plan.status == "AMBER"  # relies on continuous tug support
    assert any("holding tugs" in q for q in rec.plan.open_questions)
    asyncio.run(agent.answer(rec, "NW", tk))
    assert client.requests[-1]["tugs"] == rec.holding_tugs
    assert client.requests[-1]["environment"]["wind_gust_kt"] == client.env.wind_gust_kt
    assert client.requests[-1]["environment"]["wind_from_true_deg"] == 315
    assert any(c.tool == "hold_tugs" for c in calls_for(rec.plan.plan_id))


def test_responses_provider_tool_call_and_error_paths():
    call = {"type": "function_call", "call_id": "c", "name": "double_up", "arguments": '{"line_number": 1}'}
    def handler(request):
        body = json.loads(request.content)
        assert body["parallel_tool_calls"] is False and "temperature" not in body
        assert body["tools"] == agent._move_definitions() and body["max_output_tokens"] == 4096
        return httpx.Response(200, json={"status": "completed", "output": [call]})
    provider = OpenAIResponsesLLM("configured", "fake-key", transport=httpx.MockTransport(handler))
    reply = asyncio.run(provider.chat([Message(role="user", content="choose")],
                                      tools=agent._move_definitions(), max_tokens=4096))
    assert reply.tool_uses[0].arguments == {"line_number": 1}
    for args in ('{broken', '[]'):
        call["arguments"] = args
        with pytest.raises(LLMError):
            asyncio.run(provider.chat([Message(role="user", content="choose")],
                                      tools=agent._move_definitions(), max_tokens=4096))


def test_provider_deadline_preserves_result(setup, monkeypatch):
    client, tk = setup
    client.analyze_fn = lambda b: ("AMBER", 90)
    class HangingLLM:
        async def chat(self, *args, **kwargs):
            await asyncio.Event().wait()
    monkeypatch.setattr(agent, "get_llm", lambda: HangingLLM())
    monkeypatch.setattr(agent, "LLM_TIMEOUT_S", 0.01)
    rec = run(tk)
    assert rec.plan.status == "AMBER" and rec.plan.analysis_result_id


def test_missing_scenario_environment_never_falls_back_to_live(setup):
    client, tk = setup
    client.sc.env_source.mode = "scenario"
    with pytest.raises(ModelingError) as exc: run(tk)
    # S00a made a scenario-mode environment without an ID invalid in the schema, so the Physics gateway rejects the
    # malformed modeling response (502) before the planner's own 422 check runs. Either way: never the live feed.
    assert exc.value.status == 502 and "get_scenario" in exc.value.detail and client.env_requests == []


def test_last_iteration_does_not_apply_unevaluated_move(setup, monkeypatch):
    client, tk = setup
    client.analyze_fn = lambda b: ("RED", 120)
    llm = FakeLLM(move(line_number=1))
    monkeypatch.setattr(agent, "get_llm", lambda: llm)
    rec = run(tk, max_iterations=1)
    assert not llm.requests and rec.plan.config == client.cfg
    assert rec.plan.analysis_result_id == "analysis-1"


def test_move_cannot_exceed_available_inventory(setup, monkeypatch):
    client, tk = setup
    client.analyze_fn = lambda b: ("AMBER", 95)
    source = client.cfg.lines[0]
    async def depleted_ship(_):
        ship = refdata.ship(client.sc.ship_class_id).model_copy(deep=True)
        for item in ship.standard_line_outfit:
            item.count = sum(line.spec_id == item.spec_id for line in client.cfg.lines)
        return ship
    client.ship = depleted_ship
    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM(move("add_breast", from_line_number=source.line_number,
                                                               pier_fitting_id=source.pier_fitting_id)))
    rec = run(tk)
    assert rec.plan.config == client.cfg
    assert any("no spare line" in q for q in rec.plan.open_questions)


# ---- Review fixes: fallback continues, tugs sized per condition, GREEN reachable with intake ----

@pytest.mark.parametrize("error", [TimeoutError("secret"), LLMError("secret")])
def test_provider_failure_continues_with_deterministic_adjustments(setup, monkeypatch, error):
    client, tk = setup
    client.analyze_fn = lambda b: ("AMBER", 95) if b["config"]["lines"][0]["parts"] == 1 else ("GREEN", 40)
    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM(error=error))
    rec = run(tk)
    assert rec.plan.status == "GREEN" and rec.plan.config.lines[0].parts == 3
    assert "LLM unavailable" in rec.plan.open_questions[0]
    assert any("deterministic after provider unavailable" in a for a in rec.plan.assumptions)
    assert "secret" not in rec.plan.model_dump_json()


def test_refused_model_move_falls_back_and_can_still_resolve(setup, monkeypatch):
    client, tk = setup
    client.analyze_fn = lambda b: ("AMBER", 95) if b["config"]["lines"][0]["parts"] == 1 else ("GREEN", 40)
    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM(move("compute_loads")))
    rec = run(tk)
    assert rec.plan.status == "GREEN" and rec.plan.config.lines[0].parts == 3
    assert any("refused" in q for q in rec.plan.open_questions)


def test_intake_plan_with_all_conditions_green_can_be_green(setup, monkeypatch):
    client, tk = setup
    monkeypatch.setitem(REPORTS, "intake", report_for(client))
    client.analyze_fn = lambda b: ("GREEN", 40)
    rec = run(tk, intake_report_id="intake")
    assert rec.plan.status == "GREEN"
    assert len(rec.plan.condition_analysis_result_ids) == 2


def test_berthing_tugs_sized_for_most_demanding_condition(setup, monkeypatch):
    client, tk = setup
    monkeypatch.setitem(REPORTS, "intake", report_for(client))
    seen = []

    async def berthing_tugs(body):
        gust = body["environment"]["wind_gust_kt"]
        seen.append(gust)
        result = envelope(TugPlanResponse, {"required_lateral_lbf": gust * 1000, "required_by_point": [],
            "assignments": [], "total_bollard_pull_lbf": gust * 1500, "total_power_hp": gust * 100,
            "recommended_tug_count": 2, "feasible": True, "rationale": []})
        result.result_id = f"tugs-{gust:g}"
        return result

    client.berthing_tugs = berthing_tugs
    rec = run(tk, intake_report_id="intake")
    assert sorted(seen) == sorted([client.env.wind_gust_kt, 99])
    assert rec.plan.tug_plan.required_lateral_lbf == 99_000
    tug_cites = {c for item in rec.plan.rationale for c in item.cites if c.startswith("tugs-")}
    assert tug_cites == {"tugs-99", f"tugs-{client.env.wind_gust_kt:g}"}


def test_infeasible_tug_plan_for_any_condition_blocks_green(setup, monkeypatch):
    client, tk = setup
    monkeypatch.setitem(REPORTS, "intake", report_for(client))
    original = client.berthing_tugs

    async def berthing_tugs(body):
        result = await original(body)
        if body["environment"]["wind_gust_kt"] == 99:
            result.result.feasible = False
        return result

    client.berthing_tugs = berthing_tugs
    rec = run(tk, intake_report_id="intake")
    assert rec.plan.status == "RED" and not rec.plan.tug_plan.feasible



# ---- Review fixes (PR #14 integration): the planner stays within its tool budget ----

def test_planner_caps_iterations_to_fit_the_tool_budget(setup, monkeypatch):
    monkeypatch.setenv("AGENTS_MAX_TOOL_CALLS", "12")
    client = PhysicsClient()
    tk = PhysicsToolkit(client, "planner")
    monkeypatch.setitem(REPORTS, "intake", report_for(client))
    client.analyze_fn = lambda b: ("AMBER", 95)  # never converges: would iterate to max_iterations
    rec = run(tk, intake_report_id="intake", max_iterations=20)
    assert rec.plan.state == "succeeded" and rec.plan.tug_plan is not None and rec.plan.sequence is not None
    assert any("Iterations capped" in a for a in rec.plan.assumptions)
    assert len(calls_for(rec.plan.plan_id)) <= 12


def test_max_iterations_with_default_budget_completes(setup, monkeypatch):
    client, tk = setup
    monkeypatch.setitem(REPORTS, "intake", report_for(client))
    client.analyze_fn = lambda b: ("AMBER", 95)
    rec = run(tk, intake_report_id="intake", max_iterations=20)
    assert rec.plan.state == "succeeded" and len(calls_for(rec.plan.plan_id)) <= 40


def test_sequence_receives_same_loading_and_mst_as_the_plan(setup, monkeypatch):
    client, tk = setup
    client.sc.loading = 'light'
    seen = []
    original = client.sequence
    async def ship(_):
        value = refdata.ship(client.sc.ship_class_id).model_copy(deep=True)
        value.mst_class = 'IIA'
        return value
    async def sequence(body):
        seen.append(body)
        return await original(body)
    monkeypatch.setattr(client, 'ship', ship)
    monkeypatch.setattr(client, 'sequence', sequence)
    run(tk)
    assert len(seen) == 1 and seen[0]['loading'] == 'light' and seen[0]['mst'] == 'IIA'


@pytest.mark.parametrize('component', ['analysis', 'tugs'])
def test_invalid_component_remains_blocking_in_complete_plan(setup, monkeypatch, component):
    from mooring.core.schemas import Validity
    client, tk = setup
    original = client.analyze if component == 'analysis' else client.berthing_tugs
    async def invalid(body):
        response = await original(body)
        response.validity = Validity(state='invalid', reasons=[{'code': 'TEST_INVALID', 'message': 'Invalid synthetic fixture'}])
        response.status = 'RED'
        return response
    monkeypatch.setattr(client, 'analyze' if component == 'analysis' else 'berthing_tugs', invalid)
    seen = []
    original_sequence = client.sequence
    async def sequence(body):
        seen.append(body)
        return await original_sequence(body)
    monkeypatch.setattr(client, 'sequence', sequence)
    rec = run(tk, max_iterations=1)
    assert rec.plan.state == 'succeeded' and rec.plan.status == 'RED'
    if component == 'tugs':
        assert seen[0]['tug_plan_result_id'] is None
        assert any('Invalid berthing-tug assessment' in value for value in rec.plan.assumptions)


def test_tide_changes_keep_one_installation_through_plan_risk_and_what_if(setup, monkeypatch):
    client, tk = setup
    report = report_for(client)
    report.planning_conditions[0].environment = client.env.model_copy(update={"water_level_mllw_ft": -1.25})
    report.planning_conditions[1].environment = client.env.model_copy(update={"water_level_mllw_ft": 3.5})
    monkeypatch.setitem(REPORTS, "changing-tide", report)
    # Make the later tide govern, so rec.env cannot be mistaken for installation.
    client.analyze_fn = lambda b: ("AMBER", 70 if b["environment"]["water_level_mllw_ft"] == 3.5 else 30)
    sequences = []
    original = client.sequence
    async def sequence(body):
        sequences.append(body)
        return await original(body)
    monkeypatch.setattr(client, "sequence", sequence)
    rec = run(tk, intake_report_id="changing-tide", max_iterations=1)
    assert rec.env.water_level_mllw_ft == 3.5
    assert rec.plan.installed_at_water_level_mllw_ft == -1.25
    assert {b["environment"]["water_level_mllw_ft"] for b in client.requests} == {-1.25, 3.5}
    assert all(b["installed_at_water_level_mllw_ft"] == -1.25 for b in [*client.requests, *client.risks, *sequences])
    restored = agent._load_record(agent.SavedPlan.model_validate_json(agent._save_record(rec).model_dump_json()))
    assert restored.plan.installed_at_water_level_mllw_ft == -1.25
    asyncio.run(agent.answer(restored, "NW 15 kt", tk))
    assert client.requests[-1]["installed_at_water_level_mllw_ft"] == -1.25
    assert client.requests[-1]["environment"]["water_level_mllw_ft"] == 3.5


def test_holding_search_adds_to_existing_assistance_instead_of_replacing_it(setup, monkeypatch):
    client, tk = setup
    existing = {"tug_id": "T4", "push_point_id": "PP-AFT-P", "force_lbf": 5000, "mode": "push"}
    client.sc.tugs = [TugAssignment.model_validate(existing)]
    client.analyze_fn = lambda b: ("GREEN", 40) if len(b["tugs"]) == 2 else ("RED", 120)
    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM(move("hold_tugs")))
    rec = run(tk)
    assert {a.tug_id for a in rec.plan.holding_tugs} == {"T1", "T4"}
    assert len(rec.holding_tugs) == 2
    assert all({a["tug_id"] for a in b["tugs"]} == {"T1", "T4"} for b in client.risks)


def test_planner_preserves_model_resolved_spans_for_sequence_risk_and_saved_plan(setup, monkeypatch):
    client, tk = setup
    original = client.analyze
    resolved = client.cfg.model_copy(deep=True)
    for index, line in enumerate(resolved.lines):
        line.paid_out_unstretched_length_ft = 100.125+index  # Fixture output, never computed by the agent.
        line.pretension_lbf = line.slack_ft = None
        line.condition = 'wet'
    async def analyze_with_resolved(body):
        response = await original(body)
        response.result.resolved_config = resolved.model_copy(deep=True)
        return response
    monkeypatch.setattr(client, 'analyze', analyze_with_resolved)
    sequences = []
    original_sequence = client.sequence
    async def sequence(body):
        sequences.append(body)
        return await original_sequence(body)
    monkeypatch.setattr(client, 'sequence', sequence)
    rec = run(tk)
    assert rec.plan.config.model_dump() == resolved.model_dump()
    for body in [*client.risks, *sequences]:
        assert MooringConfig.model_validate(body['config']).model_dump() == resolved.model_dump()
    restored = agent._load_record(agent.SavedPlan.model_validate_json(agent._save_record(rec).model_dump_json()))
    assert restored.plan.config.model_dump() == resolved.model_dump()
    assert any('modeling-resolved' in item.text and item.cites == [rec.plan.analysis_result_id]
               for item in rec.plan.rationale)
