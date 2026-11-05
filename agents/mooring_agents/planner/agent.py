"""LLM-guided, code-governed mooring planning loop."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mooring.core import access
from mooring.core.envelopes import new_id
from mooring.core.schemas import AnalyzeResponse, EnvironmentSnapshot, MooringConfig, MooringLine, Scenario

from ..physics.client import ModelingError
from ..physics.toolkit import PhysicsToolkit, calls_for
from .schemas import (AgentDoneEvent, AgentMessageEvent, AgentPlan, AgentPlanRequest, AgentProposalEvent,
                       AgentStepEvent, RationaleItem)
from ..shared.llm import LLM, LLMNotConfigured, Message, ToolUse, get_llm
from ..shared.layout import PlanGeometrySnapshot, capture_geometry
from ..shared.forecast import resolve_forecast

PROMPTS = Path(__file__).with_name("prompts")
TEMPERATURE = 0.0
LLM_TIMEOUT_S = 30.0
SEVERITY = {"INFO": 0, "GREEN": 0, "AMBER": 1, "RED": 2}
COMPASS = {"N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5, "E": 90, "ESE": 112.5, "SE": 135,
           "SSE": 157.5, "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5, "W": 270,
           "WNW": 292.5, "NW": 315, "NNW": 337.5}
MOVE_NAMES = {"double_up", "move_line", "change_line_type", "add_breast", "hold_tugs"}


@dataclass
class PlanRecord:
    plan: AgentPlan
    scenario: Scenario
    env: EnvironmentSnapshot
    analysis: AnalyzeResponse | None
    mst: str = "II"
    events: list[tuple[str, dict]] = field(default_factory=list)
    messages: list[tuple[str, dict]] = field(default_factory=list)
    toolkit: PhysicsToolkit | None = None
    holding_tugs: list = field(default_factory=list)
    geometry_snapshot: PlanGeometrySnapshot | None = None


from pydantic import BaseModel, Field
from ..shared.storage import AgentStore


class SavedPlan(BaseModel):
    """Explicit persistence schema: never serialize the live toolkit/HTTP credentials."""
    plan: AgentPlan
    scenario: Scenario
    env: EnvironmentSnapshot
    analysis: AnalyzeResponse | None
    mst: str = "II"
    events: list[tuple[str, dict]] = Field(default_factory=list)
    messages: list[tuple[str, dict]] = Field(default_factory=list)
    holding_tugs: list = Field(default_factory=list)
    geometry_snapshot: PlanGeometrySnapshot | None = None


def _save_record(rec):
    return SavedPlan(**{name: getattr(rec, name) for name in SavedPlan.model_fields})


def _load_record(saved):
    return PlanRecord(**{name: getattr(saved, name) for name in SavedPlan.model_fields})


PLANS = AgentStore("agent_plan", SavedPlan, encode=_save_record, decode=_load_record)


def _analyze_body(sc: Scenario, cfg: MooringConfig, env: EnvironmentSnapshot, mst: str, tugs: list | None = None,
                  installed_at_water_level_mllw_ft: float | None = None) -> dict:
    return {"scenario_id": sc.scenario_id, "ship_class_id": sc.ship_class_id, "loading": sc.loading,
            "berth_id": sc.berth_id, "config": cfg.model_dump(mode="json", exclude_none=True),
            "environment": env.model_dump(mode="json"), "mst": mst, "tugs": tugs or [],
            "installed_at_water_level_mllw_ft": installed_at_water_level_mllw_ft}


def _move_definitions() -> list[dict[str, Any]]:
    common = {"summary": {"type": "string"}, "rationale": {"type": "string"}}
    def tool(name: str, description: str, extra: dict[str, Any], required: list[str]) -> dict[str, Any]:
        props = {**common, **extra}
        return {"type": "function", "name": name, "description": description,
                "parameters": {"type": "object", "properties": props,
                               "required": ["summary", "rationale", *required], "additionalProperties": False},
                "strict": True}
    return [
        tool("double_up", "Set one governing line to three parts.",
             {"line_number": {"type": "integer"}}, ["line_number"]),
        tool("move_line", "Move one line to a different pier fitting.",
             {"line_number": {"type": "integer"}, "pier_fitting_id": {"type": "string"}},
             ["line_number", "pier_fitting_id"]),
        tool("change_line_type", "Change one line to an available line specification.",
             {"line_number": {"type": "integer"}, "spec_id": {"type": "string"}},
             ["line_number", "spec_id"]),
        tool("add_breast", "Add one breast line by copying the ship end of an existing line.",
             {"from_line_number": {"type": "integer"}, "pier_fitting_id": {"type": "string"}},
             ["from_line_number", "pier_fitting_id"]),
        tool("hold_tugs", "Add holding-tug assignments returned by physics.", {}, []),
    ]


def _as_data(value: Any) -> str:
    """Serialize tool data for the LLM, fenced as data and never as instructions."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return "<physics_data>\n" + json.dumps(value, sort_keys=True, default=str) + "\n</physics_data>"


