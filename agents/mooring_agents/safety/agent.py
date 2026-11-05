"""Safety/Brief agent: deterministic verdicts with optional guarded narration."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import AsyncIterator
from importlib.resources import files

import httpx
from pydantic import BaseModel, ConfigDict, Field

from mooring.core.envelopes import new_id, utcnow
from mooring.core.schemas import LimitEnvelopePoint, Validity

from ..intake.mock import REPORTS
from ..physics.client import ModelingClient, ModelingError
from ..physics.toolkit import PhysicsToolkit
from ..planner.mock import PLANS, PlanRecord, _analyze_body
from ..shared import llm
from ..shared.narration import GuardrailError, format_fact, render
from . import checks
from .schemas import (DirectionalThreshold, GustWarning, SafetyReview, SafetyReviewRequest, Thresholds)

REVIEWS: dict[str, SafetyReview] = {}
ENVELOPES: dict[str, list[LimitEnvelopePoint]] = {}
LLM_TIMEOUT_S = 30
logger = logging.getLogger(__name__)


class _ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BriefProposal(_ProposalModel):
    sentences: list[str] = Field(min_length=2, max_length=3)


def plan_record(plan_id: str) -> PlanRecord:
    if plan_id not in PLANS:
        raise ModelingError(404, f"Plan '{plan_id}' not found")
    return PLANS[plan_id]


def latest_review(plan_id: str) -> SafetyReview | None:
    found = [review for review in REVIEWS.values() if review.plan_id == plan_id]
    return max(found, key=lambda review: review.created_at_utc) if found else None


def _headline(verdict: str, passed: int, total: int, limiting_gust: float | None) -> str:
    limit = format_fact("limit_wll_gust_kt", limiting_gust) if limiting_gust is not None else "unavailable"
    return f"Verdict: {verdict.replace('_', ' ')}; {passed} of {total} checks passed; limiting gust is {limit}."


def _brief_facts(review: SafetyReview) -> dict[str, str]:
    facts = {
        "/verdict": review.verdict.replace("_", " "),
        "/status": review.status,
        "/checks/passed": str(sum(check.passed for check in review.checks)),
        "/checks/total": str(len(review.checks)),
    }
    threshold = review.thresholds
    for field in ("governing_element", "limit_wll_gust_kt", "limit_breaking_gust_kt", "forecast_max_gust_kt",
                  "wind_rel_deg"):
        value = getattr(threshold, field)
        if value is not None:
            facts[f"/thresholds/{field}"] = format_fact(field, value)
    for index, check in enumerate(review.checks):
        facts[f"/checks/{index}/title"] = check.title
        facts[f"/checks/{index}/detail"] = check.detail
        facts[f"/checks/{index}/severity"] = check.severity
        facts[f"/checks/{index}/passed"] = format_fact("passed", check.passed)
    return facts


async def _narrate(review: SafetyReview) -> SafetyReview:
    try:
        model = llm.get_llm()
    except llm.LLMNotConfigured:
        return review.model_copy(update={"summary_source": "deterministic",
                                         "narration_note": "provider not configured or unavailable"})
    facts = _brief_facts(review)
    payload = {"checks": [check.model_dump(mode="json") for check in review.checks],
               "thresholds": review.thresholds.model_dump(mode="json"), "facts": facts,
               "response_schema": BriefProposal.model_json_schema()}
    messages = [llm.Message(role="system", content=files(__package__).joinpath("prompts/brief.txt").read_text()),
                llm.Message(role="user", content=json.dumps(payload))]
    try:
        async with asyncio.timeout(LLM_TIMEOUT_S):
            reply = await model.chat(messages, max_tokens=1024, temperature=0.0)
    except Exception as exc:
        timed_out = isinstance(exc, (TimeoutError, httpx.TimeoutException)) or isinstance(exc.__cause__, httpx.TimeoutException)
        note = "provider timeout" if timed_out else "provider error"
        logger.warning("Safety narration unavailable (%s); retaining deterministic review", note)
        return review.model_copy(update={"summary_source": "deterministic", "narration_note": note})
    try:
        if reply.tool_uses or reply.stop_reason not in ("stop", "completed"):
            raise GuardrailError("incomplete response or tool call")
        proposal = BriefProposal.model_validate_json(reply.text)
        brief = " ".join(render(sentence, facts, sentence=True) for sentence in proposal.sentences)
    except GuardrailError as exc:
        note = f"guardrail: {exc}"
        logger.warning("Safety narration rejected (%s); retaining deterministic review", note)
        return review.model_copy(update={"summary_source": "deterministic", "narration_note": note})
    except ValueError:
        return review.model_copy(update={"summary_source": "deterministic",
                                         "narration_note": "guardrail: invalid proposal"})
    return review.model_copy(update={"brief": brief, "summary": f"{review.summary} {brief}",
                                     "summary_source": "llm", "narration_note": None})


def _directional(points: list[LimitEnvelopePoint], factor: float) -> list[DirectionalThreshold]:
    return [DirectionalThreshold(
        wind_rel_deg=point.wind_rel_deg, governing_element=point.first_failure_element,
        limit_wll_gust_kt=_gust_limit(point),
        estimated_breaking_gust_kt=None,
    ) for point in points]


async def review(req: SafetyReviewRequest, tk: PhysicsToolkit) -> SafetyReview:
    rec = plan_record(req.plan_id)
    tk.plan_id = req.plan_id
    plan = rec.plan
    cites = sorted({cite for item in plan.rationale for cite in item.cites})
    results = [await checks.cites_resolve(tk, cites), checks.cites_in_ledger(req.plan_id, cites)]

    intake_id = req.intake_report_id or getattr(plan, "intake_report_id", None)
    report = REPORTS.get(intake_id) if intake_id else None
    if intake_id and report is None:
        raise ModelingError(404, f"Intake report '{intake_id}' not found")
    if report is not None:
        for name, expected in (("berth_id", rec.scenario.berth_id),
                               ("ship_class_id", rec.scenario.ship_class_id),
                               ("side_to", getattr(rec.scenario, "side_to", None))):
            if getattr(report, name, None) not in (None, expected):
                raise ModelingError(422, "Intake report does not match the plan ship, berth or side")
        if not report.planning_conditions:
            raise ModelingError(422, "Intake report has no planning conditions")
    if plan.config is None:
        raise ModelingError(422, "Plan has no configuration to review")
    # Independent re-analysis at every intake planning condition (at least as thorough as the Planner),
    # with the same holding-tug assistance the plan relies on. The worst condition governs the checks.
    environments = [condition.environment for condition in report.planning_conditions] if report else [rec.env]
    holding = getattr(rec, "holding_tugs", None) or []
    reanalyses = [await tk.analyze(_analyze_body(rec.scenario, plan.config, condition, rec.mst, holding))
                  for condition in environments]
    rank = {"GREEN": 0, "INFO": 0, "AMBER": 1, "RED": 2}
    worst_index = max(range(len(reanalyses)),
                      key=lambda i: (rank[reanalyses[i].status], reanalyses[i].result.min_margin.pct_wll))
    reanalysis, env = reanalyses[worst_index], environments[worst_index]
    body = _analyze_body(rec.scenario, plan.config, env, rec.mst, holding)
    reanalysis_checks = [checks.reanalysis_not_red(reanalysis, env),
                         checks.margin(reanalysis, req.target_margin_pct_wll), checks.no_red_findings(reanalysis)]
    for check in reanalysis_checks:
        check.cites = [r.result_id for r in reanalyses]
    results.extend(reanalysis_checks)

    envelope = await tk.envelope({**body, "step_deg": 15})
    worst = envelope.result.worst
    factor = 1.0  # Legacy helper parameter; breaking estimates are deliberately unavailable.
    limit_wll = _gust_limit(worst)
    estimate = None
    forecast_gust = max([condition.environment.wind_gust_kt for condition in report.planning_conditions]
                        if report else [env.wind_gust_kt])
    results.extend([checks.gust_threshold(forecast_gust, limit_wll, envelope.result_id),
                    checks.tugs_feasible(plan.tug_plan), checks.mst_within_ship(report), checks.forecast_coverage(report)])
    checks.validate_check_set(results)

    failed = [result for result in results if not result.passed]
    mst_check = next(check for check in results if check.check_id == "MST-WITHIN-SHIP")
    verdict = "reject" if not mst_check.passed and mst_check.severity == "RED" else ("revise" if failed else "ready_for_signature")
    status = "RED" if any(result.severity == "RED" for result in failed) else "AMBER" if failed else "GREEN"
    # A review must not erase the validity floor imposed by the physics results.
    status = max([status, *(r.status for r in reanalyses), getattr(envelope, "status", "GREEN")], key=rank.get)
    threshold = Thresholds(
        wind_rel_deg=worst.wind_rel_deg, governing_element=worst.first_failure_element,
        limit_wll_gust_kt=limit_wll, forecast_max_gust_kt=forecast_gust,
        limit_breaking_gust_kt=round(estimate, 1) if estimate else None, cites=[envelope.result_id],
        directions=_directional(envelope.result.points, factor),
    )
    validities = [v for item in [*reanalyses, envelope] if (v := getattr(item, "validity", None)) is not None]
    review_validity = None
    if validities:
        state_rank = {"valid": 0, "limited": 1, "unknown": 2, "invalid": 3}
        review_validity = Validity(state=max((v.state for v in validities), key=state_rank.get),
            reasons=list({r.code: r for v in validities for r in v.reasons}.values()))
    headline = _headline(verdict, len(results) - len(failed), len(results), limit_wll)
    result = SafetyReview(
        review_id=new_id("review"), plan_id=req.plan_id, intake_report_id=intake_id,
        created_at_utc=utcnow(), verdict=verdict, status=status, checks=results, thresholds=threshold,
        validity=review_validity, summary=headline, summary_source="deterministic", narration_note=None, backend="real",
    )
    result = await _narrate(result)
    REVIEWS[result.review_id] = result
    ENVELOPES[result.review_id] = envelope.result.points
    return result


def _gust_limit(point):
    # Legacy fixtures with no explicit search outcome used a gust-labeled limit.
    # Current modeling responses must provide the explicit gust basis.
    gust = getattr(point, "limit_gust_kt", None)
    if gust is not None:
        return gust
    return point.limit_wind_kt if getattr(point, "outcome", None) is None else None


def _limit_for(points: list[LimitEnvelopePoint], rel_deg: float) -> LimitEnvelopePoint | None:
    if not points:
        return None
    # Do not substitute a distant known sector when the nearest sector is unknown.
    nearest = min(points, key=lambda point: abs((point.wind_rel_deg - rel_deg + 180) % 360 - 180))
    return nearest if _gust_limit(nearest) is not None else None


def _warning(plan_id: str, env, point: LimitEnvelopePoint | None, factor: float, *, prefix: str = "") -> GustWarning:
    limit = _gust_limit(point) if point is not None else None
    positive_limit = limit is not None and limit > 0
    pct_wll = 100 * env.wind_gust_kt / limit if positive_limit else None
    pct_break = None
    severity = "RED" if pct_wll and pct_wll >= 100 else "AMBER" if pct_wll and pct_wll >= 80 else "INFO"
    if not positive_limit:
        severity = "RED" if limit == 0 else "AMBER"
    message = (f"{prefix}Gust {env.wind_gust_kt:.0f} kt from {env.wind_from_true_deg:03.0f}: " +
               (f"{pct_wll:.0f}% of the {limit:.0f} kt working-load gust limit "
                f"({point.first_failure_element} governs); breaking threshold is unavailable."
                if positive_limit else "gust threshold is unavailable; do not infer safe conditions."))
    return GustWarning(warning_id=new_id("warn"), plan_id=plan_id, at_utc=env.valid_at_utc, severity=severity,
                       gust_kt=env.wind_gust_kt, wind_from_true_deg=env.wind_from_true_deg,
                       pct_of_wll_limit=round(pct_wll, 1) if pct_wll is not None else None,
                       pct_of_breaking_limit=round(pct_break, 1) if pct_break is not None else None,
                       element_id=point.first_failure_element if point else None, message=message)


async def watch(plan_id: str, client: ModelingClient, interval_s: float = 5.0, limit: int = 0,
                heartbeat_minutes: float = 5.0) -> AsyncIterator[GustWarning]:
    """Emit changes, weaker-sector escalations, forecast warnings, and periodic heartbeats."""
    rec = plan_record(plan_id)
    safety_review = latest_review(plan_id)
    if safety_review is None:
        safety_review = await review(SafetyReviewRequest(plan_id=plan_id), PhysicsToolkit(client, "safety", plan_id))
    points = ENVELOPES[safety_review.review_id]
    berth = await client.berth(rec.scenario.berth_id)
    heading = (berth.face_bearing_true_deg if rec.scenario.side_to == "starboard"
               else (berth.face_bearing_true_deg + 180) % 360)
    factor = 1.0  # Legacy helper parameter; breaking estimates are deliberately unavailable.
    emitted = 0

    report = REPORTS.get(safety_review.intake_report_id) if safety_review.intake_report_id else None
    if report:
        for condition in report.planning_conditions:
            rel = (condition.environment.wind_from_true_deg - heading) % 360
            point = _limit_for(points, rel)
            forecast_at = format_fact("valid_at_utc", condition.environment.valid_at_utc)
            warning = _warning(plan_id, condition.environment, point, factor,
                               prefix=f"Forecast ahead at {forecast_at}: ")
            if warning.pct_of_wll_limit is not None and warning.pct_of_wll_limit >= 80:
                yield warning
                emitted += 1
                if limit and emitted >= limit:
                    return

    previous_severity = -1
    previous_element = None
    previous_limit = math.inf
    last_emit = -math.inf
    rank = {"INFO": 0, "AMBER": 1, "RED": 2}
    heartbeat_s = max(heartbeat_minutes * 60, 0)
    while limit == 0 or emitted < limit:
        env = await client.env_now(rec.scenario.berth_id)
        rel = (env.wind_from_true_deg - heading) % 360
        point = _limit_for(points, rel)
        warning = _warning(plan_id, env, point, factor)
        now = time.monotonic()
        point_limit = _gust_limit(point) if point and _gust_limit(point) is not None else math.inf
        severity_rise = rank[warning.severity] > previous_severity
        element_change = warning.element_id != previous_element
        weaker_sector = point_limit < previous_limit
        heartbeat = heartbeat_s == 0 or now - last_emit >= heartbeat_s
        should_emit = severity_rise or element_change or weaker_sector or heartbeat
        if should_emit:
            yield warning
            emitted += 1
            last_emit = now
        previous_severity = rank[warning.severity]
        previous_element = warning.element_id
        previous_limit = point_limit
        if limit and emitted >= limit:
            return
        await asyncio.sleep(interval_s)
