"""LLM-guided, code-governed mooring planning loop."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mooring.core.envelopes import new_id
from mooring.core.schemas import AnalyzeResponse, EnvironmentSnapshot, MooringConfig, MooringLine, Scenario

from ..clients import ModelingError
from ..physics.toolkit import PhysicsToolkit, calls_for, ensure_toolkit, summarize, tool_definitions
from ..schemas import (AgentDoneEvent, AgentMessageEvent, AgentPlan, AgentPlanRequest, AgentProposalEvent,
                       AgentStepEvent, RationaleItem)
from ..shared.llm import LLM, LLMNotConfigured, Message, ToolUse, get_llm

PROMPTS = Path(__file__).with_name("prompts")
TEMPERATURE = 0.0
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


PLANS: dict[str, PlanRecord] = {}


def _analyze_body(sc: Scenario, cfg: MooringConfig, env: EnvironmentSnapshot, mst: str, tugs: list | None = None) -> dict:
    return {"scenario_id": sc.scenario_id, "ship_class_id": sc.ship_class_id, "loading": sc.loading,
            "berth_id": sc.berth_id, "config": cfg.model_dump(mode="json", exclude_none=True),
            "environment": env.model_dump(mode="json"), "mst": mst, "tugs": tugs or []}


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


def _model_id(llm: LLM) -> str:
    return str(getattr(llm, "model_id", getattr(llm, "model", "scripted-fake")))


def _safe() -> tuple[LLM | None, str]:
    try:
        configured = get_llm()
        return configured, _model_id(configured)
    except LLMNotConfigured:
        return None, "deterministic-fallback"


async def _choose(llm: LLM, analysis: AnalyzeResponse, cfg: MooringConfig,
                  target: float) -> tuple[ToolUse | None, str]:
    system = (PROMPTS / "system.txt").read_text()
    user = (PROMPTS / "adjust.txt").read_text().format(
        target=target, analysis=summarize(analysis), config=summarize(cfg))
    reply = await llm.chat([Message(role="system", content=system), Message(role="user", content=user)],
                           tools=[*tool_definitions(), *_move_definitions()], temperature=TEMPERATURE)
    if len(reply.tool_uses) != 1:
        return None, "The model did not request exactly one adjustment; its request was refused."
    return reply.tool_uses[0], ""


def _line(cfg: MooringConfig, number: int) -> MooringLine | None:
    return next((line for line in cfg.lines if line.line_number == number), None)


async def _apply_move(call: ToolUse, cfg: MooringConfig, *, tk: PhysicsToolkit, sc: Scenario, env,
                      mst: str, berth, ship, tugs: list) -> tuple[MooringConfig, list, str | None, str | None]:
    """Return config, tugs, result id, refusal reason. All model arguments are validated here."""
    if call.name not in MOVE_NAMES:
        return cfg, tugs, None, f"Disallowed or unknown tool '{call.name}' was refused."
    args = call.arguments
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
            lines = [x.model_copy(update={"spec_id": spec}) if x.line_number == line.line_number else x
                     for x in cfg.lines]
            return cfg.model_copy(update={"lines": lines}), tugs, None, None
        if call.name == "add_breast":
            source = _line(cfg, int(args["from_line_number"]))
            fitting = str(args["pier_fitting_id"])
            if source is None or fitting not in fitting_ids:
                raise ValueError("the source line or usable fitting does not exist")
            added = source.model_copy(update={"line_number": max(x.line_number for x in cfg.lines) + 1,
                                               "role": "breast", "pier_fitting_id": fitting})
            return cfg.model_copy(update={"lines": [*cfg.lines, added]}), tugs, None, None
        result = await tk.hold_tugs(_analyze_body(sc, cfg, env, mst, tugs))
        if not result.result.feasible:
            raise ValueError("the holding-tug plan is infeasible")
        assignments = [x.model_dump(mode="json") for x in result.result.assignments]
        return cfg, assignments, result.result_id, None
    except (KeyError, TypeError, ValueError) as exc:
        return cfg, tugs, None, f"Invalid {call.name} request was refused: {exc}."


async def run(req: AgentPlanRequest, tk: PhysicsToolkit) -> PlanRecord:
    tk = ensure_toolkit(tk)
    plan_id = new_id("plan")
    tk.plan_id = plan_id
    llm, model_id = _safe()
    events: list[tuple[str, dict]] = []
    rationale: list[RationaleItem] = []
    open_questions: list[str] = []
    event_no = 0

    def step(summary: str, tool: str, result_id: str | None = None) -> None:
        nonlocal event_no
        event_no += 1
        events.append(("step", AgentStepEvent(iteration=event_no, thought_summary=summary, tool=tool,
                                               result_id=result_id).model_dump(mode="json")))

    sc = await tk.scenario(req.scenario_id)
    ship = await tk.ship(sc.ship_class_id)
    berth = await tk.berth(sc.berth_id)
    other_conditions: list[Any] = []
    if req.intake_report_id:
        try:
            from ..intake.mock import REPORTS  # type: ignore[import-not-found]
            report = REPORTS.get(req.intake_report_id)
        except ImportError:
            report = None
        if report is None:
            raise ModelingError(404, f"Intake report '{req.intake_report_id}' not found")
        env = report.planning_conditions[0].environment
        other_conditions = list(report.planning_conditions[1:])
        step(f"Selected intake planning condition: {report.planning_conditions[0].label}.", "intake_report")
    else:
        env = await tk.env_now(sc.berth_id)
    step(f"Gathered the design environment ({env.wind_speed_kt:.0f} kt wind).", "get_environment")

    recommendation = await tk.recommend({"ship_class_id": sc.ship_class_id, "loading": sc.loading,
        "berth_id": sc.berth_id, "side_to": sc.side_to,
        "ship_x_ft": sc.config.ship_x_ft if sc.config else None, "design_mst": ship.mst_class,
        "max_candidates": 3})
    if not recommendation.result.candidates:
        raise ModelingError(422, "recommend_config returned no candidates")
    cfg = recommendation.result.candidates[0].config
    step("Seeded the loop with the optimizer's highest-ranked configuration.", "recommend_config",
         recommendation.result_id)
    rationale.append(RationaleItem(text="Started from the optimizer's highest-ranked candidate.",
                                   cites=[recommendation.result_id]))

    analysis: AnalyzeResponse | None = None
    tugs: list = []
    stopped_safely = False
    for iteration in range(req.max_iterations):
        analysis = await tk.analyze(_analyze_body(sc, cfg, env, ship.mst_class, tugs))
        events.append(("proposal", AgentProposalEvent(config=cfg, status=analysis.status).model_dump(mode="json")))
        red = any(f.severity == "RED" for f in analysis.result.findings)
        if analysis.status == "GREEN" and not red and analysis.result.min_margin.pct_wll <= req.target_margin_pct_wll:
            stopped_safely = True
            step("The evaluated plan meets the target and has no RED finding.", "analyze_mooring",
                 analysis.result_id)
            break
        if iteration == req.max_iterations - 1:
            break

        if llm is None:
            top = analysis.result.min_margin
            number = int(top.element_id.removeprefix("line-")) if top.element_id.startswith("line-") else -1
            line = _line(cfg, number)
            if line is None or line.parts == 3:
                open_questions.append(f"No deterministic adjustment can resolve governing element {top.element_id}.")
                break
            call = ToolUse(id=f"fallback-{iteration}", name="double_up",
                           arguments={"line_number": number,
                                      "summary": f"Double up governing line {number}.",
                                      "rationale": f"Line {number} governed the preceding analysis."})
        else:
            call, refusal = await _choose(llm, analysis, cfg, req.target_margin_pct_wll)
            if call is None:
                step(refusal, "llm_refusal", analysis.result_id)
                open_questions.append(refusal)
                break
        cfg2, tugs2, move_rid, refusal = await _apply_move(call, cfg, tk=tk, sc=sc, env=env,
                                                           mst=ship.mst_class, berth=berth, ship=ship, tugs=tugs)
        if refusal:
            step(refusal, "llm_refusal", analysis.result_id)
            open_questions.append(refusal)
            break
        summary = str(call.arguments.get("summary") or f"Applied {call.name}.")
        step(summary, call.name, move_rid or analysis.result_id)
        rationale.append(RationaleItem(text=str(call.arguments.get("rationale") or summary),
                                       cites=[move_rid or analysis.result_id]))
        cfg, tugs = cfg2, tugs2

    if analysis is None:
        raise RuntimeError("planner exhausted without an analysis")

    # Intake reports may contain several credible conditions. They are all checked before completion.
    for condition in other_conditions:
        check = await tk.analyze(_analyze_body(sc, cfg, condition.environment, ship.mst_class, tugs))
        step(f"Checked additional intake condition: {condition.label}.", "analyze_mooring", check.result_id)
        if check.status == "RED" or any(f.severity == "RED" for f in check.result.findings):
            open_questions.append(f"Additional intake condition '{condition.label}' remains RED.")
            analysis = check

    tug_plan = await tk.berthing_tugs({"ship_class_id": sc.ship_class_id, "loading": sc.loading,
        "berth_id": sc.berth_id, "side_to": sc.side_to, "environment": env.model_dump(mode="json")})
    step("Computed the berthing tug plan.", "plan_tugs", tug_plan.result_id)
    sequence = await tk.sequence({"ship_class_id": sc.ship_class_id, "berth_id": sc.berth_id,
        "config": cfg.model_dump(mode="json", exclude_none=True), "environment": env.model_dump(mode="json"),
        "tug_plan_result_id": tug_plan.result_id})
    step("Generated the line-handling sequence.", "generate_sequence", sequence.result_id)
    risk = await tk.exceedance({**_analyze_body(sc, cfg, env, ship.mst_class, tugs), "n_samples": 200, "seed": 1})
    step("Evaluated gust exceedance risk.", "risk_exceedance", risk.result_id)
    rationale.extend([
        RationaleItem(text="The berthing tug recommendation comes from the tug-plan result.", cites=[tug_plan.result_id]),
        RationaleItem(text="The final gust-risk assessment comes from the exceedance result.", cites=[risk.result_id]),
    ])

    red = analysis.status == "RED" or any(f.severity == "RED" for f in analysis.result.findings)
    over_target = analysis.result.min_margin.pct_wll > req.target_margin_pct_wll
    status = "RED" if red else ("AMBER" if over_target or not stopped_safely else "GREEN")
    if status == "GREEN" and risk.result.p_any_exceeds_wll > 0.10:
        status = "AMBER"
    if status != "GREEN" and not open_questions:
        open_questions.append("The iteration budget ended before every element met the utilization target.")
    ledger_ids = {call.result_id for call in calls_for(plan_id) if call.result_id}
    rationale = [item for item in rationale if item.cites and set(item.cites) <= ledger_ids]
    assumptions = [f"LLM provider/model: {'OpenAI/' if llm else ''}{model_id}; temperature {TEMPERATURE}."]
    assumptions.extend(analysis.assumptions[1:2])
    plan = AgentPlan(plan_id=plan_id, scenario_id=sc.scenario_id, intake_report_id=req.intake_report_id,
        state="succeeded", status=status, config=cfg, tug_plan=tug_plan.result, sequence=sequence.result,
        analysis_result_id=analysis.result_id, risk_result_id=risk.result_id, rationale=rationale,
        assumptions=assumptions, open_questions=open_questions)
    events.append(("done", AgentDoneEvent(plan_id=plan_id, status=status).model_dump(mode="json")))
    record = PlanRecord(plan=plan, scenario=sc, env=env, analysis=analysis, mst=ship.mst_class,
                        events=events, toolkit=tk)
    PLANS[plan_id] = record
    return record


async def answer(rec: PlanRecord, text: str, tk: PhysicsToolkit) -> AgentMessageEvent:
    tk = ensure_toolkit(tk)
    tk.plan_id = rec.plan.plan_id
    env = rec.env
    speed_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kt|knots?)", text, re.I)
    direction_match = re.search(r"\b(" + "|".join(sorted(COMPASS, key=len, reverse=True)) + r")\b", text.upper())
    if not speed_match and not direction_match:
        msg = AgentMessageEvent(message_id=new_id("msg"), cites=[],
            text="Ask a what-if with a wind speed or compass direction, for example 'NW 35 kt'.")
    else:
        speed = float(speed_match.group(1)) if speed_match else env.wind_speed_kt
        changed = env.model_copy(update={"wind_speed_kt": speed, "wind_gust_kt": speed * 1.3,
            "wind_from_true_deg": COMPASS[direction_match.group(1)] if direction_match else env.wind_from_true_deg})
        result = await tk.analyze(_analyze_body(rec.scenario, rec.plan.config, changed, rec.mst))
        top = result.result.min_margin
        msg = AgentMessageEvent(message_id=new_id("msg"), cites=[result.result_id],
            text=f"At {speed:.0f} kt from {changed.wind_from_true_deg:03.0f}, the plan is {result.status}; "
                 f"the governing utilization is {top.pct_wll:.0f}% on {top.element_id}.")
    rec.messages.append(("message", msg.model_dump(mode="json")))
    return msg
