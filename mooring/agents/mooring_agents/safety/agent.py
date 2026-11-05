"""Safety/Brief agent: deterministic verdicts with optional guarded narration."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import AsyncIterator
from datetime import UTC
from importlib.resources import files

import httpx
from pydantic import BaseModel, ConfigDict, Field

from mooring.core import access
from mooring.core.envelopes import new_id, utcnow
from mooring.core.forecast_provenance import availability_problem
from mooring.core.schemas import LimitEnvelopePoint, Validity

from ..intake.mock import REPORTS
from ..physics.client import ModelingClient, ModelingError
from ..physics.toolkit import PhysicsToolkit
from ..planner.mock import PLANS, PlanRecord, _analyze_body
from ..shared import llm
from ..shared.environment_quality import component_issues
from ..shared.forecast import bound_samples, resolve_forecast, same_forecast
from ..shared.layout import review_geometry_matches
from ..shared.narration import GuardrailError, format_fact, render
from . import checks
from .schemas import (DirectionalThreshold, GustWarning, SafetyReview, SafetyReviewRequest, Thresholds)

from ..shared.storage import AgentStore

REVIEWS = AgentStore("agent_review", SafetyReview)
ENVELOPES = AgentStore("agent_envelope", list[LimitEnvelopePoint], owner_kind="agent_review")
LLM_TIMEOUT_S = 30
logger = logging.getLogger(__name__)


class _ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BriefProposal(_ProposalModel):
    sentences: list[str] = Field(min_length=2, max_length=3)


def plan_record(plan_id: str) -> PlanRecord:
    if not access.allowed("agent_plan", plan_id) or plan_id not in PLANS:
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
    forecast_manifest = getattr(plan, "forecast_manifest", None)
    forecast_result_id = getattr(plan, "forecast_result_id", None)
    if forecast_manifest is not None:
        if plan.forecast_request is None:
            raise ModelingError(422, "Bound plan has no saved forecast selection; create a new Intake and plan")
        resolution = await resolve_forecast(tk, plan.forecast_request, forecast_manifest)
        forecast_result_id = resolution.result_id
    cites = sorted({cite for item in plan.rationale for cite in item.cites})
    results = [await checks.cites_resolve(tk, cites), checks.cites_in_ledger(req.plan_id, cites)]

    original_id = getattr(plan, "intake_report_id", None)
    intake_id = req.intake_report_id or original_id
    report_ids = list(dict.fromkeys(value for value in (original_id, intake_id) if value))
    reports = []
    for report_id in report_ids:
        report = REPORTS.get(report_id) if access.allowed("agent_report", report_id) else None
        if report is None:
            raise ModelingError(404, f"Intake report '{report_id}' not found")
        for name, expected in (("berth_id", rec.scenario.berth_id),
                               ("ship_class_id", rec.scenario.ship_class_id),
                               ("side_to", getattr(rec.scenario, "side_to", None))):
            if getattr(report, name, None) not in (None, expected):
                raise ModelingError(422, "Intake report does not match the plan ship, berth or side")
        if not report.planning_conditions:
            raise ModelingError(422, "Intake report has no planning conditions")
        if not same_forecast(forecast_manifest, getattr(report, "forecast_manifest", None)):
            raise ModelingError(409, "Intake forecast binding differs from the plan; create a new plan for explicit reassessment, without transferring prior approvals")
        reports.append(report)
    if plan.config is None:
        raise ModelingError(422, "Plan has no configuration to review")
    # A supplemental intake adds conditions; it cannot erase the plan's original design conditions.
    environments = [condition.environment for report in reports for condition in report.planning_conditions] or [rec.env]
    environments = list({json.dumps(env.model_dump(mode="json"), sort_keys=True): env for env in environments}.values())
    holding = getattr(rec, "holding_tugs", None) or []
    installation_tide = getattr(plan, "installed_at_water_level_mllw_ft", None)
    reanalyses = [await tk.analyze(_analyze_body(rec.scenario, plan.config, condition, rec.mst, holding, installation_tide))
                  for condition in environments]
    rank = {"GREEN": 0, "INFO": 0, "AMBER": 1, "RED": 2}
    reanalysis_checks = [
        checks.all_conditions([checks.reanalysis_not_red(result, condition) for result, condition in zip(reanalyses, environments)]),
        checks.all_conditions([checks.margin(result, req.target_margin_pct_wll) for result in reanalyses]),
        checks.all_conditions([checks.no_red_findings(result) for result in reanalyses]),
    ]
    results.extend(reanalysis_checks)

    envelopes = [await tk.envelope({**_analyze_body(rec.scenario, plan.config, condition, rec.mst, holding, installation_tide), "step_deg": 15})
                 for condition in environments]
    points = _conservative_points(envelopes)
    worst = min(points, key=lambda point: (0, 0) if _gust_limit(point) is None else (1, _gust_limit(point)))
    factor = 1.0  # Legacy helper parameter; breaking estimates are deliberately unavailable.
    limit_wll = _gust_limit(worst)
    estimate = None
    forecast_gust = max(condition.wind_gust_kt for condition in environments)
    gust_check = checks.gust_threshold(forecast_gust, limit_wll, envelopes[0].result_id)
    gust_check.cites = [item.result_id for item in envelopes]
    results.extend([gust_check, checks.tugs_feasible(plan.tug_plan),
                    checks.all_conditions([checks.mst_within_ship(report) for report in reports or [None]]),
                    checks.all_conditions([checks.forecast_coverage(report) for report in reports or [None]]),
                    checks.plan_not_red(plan)])
    checks.validate_check_set(results)

    failed = [result for result in results if not result.passed]
    mst_check = next(check for check in results if check.check_id == "MST-WITHIN-SHIP")
    verdict = "reject" if not mst_check.passed and mst_check.severity == "RED" else ("revise" if failed else "ready_for_signature")
    status = "RED" if any(result.severity == "RED" for result in failed) else "AMBER" if failed else "GREEN"
    # A review must not erase the validity floor imposed by the physics results.
    status = max([status, *(r.status for r in reanalyses), *(getattr(item, "status", "GREEN") for item in envelopes),
                  getattr(plan, "status", None) or "AMBER"], key=rank.get)
    threshold = Thresholds(
        wind_rel_deg=worst.wind_rel_deg, governing_element=worst.first_failure_element,
        limit_wll_gust_kt=limit_wll, forecast_max_gust_kt=forecast_gust,
        limit_breaking_gust_kt=round(estimate, 1) if estimate else None, cites=[item.result_id for item in envelopes],
        directions=_directional(points, factor),
    )
    validities = [v for item in [*reanalyses, *envelopes] if (v := getattr(item, "validity", None)) is not None]
    review_validity = None
    if validities:
        state_rank = {"valid": 0, "limited": 1, "unknown": 2, "invalid": 3}
        review_validity = Validity(state=max((v.state for v in validities), key=state_rank.get),
            reasons=list({r.code: r for v in validities for r in v.reasons}.values()))
    headline = _headline(verdict, len(results) - len(failed), len(results), limit_wll)
    result = SafetyReview(
        geometry_snapshot_verified=review_geometry_matches(getattr(rec, "geometry_snapshot", None), [*reanalyses, *envelopes]),
        **({"forecast_manifest": forecast_manifest, "forecast_result_id": forecast_result_id} if forecast_manifest is not None else {}),
        review_id=new_id("review"), plan_id=req.plan_id, intake_report_id=intake_id,
        created_at_utc=utcnow(), verdict=verdict, status=status, checks=results, thresholds=threshold,
        validity=review_validity, summary=headline, summary_source="deterministic", narration_note=None, backend="real",
    )
    result = await _narrate(result)
    access.claim("agent_review", result.review_id)
    REVIEWS[result.review_id] = result
    ENVELOPES[result.review_id] = points
    return result


def _conservative_points(envelopes):
    """Choose the least established/lowest solver limit in each direction across conditions."""
    angles = sorted({point.wind_rel_deg for item in envelopes for point in item.result.points})
    if not angles:
        raise ModelingError(502, "Modeling returned an empty limit envelope")
    out = []
    for angle in angles:
        candidates = [next((point for point in item.result.points if point.wind_rel_deg == angle), None)
                      for item in envelopes]
        if any(point is None for point in candidates):
            raise ModelingError(502, "Modeling returned inconsistent limit-envelope directions")
        out.append(min(candidates, key=lambda point: (0, 0) if _gust_limit(point) is None else (1, _gust_limit(point))))
    return out


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


def _warning(plan_id: str, env, point: LimitEnvelopePoint | None, factor: float, *, prefix: str = "",
             recheck_reasons: list[str] | None = None, invalid_input: bool = False) -> GustWarning:
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
    reasons = list(recheck_reasons or [])
    if not positive_limit:
        reasons.append("No positive assessed gust limit is available.")
    if recheck_reasons:
        pct_wll = None
        severity = "RED" if severity == "RED" or invalid_input else "AMBER"
        message = f"{prefix}Reanalysis required before using the assessed gust limits: " + " ".join(reasons)
    return GustWarning(warning_id=new_id("warn"), plan_id=plan_id, at_utc=env.valid_at_utc, severity=severity,
                       gust_kt=env.wind_gust_kt, wind_from_true_deg=env.wind_from_true_deg,
                       pct_of_wll_limit=round(pct_wll, 1) if pct_wll is not None else None,
                       pct_of_breaking_limit=round(pct_break, 1) if pct_break is not None else None,
                       element_id=point.first_failure_element if point else None, message=message,
                       requires_recheck=bool(reasons), recheck_reasons=reasons)


def _watch_recheck(env, assessed) -> tuple[list[str], bool]:
    """Compare supplied facts, never recompute or extrapolate a physical threshold in the agent."""
    problems = [item for item in component_issues(env) if item[2] in ("AMBER", "RED")]
    reasons = [item[3] for item in problems]
    invalid = any(item[2] == "RED" for item in problems)
    if problem := availability_problem(env, utcnow()):
        reasons.append(problem)
        invalid = True
    fields = ("current_speed_kt", "current_set_true_deg", "water_level_mllw_ft", "air_density_kgm3", "water_density_kgm3")
    if not any(all(getattr(env, field) == getattr(prior, field) for field in fields) for prior in assessed):
        reasons.append("Current, water level or density differs from the reviewed conditions; wind limits have not been recomputed.")
    meta = env.metadata
    if meta and meta.quality in ("suspect", "poor"):
        reasons.append("The environment provider reports suspect or poor quality.")
        invalid = invalid or meta.quality == "poor"
    flags = " ".join(flag for station in env.quality for flag in station.flags).lower()
    if any(word in flags for word in ("missing", "unavailable", "stale", "suspect", "poor", "invalid", "gap")):
        reasons.append("A required environmental source is flagged; review source availability and freshness.")
        invalid = invalid or any(word in flags for word in ("missing", "unavailable", "poor", "invalid", "gap"))
    at = (env.valid_at_utc.astimezone(UTC)
          if env.valid_at_utc.tzinfo is not None and env.valid_at_utc.utcoffset() is not None else None)
    if at is None or (meta and (
            (meta.valid_from_utc and at < meta.valid_from_utc)
            or (meta.valid_to_utc and at > meta.valid_to_utc))):
        reasons.append("Environment time is unspecified or outside its declared validity interval.")
        invalid = True
    basis_fields = ("wind_averaging_s", "gust_duration_s", "wind_reference_height_m")
    basis = tuple(getattr(meta, field, None) for field in basis_fields)
    if not any(basis == tuple(getattr(prior.metadata, field, None) for field in basis_fields) for prior in assessed):
        reasons.append("Wind duration or reference height differs from the reviewed basis.")
    return reasons, invalid


def _bound_watch_time(resolution):
    """Forecast-ahead messages and polling share the same closed coverage interval."""
    at = utcnow()
    manifest = resolution.result.forecast_manifest
    if not manifest.from_utc <= at <= manifest.to_utc:
        raise ModelingError(409, "Watch time is outside the assessed forecast interval; explicit reassessment is required")
    return at


async def watch(plan_id: str, client: ModelingClient, interval_s: float = 5.0, limit: int = 0,
                heartbeat_minutes: float = 5.0) -> AsyncIterator[GustWarning]:
    """Emit changes, weaker-sector escalations, forecast warnings, and periodic heartbeats."""
    rec = plan_record(plan_id)
    safety_review = latest_review(plan_id)
    if safety_review is None:
        safety_review = await review(SafetyReviewRequest(plan_id=plan_id), PhysicsToolkit(client, "safety", plan_id))
    points = ENVELOPES[safety_review.review_id]
    geometry = getattr(rec, "geometry_snapshot", None)
    if geometry is not None:
        if geometry.unavailable_reason or getattr(safety_review, "geometry_snapshot_verified", None) is not True:
            raise ModelingError(409, "Review geometry is not bound to this plan; explicit reassessment is required before watching gust limits")
        # Threshold sectors were assessed in this frame. A changed catalog heading
        # must not silently rotate them after the independent review.
        berth = geometry.berth
        side_to = geometry.config.side_to
    else:
        berth = await client.berth(rec.scenario.berth_id)
        side_to = rec.scenario.side_to
    heading = (berth.face_bearing_true_deg if side_to == "starboard"
               else (berth.face_bearing_true_deg + 180) % 360)
    factor = 1.0  # Legacy helper parameter; breaking estimates are deliberately unavailable.
    emitted = 0
    forecast_request = getattr(getattr(rec, "plan", None), "forecast_request", None)
    bound_resolution = None
    if forecast_request is not None:
        # Check identity before emitting any forecast-ahead percentage from an archived review.
        forecast_request = forecast_request.model_copy(deep=True)
        watch_tk = PhysicsToolkit(client, "safety", plan_id, operation_id=new_id("forecast_watch"))
        bound_resolution = await resolve_forecast(watch_tk, forecast_request, rec.plan.forecast_manifest)
        _bound_watch_time(bound_resolution)

    report = REPORTS.get(safety_review.intake_report_id) if safety_review.intake_report_id else None
    report_ids = {value for value in (safety_review.intake_report_id,
        getattr(getattr(rec, "plan", None), "intake_report_id", None)) if value}
    # Match review() exactly: reports replace the fallback snapshot, and supplemental reports add
    # to the original intake. Never treat the old fallback as reviewed when it was not assessed.
    assessed = [condition.environment for report_id in report_ids if (source_report := REPORTS.get(report_id))
                for condition in source_report.planning_conditions] if report_ids else [rec.env]
    if report:
        for condition in report.planning_conditions:
            rel = (condition.environment.wind_from_true_deg - heading) % 360
            point = _limit_for(points, rel)
            forecast_at = format_fact("valid_at_utc", condition.environment.valid_at_utc)
            reasons, invalid = _watch_recheck(condition.environment, assessed)
            warning = _warning(plan_id, condition.environment, point, factor,
                               prefix=f"Forecast ahead at {forecast_at}: ", recheck_reasons=reasons, invalid_input=invalid)
            if warning.requires_recheck or (warning.pct_of_wll_limit is not None and warning.pct_of_wll_limit >= 80):
                if bound_resolution is not None:
                    # A slow SSE consumer can resume after the interval has expired.
                    _bound_watch_time(bound_resolution)
                yield warning
                emitted += 1
                if limit and emitted >= limit:
                    return

    previous_severity = -1
    previous_element = None
    previous_limit = math.inf
    previous_recheck = None
    last_emit = -math.inf
    rank = {"INFO": 0, "AMBER": 1, "RED": 2}
    heartbeat_s = max(heartbeat_minutes * 60, 0)
    while limit == 0 or emitted < limit:
        if forecast_request is not None:
            # An explicit bound forecast must not be replaced by the scenario's unrelated default provider.
            # Supplied bytes are immutable and have no latest-revision endpoint. Scenario records can change,
            # so refresh only those, with each poll a separately budgeted, logged operation.
            if bound_resolution is None:
                watch_tk = PhysicsToolkit(client, "safety", plan_id, operation_id=new_id("forecast_watch"))
                bound_resolution = await resolve_forecast(watch_tk, forecast_request, rec.plan.forecast_manifest)
            resolution = bound_resolution
            manifest = resolution.result.forecast_manifest
            if manifest.source == "scenario":
                bound_resolution = None
            at = _bound_watch_time(resolution)
            samples = [sample for sample in bound_samples(resolution) if sample.valid_at_utc <= at]
            if not samples:
                raise ModelingError(422, "No assessed forecast sample covers the watch time")
            env = samples[-1]
        else:
            env = await client.scenario_environment(rec.scenario.scenario_id)
        rel = (env.wind_from_true_deg - heading) % 360
        point = _limit_for(points, rel)
        recheck_reasons, invalid_input = _watch_recheck(env, assessed)
        warning = _warning(plan_id, env, point, factor, recheck_reasons=recheck_reasons, invalid_input=invalid_input,
                           prefix="Bound forecast sample: " if forecast_request is not None else "")
        now = time.monotonic()
        point_limit = _gust_limit(point) if point and _gust_limit(point) is not None else math.inf
        severity_rise = rank[warning.severity] > previous_severity
        element_change = warning.element_id != previous_element
        weaker_sector = point_limit < previous_limit
        heartbeat = heartbeat_s == 0 or now - last_emit >= heartbeat_s
        recheck_changed = tuple(warning.recheck_reasons) != previous_recheck
        should_emit = severity_rise or element_change or weaker_sector or heartbeat or recheck_changed
        if should_emit:
            yield warning
            emitted += 1
            last_emit = now
        previous_severity = rank[warning.severity]
        previous_element = warning.element_id
        previous_limit = point_limit
        previous_recheck = tuple(warning.recheck_reasons)
        if limit and emitted >= limit:
            return
        await asyncio.sleep(interval_s)
