"""Mock Safety/Brief agent: deterministic plan review and live gust warnings. No LLM.

The real agent keeps every check deterministic (pass/fail never comes from an LLM) and adds an LLM-written brief
and rationale over the check results. See safety/README.md.
"""

import asyncio
import math
from collections.abc import AsyncIterator

from mooring.core.envelopes import new_id, utcnow
from mooring.core.schemas import LimitEnvelopePoint
from mooring.rules.nstm582 import design_factor

from ..intake.mock import REPORTS
from ..physics.client import ModelingClient, ModelingError
from ..physics.toolkit import PhysicsToolkit, calls_for
from ..planner.mock import PLANS, PlanRecord, _analyze_body
from .schemas import CheckResult, GustWarning, SafetyReview, SafetyReviewRequest, Thresholds

REVIEWS: dict[str, SafetyReview] = {}
ENVELOPES: dict[str, list[LimitEnvelopePoint]] = {}  # review_id -> limit envelope points


def plan_record(plan_id: str) -> PlanRecord:
    if plan_id not in PLANS:
        raise ModelingError(404, f"Plan '{plan_id}' not found")
    return PLANS[plan_id]


def latest_review(plan_id: str) -> SafetyReview | None:
    found = [r for r in REVIEWS.values() if r.plan_id == plan_id]
    return max(found, key=lambda r: r.created_at_utc) if found else None


async def review(req: SafetyReviewRequest, tk: PhysicsToolkit) -> SafetyReview:
    rec = plan_record(req.plan_id)
    tk.plan_id = req.plan_id
    plan = rec.plan
    checks: list[CheckResult] = []

    def check(cid: str, title: str, passed: bool, severity: str, detail: str, cites: list[str] | None = None):
        checks.append(CheckResult(check_id=cid, title=title, passed=passed, severity="INFO" if passed else severity,
                                  detail=detail, cites=cites or []))

    # 1-2. Every cited number exists and came from a logged physics call made for this plan.
    cites = sorted({c for item in plan.rationale for c in item.cites})
    missing = []
    for cid in cites:
        try:
            await tk.client.result(cid)
        except ModelingError:
            missing.append(cid)
    check("CITES-RESOLVE", "Every cited result exists in the modeling service", not missing, "RED",
          "All citations resolve." if not missing else f"Unresolvable: {', '.join(missing)}", cites)
    ledger_ids = {c.result_id for c in calls_for(req.plan_id) if c.caller == "planner" and c.result_id}
    unlogged = [c for c in cites if c not in ledger_ids]
    check("CITES-IN-LEDGER", "Every cited result came from a logged tool call for this plan", not unlogged, "RED",
          "All citations are in the tool-call ledger." if not unlogged else f"Not in ledger: {', '.join(unlogged)}", cites)

    # 3-5. Independent re-analysis at the worst condition (intake report if given, else the plan's environment).
    report = REPORTS.get(req.intake_report_id) if req.intake_report_id else None
    env = report.planning_conditions[0].environment if report else rec.env
    if plan.config is None:
        raise ModelingError(422, "Plan has no configuration to review")
    body = _analyze_body(rec.scenario, plan.config, env, rec.mst)
    re_an = await tk.analyze(body)
    check("REANALYSIS-NOT-RED", "Independent re-analysis is not RED", re_an.status != "RED", "RED",
          f"Re-analysis status {re_an.status} at gust {env.wind_gust_kt:.0f} kt.", [re_an.result_id])
    top = re_an.result.min_margin
    check("MARGIN", f"Highest utilization at or below {req.target_margin_pct_wll:.0f}% of WLL",
          top.pct_wll <= req.target_margin_pct_wll, "AMBER",
          f"{top.element_id} at {top.pct_wll:.0f}% of WLL.", [re_an.result_id])
    reds = [f for f in re_an.result.findings if f.severity == "RED"]
    check("NO-RED-FINDINGS", "No RED NSTM 582 findings", not reds, "RED",
          "None." if not reds else "; ".join(f"{f.rule_id}: {f.message}" for f in reds), [re_an.result_id])

    # 6. Gust threshold from the limit envelope.
    env_resp = await tk.envelope({**body, "step_deg": 15})
    worst = env_resp.result.worst
    df = design_factor(rec.mst)
    limit_wll = worst.limit_wind_kt
    limit_break = limit_wll * math.sqrt(df) if limit_wll else None
    forecast_gust = max([c.environment.wind_gust_kt for c in report.planning_conditions] if report else [env.wind_gust_kt])
    ratio = forecast_gust / limit_wll if limit_wll else 0.0
    check("GUST-THRESHOLD", "Forecast gusts stay below 80% of the plan's limiting gust", ratio < 0.8,
          "RED" if ratio >= 1 else "AMBER",
          f"Forecast max gust {forecast_gust:.0f} kt vs limit {limit_wll or float('nan'):.0f} kt ({ratio:.0%}).",
          [env_resp.result_id])

    # 7-8. Tugs and Mooring Service Type.
    tugs_ok = plan.tug_plan is None or plan.tug_plan.feasible
    check("TUGS-FEASIBLE", "Available tugs cover the required force", tugs_ok, "RED",
          "Feasible." if tugs_ok else "Required bollard pull exceeds the available tugs.")
    mst_ok = not (report and report.mst.exceeds_ship_mst)
    check("MST-WITHIN-SHIP", "Forecast stays within the ship's Mooring Service Type", mst_ok, "RED",
          report.mst.reason if report else "No intake report; MST not assessed against the forecast.")

    failed = [c for c in checks if not c.passed]
    verdict = "reject" if not mst_ok else ("revise" if any(c.severity == "RED" for c in failed) else "ready_for_signature")
    status = "RED" if any(c.severity == "RED" for c in failed) else "AMBER" if failed else "GREEN"
    rv = SafetyReview(
        review_id=new_id("review"), plan_id=req.plan_id, created_at_utc=utcnow(), verdict=verdict, status=status,
        checks=checks,
        thresholds=Thresholds(wind_rel_deg=worst.wind_rel_deg, governing_element=worst.first_failure_element,
                              limit_wll_gust_kt=limit_wll, forecast_max_gust_kt=forecast_gust,
                              limit_breaking_gust_kt=round(limit_break, 1) if limit_break else None,
                              cites=[env_resp.result_id]),
        summary=f"{len(checks) - len(failed)}/{len(checks)} checks passed; verdict {verdict.replace('_', ' ')}.",
        backend="mock")
    REVIEWS[rv.review_id] = rv
    ENVELOPES[rv.review_id] = env_resp.result.points
    return rv