def _model_id(llm: LLM) -> str:
    return str(getattr(llm, "model_id", getattr(llm, "model", "scripted-fake")))


def _safe() -> tuple[LLM | None, str]:
    try:
        configured = get_llm()
        return configured, _model_id(configured)
    except LLMNotConfigured:
        return None, "deterministic-fallback"


async def _choose(llm: LLM, analysis: AnalyzeResponse, cfg: MooringConfig,
                  target: float, ship, berth) -> tuple[ToolUse | None, str]:
    system = (PROMPTS / "system.txt").read_text()
    user = (PROMPTS / "adjust.txt").read_text().format(
        target=target, analysis=_as_data(analysis), config=_as_data(cfg))
    user += "\nShip inventory and berth fittings:\n" + _as_data(ship) + "\n" + _as_data(berth)
    reply = await asyncio.wait_for(llm.chat(
        [Message(role="system", content=system), Message(role="user", content=user)],
        tools=_move_definitions(), temperature=TEMPERATURE, max_tokens=4096), timeout=LLM_TIMEOUT_S)
    if reply.stop_reason not in ("completed", "stop", "tool_use", "tool_calls"):
        return None, "The provider did not complete its adjustment; the request was refused."
    if len(reply.tool_uses) != 1:
        return None, "The model did not request exactly one adjustment; its request was refused."
    return reply.tool_uses[0], ""


def _line(cfg: MooringConfig, number: int) -> MooringLine | None:
    return next((line for line in cfg.lines if line.line_number == number), None)


async def _apply_move(call: ToolUse, cfg: MooringConfig, *, tk: PhysicsToolkit, sc: Scenario, env,
                      mst: str, berth, ship, tugs: list, installation_tide: float | None = None) -> tuple[MooringConfig, list, str | None, str | None]:
    """Return config, tugs, result id, refusal reason. All model arguments are validated here."""
    if call.name not in MOVE_NAMES:
        return cfg, tugs, None, "Disallowed or unknown adjustment was refused."
    args = call.arguments
    schema = next(d["parameters"] for d in _move_definitions() if d["name"] == call.name)
    if set(args) != set(schema["required"]):
        return cfg, tugs, None, "Invalid adjustment fields were refused."
    for name, spec in schema["properties"].items():
        expected = int if spec["type"] == "integer" else str
        if type(args[name]) is not expected:
            return cfg, tugs, None, "Invalid adjustment argument types were refused."
    fitting_ids = {f.fitting_id for f in berth.fittings if f.condition != "do_not_use"}
    inventory = {item.spec_id for item in ship.standard_line_outfit if item.count > 0}
    try:
        if call.name == "double_up":
            line = _line(cfg, int(args["line_number"]))
            if line is None or line.parts == 3:
                raise ValueError("the requested line is missing or already doubled")
            lines = [x.model_copy(update={"parts": 3}) if x.line_number == line.line_number else x for x in cfg.lines]
            return cfg.model_copy(update={"lines": lines}), tugs, None, None
        if call.name == "move_line":
            line = _line(cfg, int(args["line_number"]))
            fitting = str(args["pier_fitting_id"])
            if line is None or fitting not in fitting_ids:
                raise ValueError("the line or usable fitting does not exist")
            lines = [x.model_copy(update={"pier_fitting_id": fitting}) if x.line_number == line.line_number else x
                     for x in cfg.lines]
            return cfg.model_copy(update={"lines": lines}), tugs, None, None
        if call.name == "change_line_type":
            line = _line(cfg, int(args["line_number"]))
            spec = str(args["spec_id"])
            if line is None or spec not in inventory:
                raise ValueError("the line is missing or line type is not in ship inventory")
            available = sum(item.count for item in ship.standard_line_outfit if item.spec_id == spec)
            if sum(x.spec_id == spec and x.line_number != line.line_number for x in cfg.lines) >= available:
                raise ValueError("the requested line type has no spare inventory")
            lines = [x.model_copy(update={"spec_id": spec}) if x.line_number == line.line_number else x
                     for x in cfg.lines]
            return cfg.model_copy(update={"lines": lines}), tugs, None, None
        if call.name == "add_breast":
            source = _line(cfg, int(args["from_line_number"]))
            fitting = str(args["pier_fitting_id"])
            if source is None or fitting not in fitting_ids:
                raise ValueError("the source line or usable fitting does not exist")
            available = sum(item.count for item in ship.standard_line_outfit if item.spec_id == source.spec_id)
            if sum(x.spec_id == source.spec_id for x in cfg.lines) >= available:
                raise ValueError("no spare line is available")
            added = source.model_copy(update={"line_number": max(x.line_number for x in cfg.lines) + 1,
                                               "role": "breast", "pier_fitting_id": fitting})
            return cfg.model_copy(update={"lines": [*cfg.lines, added]}), tugs, None, None
        result = await tk.hold_tugs(_analyze_body(sc, cfg, env, mst, tugs, installation_tide))
        if not result.result.feasible or result.status == "RED":
            raise ValueError("the holding-tug plan is infeasible")
        # Holding search returns additions to the assistance already in the request.
        assignments = [*tugs, *(x.model_dump(mode="json") for x in result.result.assignments)]
        return cfg, assignments, result.result_id, None
    except (KeyError, TypeError, ValueError) as exc:
        return cfg, tugs, None, f"Invalid {call.name} request was refused: {exc}."


