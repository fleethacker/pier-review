"""Mock planning agent (M9): a deterministic plan -> evaluate -> adjust loop over modeling tools.

No LLM yet. It calls the same modeling endpoints the real agent will (see tools.py), emits the same SSE events and
cites every number by result_id. Workstream D replaces the loop body with an LLM tool-use loop.
"""

import re
from dataclasses import dataclass, field

from mooring.core.envelopes import new_id
from mooring.core.schemas import AnalyzeResponse, EnvironmentSnapshot, MooringConfig, Scenario

from ..clients import ModelingClient
from ..schemas import (
    AgentDoneEvent,
    AgentMessageEvent,
    AgentPlan,
    AgentPlanRequest,
    AgentProposalEvent,
    AgentStepEvent,
    RationaleItem,
)


@dataclass
class PlanRecord:
    plan: AgentPlan
    scenario: Scenario
    env: EnvironmentSnapshot
    analysis: AnalyzeResponse | None
    mst: str = "II"
    events: list[tuple[str, dict]] = field(default_factory=list)
    messages: list[tuple[str, dict]] = field(default_factory=list)


PLANS: dict[str, PlanRecord] = {}

COMPASS = {"N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5, "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5, "S": 180,
           "SSW": 202.5, "SW": 225, "WSW": 247.5, "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5}


def _analyze_body(sc: Scenario, cfg: MooringConfig, env: EnvironmentSnapshot, mst: str) -> dict:
    return {"scenario_id": sc.scenario_id, "ship_class_id": sc.ship_class_id, "loading": sc.loading,
            "berth_id": sc.berth_id, "config": cfg.model_dump(mode="json", exclude_none=True),
            "environment": env.model_dump(mode="json"), "mst": mst}


async def run(req: AgentPlanRequest, client: ModelingClient) -> PlanRecord:
    sc = await client.scenario(req.scenario_id)
    ship = await client.ship(sc.ship_class_id)
    mst = ship.mst_class
    events: list[tuple[str, dict]] = []
    rationale: list[RationaleItem] = []
    it = 0

    def step(summary: str, tool: str, result_id: str | None) -> None:
        nonlocal it
        it += 1
        events.append(("step", AgentStepEvent(iteration=it, thought_summary=summary, tool=tool,
                                              result_id=result_id).model_dump(mode="json")))

    env = await client.env_now(sc.berth_id)
    step(f"Wind {env.wind_speed_kt:.0f} kt gusting {env.wind_gust_kt:.0f} kt from {env.wind_from_true_deg:03.0f}, "
         f"current {env.current_speed_kt:.1f} kt.", "get_environment", None)

    rec = await client.recommend({"ship_class_id": sc.ship_class_id, "loading": sc.loading, "berth_id": sc.berth_id,
                                  "side_to": sc.side_to, "ship_x_ft": sc.config.ship_x_ft if sc.config else None,
                                  "design_mst": mst, "max_candidates": 3})
    cands = rec.result.candidates
    step(f"{len(cands)} candidate plans; best holds MST {mst} design load at "
         f"{cands[0].min_margin_pct_wll:.0f}% of WLL.", "recommend_config", rec.result_id)
    rationale.append(RationaleItem(text=f"Started from the optimizer's best candidate ({cands[0].why[0]}).",
                                   cites=[rec.result_id, cands[0].analysis_result_id]))

    cfg = cands[0].config
    analysis = None
    for _ in range(req.max_iterations):
        analysis = await client.analyze(_analyze_body(sc, cfg, env, mst))
        top = analysis.result.min_margin
        events.append(("proposal", AgentProposalEvent(config=cfg, status=analysis.status).model_dump(mode="json")))
        if top.pct_wll <= req.target_margin_pct_wll and analysis.status != "RED":
            step(f"Plan holds: highest utilization {top.pct_wll:.0f}% ({top.element_id}).", "analyze_mooring",
                 analysis.result_id)
            break
        if not top.element_id.startswith("line-"):
            step(f"{top.element_id} governs at {top.pct_wll:.0f}%; cannot fix by doubling lines.", "analyze_mooring",
                 analysis.result_id)
            break
        n = int(top.element_id.split("-")[1])
        line = next(ln for ln in cfg.lines if ln.line_number == n)
        if line.parts == 3:
            step(f"Line {n} already doubled up and still at {top.pct_wll:.0f}%; stopping.", "analyze_mooring",
                 analysis.result_id)
            break
        step(f"Line {n} governs at {top.pct_wll:.0f}% of WLL; doubling it up.", "analyze_mooring", analysis.result_id)
        rationale.append(RationaleItem(text=f"Doubled up line {n}: it reached {top.pct_wll:.0f}% of WLL.",
                                       cites=[analysis.result_id]))
        cfg = cfg.model_copy(update={"lines": [ln.model_copy(update={"parts": 3}) if ln.line_number == n else ln
                                               for ln in cfg.lines]})

    tugs = await client.berthing_tugs({"ship_class_id": sc.ship_class_id, "loading": sc.loading,
                                       "berth_id": sc.berth_id, "side_to": sc.side_to,
                                       "environment": env.model_dump(mode="json")})
    step(f"Berthing needs {tugs.result.required_lateral_lbf:,.0f} lbf: {tugs.result.recommended_tug_count} tugs, "
         f"{tugs.result.total_power_hp:,.0f} hp.", "plan_tugs", tugs.result_id)
    rationale.append(RationaleItem(text=f"Tugs: {tugs.result.recommended_tug_count} totalling "
                                        f"{tugs.result.total_power_hp:,.0f} hp ({tugs.result.rationale[0]})",
                                   cites=[tugs.result_id]))

    seq = await client.sequence({"ship_class_id": sc.ship_class_id, "berth_id": sc.berth_id,
                                 "config": cfg.model_dump(mode="json", exclude_none=True),
                                 "environment": env.model_dump(mode="json"), "tug_plan_result_id": tugs.result_id})
    step(f"Line sequence: {len(seq.result.steps)} steps, {seq.result.crews_required} crews.", "generate_sequence",
         seq.result_id)

    risk = await client.exceedance({**_analyze_body(sc, cfg, env, mst), "n_samples": 200, "seed": 1})
    step(f"Gust risk: {risk.result.p_any_exceeds_wll:.0%} chance any line passes WLL "
         f"(governing {risk.result.governing_element}).", "risk_exceedance", risk.result_id)
    rationale.append(RationaleItem(text=f"Gust exceedance probability {risk.result.p_any_exceeds_wll:.0%}; "
                                        f"governing element {risk.result.governing_element}.",
                                   cites=[risk.result_id]))

    status = analysis.status if analysis else "RED"
    if status == "GREEN" and risk.result.p_any_exceeds_wll > 0.10:
        status = "AMBER"
    plan_id = new_id("plan")
    open_q = []
    if ship.mst_class == "IIA":
        open_q.append(f"{ship.class_id} is MST IIA: confirm local storm limits with the harbormaster.")
    if any(f.rule_id == "FITTING-CONDITION" for f in (analysis.result.findings if analysis else [])):
        open_q.append("A pier fitting is marked suspect; confirm it was inspected.")
    plan = AgentPlan(plan_id=plan_id, scenario_id=sc.scenario_id, state="succeeded", status=status, config=cfg,
                     tug_plan=tugs.result, sequence=seq.result,
                     analysis_result_id=analysis.result_id if analysis else None, risk_result_id=risk.result_id,
                     rationale=rationale,
                     assumptions=["MOCK AGENT: deterministic loop, no LLM.", *analysis.assumptions[1:2]] if analysis
                     else ["MOCK AGENT: deterministic loop, no LLM."],
                     open_questions=open_q)
    events.append(("done", AgentDoneEvent(plan_id=plan_id, status=status).model_dump(mode="json")))
    rec_ = PlanRecord(plan=plan, scenario=sc, env=env, analysis=analysis, mst=mst, events=events)
    PLANS[plan_id] = rec_
    return rec_


async def answer(rec: PlanRecord, text: str, client: ModelingClient) -> AgentMessageEvent:
    """Mock follow-up: understands '<N> kt' and a compass direction, re-runs the analysis, reports the change."""
    env = rec.env
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:kt|knots?)", text, re.I)
    d = re.search(r"\b(" + "|".join(sorted(COMPASS, key=len, reverse=True)) + r")\b", text.upper())
    if not m and not d:
        msg = AgentMessageEvent(message_id=new_id("msg"), cites=[],
                                text="Mock agent: ask a what-if with a wind speed and direction, e.g. 'NW 35 kt'.")
    else:
        speed = float(m.group(1)) if m else env.wind_speed_kt
        new_env = env.model_copy(update={"wind_speed_kt": speed, "wind_gust_kt": speed * 1.3,
                                         "wind_from_true_deg": COMPASS[d.group(1)] if d else env.wind_from_true_deg})
        res = await client.analyze(_analyze_body(rec.scenario, rec.plan.config, new_env, rec.mst))
        top = res.result.min_margin
        msg = AgentMessageEvent(
            message_id=new_id("msg"), cites=[res.result_id],
            text=f"With wind {speed:.0f} kt (gusts {speed * 1.3:.0f}) from {new_env.wind_from_true_deg:03.0f}, the "
                 f"plan is {res.status}: highest utilization {top.pct_wll:.0f}% on {top.element_id}.")
    rec.messages.append(("message", msg.model_dump(mode="json")))
    return msg