def _limit_for(points: list[LimitEnvelopePoint], rel_deg: float) -> LimitEnvelopePoint | None:
    usable = [p for p in points if p.limit_wind_kt is not None]
    if not usable:
        return None
    return min(usable, key=lambda p: abs((p.wind_rel_deg - rel_deg + 180) % 360 - 180))


async def watch(plan_id: str, client: ModelingClient, interval_s: float = 5.0, limit: int = 0) -> AsyncIterator[GustWarning]:
    """Compare live gusts with the plan's direction-specific limits; one warning per tick (UI filters INFO)."""
    rec = plan_record(plan_id)
    rv = latest_review(plan_id)
    if rv is None:
        rv = await review(SafetyReviewRequest(plan_id=plan_id), PhysicsToolkit(client, "safety", plan_id))
    points = ENVELOPES[rv.review_id]
    berth = await client.berth(rec.scenario.berth_id)
    heading = berth.face_bearing_true_deg if rec.scenario.side_to == "starboard" else (berth.face_bearing_true_deg + 180) % 360
    df = design_factor(rec.mst)
    sent = 0
    while limit == 0 or sent < limit:
        env = await client.env_now(rec.scenario.berth_id)
        rel = (env.wind_from_true_deg - heading) % 360
        pt = _limit_for(points, rel)
        pct_wll = 100 * env.wind_gust_kt / pt.limit_wind_kt if pt else None
        pct_break = 100 * env.wind_gust_kt / (pt.limit_wind_kt * math.sqrt(df)) if pt else None
        sev = "RED" if pct_wll and pct_wll >= 100 else "AMBER" if pct_wll and pct_wll >= 80 else "INFO"
        msg = (f"Gust {env.wind_gust_kt:.0f} kt from {env.wind_from_true_deg:03.0f}: "
               + (f"{pct_wll:.0f}% of the {pt.limit_wind_kt:.0f} kt working-load limit, {pct_break:.0f}% of estimated "
                  f"breaking ({pt.first_failure_element} governs)." if pt else "wind from this side loads the fenders only."))
        yield GustWarning(warning_id=new_id("warn"), plan_id=plan_id, at_utc=env.valid_at_utc, severity=sev,
                          gust_kt=env.wind_gust_kt, wind_from_true_deg=env.wind_from_true_deg,
                          pct_of_wll_limit=round(pct_wll, 1) if pct_wll else None,
                          pct_of_breaking_limit=round(pct_break, 1) if pct_break else None,
                          element_id=pt.first_failure_element if pt else None, message=msg)
        sent += 1
        if limit == 0 or sent < limit:
            await asyncio.sleep(interval_s)