def _analysis_status(analysis: AnalyzeResponse) -> str:
    """An aggregate label cannot hide a component or finding with greater severity."""
    result = analysis.result
    statuses = [analysis.status, *(f.severity for f in result.findings),
                *(f.severity for f in analysis.warnings)]
    for group in (result.lines, result.pier_fittings, result.ship_fittings, result.fenders):
        statuses.extend(item.status for item in group)
    return max(statuses, key=lambda status: SEVERITY[status])


def _score(analysis: AnalyzeResponse) -> tuple[int, float]:
    return SEVERITY[_analysis_status(analysis)], analysis.result.min_margin.pct_wll


async def _conditions(tk, sc, cfg, environments, mst, tugs):
    checks = [await tk.analyze(_analyze_body(sc, cfg, env, mst, tugs, environments[0].water_level_mllw_ft))
              for env in environments]
    return checks, max(range(len(checks)), key=lambda i: _score(checks[i]))


class EventLog(list):
    """Keep the replay record and publish each event when it is computed."""
    def __init__(self, callback=None):
        super().__init__()
        self.callback = callback

    def append(self, event):
        if self.callback:
            self.callback(*event)
        super().append(event)


async def run(req: AgentPlanRequest, tk: PhysicsToolkit, *, plan_id: str | None = None,
              scenario: Scenario | None = None, on_event=None) -> PlanRecord:
    if req.constraints:
        raise ModelingError(422, "Planner constraints are not implemented; refusing to ignore them")
    if req.objective != "moor_for_forecast":
        raise ModelingError(422, "Only moor_for_forecast is currently supported")
    plan_id = plan_id or new_id("plan")
    access.claim("agent_plan", plan_id)
    tk.plan_id = plan_id
    llm, model_id = _safe()
    events: list[tuple[str, dict]] = EventLog(on_event)
    rationale: list[RationaleItem] = []
    open_questions: list[str] = []
    event_no = 0

    def step(summary: str, tool: str, result_id: str | None = None) -> None:
        nonlocal event_no
        event_no += 1
        events.append(("step", AgentStepEvent(iteration=event_no, thought_summary=summary, tool=tool,
                                               result_id=result_id).model_dump(mode="json")))

    sc = scenario or await tk.scenario(req.scenario_id)
    ship = (await tk.ship(sc.ship_class_id)).model_copy(deep=True)
    berth = (await tk.berth(sc.berth_id)).model_copy(deep=True)
    other_conditions: list[Any] = []
    forecast_manifest = forecast_result_id = forecast_request = None
    if req.intake_report_id:
        try:
            from ..intake.agent import REPORTS
            report = REPORTS.get(req.intake_report_id) if access.allowed("agent_report", req.intake_report_id) else None
        except ImportError:
            report = None
        if report is None:
            raise ModelingError(404, f"Intake report '{req.intake_report_id}' not found")
        if (report.berth_id != sc.berth_id or
                report.ship_class_id not in (None, sc.ship_class_id) or
                report.side_to not in (None, sc.side_to)):
            raise ModelingError(422, "Intake report does not match the scenario ship, berth or side")
        if not report.planning_conditions:
            raise ModelingError(422, "Intake report has no planning conditions")
        if getattr(report, "forecast_manifest", None) is not None:
            if report.forecast_request is None:
                raise ModelingError(422, "Bound intake has no saved forecast selection; create a new Intake")
            resolution = await resolve_forecast(tk, report.forecast_request, report.forecast_manifest)
            forecast_manifest = resolution.result.forecast_manifest
            forecast_result_id = resolution.result_id
            forecast_request = report.forecast_request.model_copy(deep=True)
            step("Confirmed the Intake forecast revision, content and temporal binding.", "resolve_forecast", forecast_result_id)
            rationale.append(RationaleItem(text="The plan retains the canonical Intake forecast binding; supplied source identifiers do not provide public latest-revision discovery.", cites=[forecast_result_id]))
        env = report.planning_conditions[0].environment
        other_conditions = list(report.planning_conditions[1:])
        step(f"Selected intake planning condition: {report.planning_conditions[0].label}.", "intake_report")
    else:
        if sc.env_source.mode not in ("live", "scenario", "mock"):
            raise ModelingError(422, "Planner environment source is unsupported")
        if sc.env_source.mode == "scenario" and not sc.env_source.env_scenario_id:
            raise ModelingError(422, "Scenario environment requires env_scenario_id")
        env = await tk.scenario_environment(sc.scenario_id)
    environments = [env, *(condition.environment for condition in other_conditions)]
    installation_tide = environments[0].water_level_mllw_ft
    step(f"Gathered the design environment ({env.wind_speed_kt:.0f} kt wind).", "get_environment")

    recommendation = await tk.recommend({"ship_class_id": sc.ship_class_id, "loading": sc.loading,
        "berth_id": sc.berth_id, "side_to": sc.side_to,
        "ship_x_ft": sc.config.ship_x_ft if sc.config else None, "design_mst": ship.mst_class,
        "max_candidates": 3, "design_basis": "forecast_only",
        "forecast_env": [e.model_dump(mode="json") for e in environments],
        "tide_levels_ft": [environments[0].water_level_mllw_ft],
        "standoff_ft": sc.config.standoff_ft if sc.config else None,
        "tugs": [assignment.model_dump(mode="json") for assignment in sc.tugs]})
    if not recommendation.result.candidates:
        raise ModelingError(422, "recommend_config returned no candidates")
    cfg = recommendation.result.candidates[0].config
    step("Seeded the loop with the optimizer's highest-ranked configuration.", "recommend_config",
         recommendation.result_id)
    rationale.append(RationaleItem(text="Started from the optimizer's highest-ranked candidate.",
                                   cites=[recommendation.result_id]))

    analysis: AnalyzeResponse | None = None
    tugs: list = [assignment.model_dump(mode="json") for assignment in sc.tugs]
    stopped_safely = False
    best = None
    holding_attempted = False
    no_improvement = 0
    llm_requested = llm is not None
    fallback_reason = None
    # Keep the essential finishing calls (tugs, risk for every condition, sequence) inside the Planner's tool budget:
    # each iteration costs one analysis per condition plus a possible holding-tug call.
    n = len(environments)
    finishing_calls = 2 * n + 1
    spent = len(calls_for(plan_id))
    affordable = max(1, (tk.max_calls - spent - finishing_calls) // (n + 1))
    iterations = min(req.max_iterations, affordable)
    if iterations < req.max_iterations:
        budget_note = (f"Iterations capped at {iterations} of {req.max_iterations} to stay within the tool-call budget "
                       f"({tk.max_calls}) with {n} planning condition(s).")
    else:
        budget_note = None
    for iteration in range(iterations):
        try:
            checks, worst_index = await _conditions(tk, sc, cfg, environments, ship.mst_class, tugs)
        except ModelingError as exc:
            if exc.status != 429 or best is None:
                raise
            open_questions.append("Tool-call budget exhausted; returning the best evaluated plan.")
            break
        analysis = checks[worst_index]
        for check in checks:
            step("Evaluated a required planning condition.", "analyze_mooring", check.result_id)
        if best is None or _score(analysis) < _score(best[2]):
            best = (cfg, list(tugs), analysis, worst_index, checks)
            no_improvement = 0
        else:
            no_improvement += 1
        env = environments[worst_index]
        events.append(("proposal", AgentProposalEvent(config=cfg, status=_analysis_status(analysis)).model_dump(mode="json")))
        if (_analysis_status(analysis) != "RED"
                and analysis.result.min_margin.pct_wll <= req.target_margin_pct_wll
                and all(check.validity is None or check.validity.state != "invalid" for check in checks)):
            stopped_safely = True
            step("The evaluated plan meets the target and has no RED finding.", "analyze_mooring",
                 analysis.result_id)
            break
        if iteration == iterations - 1:
            break
        if no_improvement >= 2:
            open_questions.append("Stopped after repeated evaluated adjustments did not improve the governing result; this is not proof of infeasibility.")
            break

        call = None
        if llm is not None:
            try:
                call, refusal = await _choose(llm, analysis, cfg, req.target_margin_pct_wll, ship, berth)
            except Exception:
                # Provider failures cannot discard the evaluated plan or leak provider details.
                llm, fallback_reason = None, "provider unavailable"
                open_questions.append("LLM unavailable; continued with deterministic adjustments.")
            else:
                if call is None:
                    step(refusal, "llm_refusal", analysis.result_id)
                    open_questions.append(refusal)
                    llm, fallback_reason = None, "model response refused"
        if call is not None:
            cfg2, tugs2, move_rid, refusal = await _apply_move(call, cfg, tk=tk, sc=sc, env=env,
                                                               mst=ship.mst_class, berth=berth, ship=ship, tugs=tugs, installation_tide=installation_tide)
            if refusal:
                step(refusal, "llm_refusal", analysis.result_id)
                open_questions.append(refusal)
                llm, fallback_reason, call = None, "model adjustment refused", None
        if call is None:
            # Deterministic adjustment: double up the governing line (also the fallback after LLM problems).
            top = analysis.result.min_margin
            match = re.fullmatch(r"line-(\d+)", top.element_id)
            number = int(match.group(1)) if match else -1
            line = _line(cfg, number)
            if line is None or line.parts == 3:
                if not holding_attempted:
                    holding_attempted = True
                    call = ToolUse(id=f"holding-{iteration}", name="hold_tugs", arguments={})
                    cfg2, tugs2, move_rid, refusal = await _apply_move(call, cfg, tk=tk, sc=sc, env=env,
                        mst=ship.mst_class, berth=berth, ship=ship, tugs=tugs, installation_tide=installation_tide)
                    if not refusal and tugs2 != tugs:
                        step("Proposed holding assistance; every required condition will be re-evaluated.", "hold_tugs", move_rid)
                        cfg, tugs = cfg2, tugs2
                        continue
                    if refusal:
                        open_questions.append(refusal)
                open_questions.append(f"No evaluated deterministic adjustment resolved governing element {top.element_id}; no safe plan was found within this search.")
                break
            call = ToolUse(id=f"fallback-{iteration}", name="double_up",
                           arguments={"line_number": number,
                                      "summary": f"Double up governing line {number}.",
                                      "rationale": f"Line {number} governed the preceding analysis."})
            cfg2, tugs2, move_rid, refusal = await _apply_move(call, cfg, tk=tk, sc=sc, env=env,
                                                               mst=ship.mst_class, berth=berth, ship=ship, tugs=tugs, installation_tide=installation_tide)
            if refusal:
                step(refusal, "deterministic_refusal", analysis.result_id)
                open_questions.append(refusal)
                break
        # Free-form model text is never made factual merely by attaching a result ID.
        summary = f"Proposed {call.name}; the changed configuration requires physics evaluation."
        step(summary, call.name, move_rid or analysis.result_id)
        rationale.append(RationaleItem(text="The preceding physics result prompted a candidate adjustment; final results govern acceptance.",
                                       cites=[move_rid or analysis.result_id]))
        cfg, tugs = cfg2, tugs2

    if analysis is None:
        raise RuntimeError("planner exhausted without an analysis")

    cfg, tugs, analysis, worst_index, checks = best
    if analysis.result.resolved_config is not None:
        cfg = analysis.result.resolved_config
        rationale.append(RationaleItem(
            text="Preserved modeling-resolved unstretched line spans for subsequent rechecks; these are not rope-cutting lengths or handling instructions.",
            cites=[analysis.result_id]))
    env = environments[worst_index]
    for check in checks:
        rationale.append(RationaleItem(text="Checked the final configuration at a required planning condition.",
                                       cites=[check.result_id]))
    # Berthing tugs are sized for every required condition; the most demanding one governs.
    tug_plans = [await tk.berthing_tugs({"ship_class_id": sc.ship_class_id, "loading": sc.loading,
        "berth_id": sc.berth_id, "side_to": sc.side_to, "environment": condition.model_dump(mode="json")})
        for condition in environments]
    tug_index = max(range(len(tug_plans)), key=lambda i: (not tug_plans[i].result.feasible,
                                                          tug_plans[i].result.required_lateral_lbf,
                                                          SEVERITY[tug_plans[i].status]))
    tug_plan = tug_plans[tug_index]
    for result in tug_plans:
        step("Computed the berthing tug plan for a required condition.", "plan_tugs", result.result_id)
    sequence_tug_id = tug_plan.result_id
    invalid_assistance_note = None
    if tug_plan.validity is not None and tug_plan.validity.state == "invalid":
        sequence_tug_id = None
        invalid_assistance_note = "Invalid berthing-tug assessment was not used as assistance in the draft sequence; the plan remains blocked."
        step(invalid_assistance_note, "plan_tugs", tug_plan.result_id)
    sequence = await tk.sequence({"ship_class_id": sc.ship_class_id, "berth_id": sc.berth_id,
        "loading": sc.loading, "mst": ship.mst_class,
        "installed_at_water_level_mllw_ft": installation_tide,
        "config": cfg.model_dump(mode="json", exclude_none=True),
        "environment": environments[tug_index].model_dump(mode="json"),
        "tug_plan_result_id": sequence_tug_id})
    step("Generated the line-handling sequence.", "generate_sequence", sequence.result_id)
    risks = [await tk.exceedance({**_analyze_body(sc, cfg, condition, ship.mst_class, tugs, installation_tide),
                                 "n_samples": 200, "seed": 1}) for condition in environments]
    risk = max(risks, key=lambda r: (SEVERITY[r.status], r.result.p_any_exceeds_wll))
    for result in risks:
        step("Evaluated gust exceedance risk for a required condition.", "risk_exceedance", result.result_id)
        rationale.append(RationaleItem(text="Gust-risk assessment for a required planning condition.",
                                       cites=[result.result_id]))
    rationale.append(RationaleItem(text="Berthing tugs are sized for the most demanding required condition.",
                                   cites=[result.result_id for result in tug_plans]))
    statuses = [_analysis_status(check) for check in checks]
    statuses += [*(t.status for t in tug_plans), sequence.status, *(r.status for r in risks)]
    statuses.extend(f.severity for result in [*tug_plans, sequence, *risks] for f in result.warnings)
    if not tug_plan.result.feasible:
        statuses.append("RED")
        open_questions.append("The berthing tug plan is infeasible.")
    if req.intake_report_id:
        if report.mst.exceeds_ship_mst:
            statuses.append("RED")
            open_questions.append("The intake conditions exceed the ship's MST capability.")
        statuses.extend(issue.severity for issue in report.data_quality)
    status = max(statuses, key=lambda value: SEVERITY[value])
    if status == "INFO":
        status = "GREEN"
    over_target = analysis.result.min_margin.pct_wll > req.target_margin_pct_wll
    if status == "GREEN" and (over_target or not stopped_safely or
                              any(r.result.p_any_exceeds_wll > 0.10 for r in risks)):
        status = "AMBER"
    # (3) A moor that is within limits only while tugs push continuously is not a GREEN moor.
    if tugs and status == "GREEN":
        status = "AMBER"
        open_questions.append("The plan stays within limits only with holding tugs; arrange continuous tug "
                              "support or strengthen the moor before relying on it.")
    if status != "GREEN":
        open_questions.append("The returned plan has unresolved limits, warnings or incomplete validation; inspect cited results.")
    ledger_ids = {call.result_id for call in calls_for(plan_id) if call.result_id}
    rationale = [item for item in rationale if item.cites and set(item.cites) <= ledger_ids]
    mode = ("LLM" if llm else f"LLM, then deterministic after {fallback_reason}") if llm_requested else "deterministic"
    assumptions = [f"Configured model: {model_id}; adjustment mode: {mode}.", *([budget_note] if budget_note else []),
                   "Model text is not used as factual rationale; physics results govern status.",
                   f"Line installation is fixed at the first planning condition water level ({installation_tide:g} ft MLLW); no implicit tending between conditions.",
                   "Forecast-only planning checks the supplied conditions; it does not establish MST design-condition compliance. Intake selects representative snapshots, not every forecast sample; use the forecast-plan endpoint for an arrival/holding interval assessment."]
    assumptions.extend(dict.fromkeys(a for result in [*checks, *tug_plans, sequence, *risks]
                                     for a in result.assumptions))
    if invalid_assistance_note:
        assumptions.append(invalid_assistance_note)
    plan = AgentPlan(plan_id=plan_id, scenario_id=sc.scenario_id, intake_report_id=req.intake_report_id,
        forecast_manifest=forecast_manifest, forecast_result_id=forecast_result_id, forecast_request=forecast_request,
        state="succeeded", status=status, config=cfg, tug_plan=tug_plan.result, sequence=sequence.result,
        sequence_result_id=sequence.result_id,
        analysis_result_id=analysis.result_id, risk_result_id=risk.result_id, rationale=rationale,
        assumptions=assumptions, open_questions=open_questions,
        holding_tugs=tugs, installed_at_water_level_mllw_ft=installation_tide, condition_analysis_result_ids=[check.result_id for check in checks])
    events.append(("done", AgentDoneEvent(plan_id=plan_id, status=status).model_dump(mode="json")))
    record = PlanRecord(plan=plan, scenario=sc, env=env, analysis=analysis, mst=ship.mst_class,
                        events=events, toolkit=tk, holding_tugs=tugs,
                        geometry_snapshot=capture_geometry(ship, berth, analysis, cfg, env))
    PLANS[plan_id] = record
    return record


async def answer(rec: PlanRecord, text: str, tk: PhysicsToolkit) -> AgentMessageEvent:
    tk.plan_id = rec.plan.plan_id
    env = rec.env
    speed_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:kt|knots?)", text, re.I)
    direction_match = re.search(r"\b(" + "|".join(sorted(COMPASS, key=len, reverse=True)) + r")\b", text.upper())
    if not speed_match and not direction_match:
        msg = AgentMessageEvent(message_id=new_id("msg"), cites=[],
            text="Ask a what-if with a wind speed or compass direction, for example 'NW 35 kt'.")
    else:
        speed = float(speed_match.group(1)) if speed_match else env.wind_speed_kt
        if speed < 0:
            raise ModelingError(422, "Wind speed cannot be negative")
        # Preserve gusts for direction-only questions; disclose the existing what-if assumption otherwise.
        gust = speed * 1.3 if speed_match else env.wind_gust_kt
        changed = env.model_copy(update={"wind_speed_kt": speed, "wind_gust_kt": gust,
            "wind_from_true_deg": COMPASS[direction_match.group(1)] if direction_match else env.wind_from_true_deg})
        result = await tk.analyze(_analyze_body(rec.scenario, rec.plan.config, changed, rec.mst, rec.holding_tugs,
            rec.plan.installed_at_water_level_mllw_ft))
        top = result.result.min_margin
        msg = AgentMessageEvent(message_id=new_id("msg"), cites=[result.result_id],
            text=f"At {speed:.0f} kt, gusting {gust:.0f} kt ({'assumed 1.3 times sustained' if speed_match else 'unchanged gust'}), "
                 f"from {changed.wind_from_true_deg:03.0f}, the plan is {_analysis_status(result)}; "
                 f"the governing utilization is {top.pct_wll:.0f}% on {top.element_id}.")
    with PLANS.atomic():
        current = PLANS.get(rec.plan.plan_id, rec)
        current.messages.append(("message", msg.model_dump(mode="json")))
        PLANS[rec.plan.plan_id] = current
    return msg
