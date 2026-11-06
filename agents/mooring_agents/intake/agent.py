"""Intake narration over immutable deterministic findings; no model-authored physics."""

import asyncio
import json
import logging
from importlib.resources import files

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..physics.toolkit import PhysicsToolkit
from ..shared import llm
from ..shared.narration import GuardrailError, format_fact as _format_fact
from . import core
from .schemas import IntakeReport, IntakeRequest, PlanningCondition

REPORTS = core.REPORTS
logger = logging.getLogger(__name__)
LLM_TIMEOUT_S = 30


class _ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WindowPriority(_ProposalModel):
    window_index: int = Field(ge=0)
    impact: int = Field(ge=0, le=10)


class QualityExplanation(_ProposalModel):
    issue_index: int = Field(ge=0)
    statement_id: str = Field(min_length=1, max_length=128)


class ExtraCondition(_ProposalModel):
    forecast_index: int = Field(ge=0)
    reason_id: str = Field(min_length=1, max_length=128)


class NarrativeProposal(_ProposalModel):
    summary_statement_ids: list[str] = Field(min_length=2, max_length=4)
    window_priorities: list[WindowPriority] = Field(default_factory=list)
    data_quality_explanations: list[QualityExplanation] = Field(default_factory=list)
    extra_condition: ExtraCondition | None = None


# Only these typed facts may enter code-owned statements; never recurse through arbitrary fields.
_ENVIRONMENT_FIELDS = (
    "wind_speed_kt", "wind_gust_kt", "wind_from_true_deg", "current_speed_kt",
    "current_set_true_deg", "water_level_mllw_ft",
)
_MST_FIELDS = ("mst_required", "ship_mst", "exceeds_ship_mst", "max_wind_kt", "max_broadside_current_kt")
def _headline(report: IntakeReport) -> str:
    severity = max((w.severity for w in report.windows), key={"INFO": 0, "AMBER": 1, "RED": 2}.get, default=None)
    concern = f"Highest window severity is {severity}" if severity else "No windows of concern"
    required = "above III" if report.mst.mst_required == "exceeds_III" else report.mst.mst_required
    if report.mst.ship_mst is None:
        comparison = "ship MST is unknown, so exceedance cannot be assessed"
    else:
        relation = "exceeds" if report.mst.exceeds_ship_mst else "does not exceed"
        comparison = f"it {relation} the ship's MST {report.mst.ship_mst}"
    incomplete = any(q.issue == "missing" and q.severity == "RED" for q in report.data_quality)
    if incomplete:
        return f"Forecast assessment incomplete; {concern.lower()}; MST from available snapshots is {required}; future exceedance is unknown."
    quality = max((q.severity for q in report.data_quality
                   if q.issue in ("missing", "stale", "flagged", "out_of_range")
                   and q.severity in ("AMBER", "RED")),
                  key={"AMBER": 1, "RED": 2}.get, default=None)
    qualification = f"; input quality is {quality}; review is required before relying on this assessment" if quality else ""
    return f"{concern}; MST required is {required}; {comparison}{qualification}."


def _environment_facts(value, path, *, include_time):
    fields = (*_ENVIRONMENT_FIELDS, "valid_at_utc") if include_time else _ENVIRONMENT_FIELDS
    return {f"{path}/{field}": _format_fact(field, value[field]) for field in fields if value.get(field) is not None}


def _facts(value) -> dict[str, str]:
    """Allowlisted report facts with code-owned units and UTC presentation."""
    facts = _environment_facts(value["current"], "/current", include_time=False)
    for index, condition in enumerate(value["planning_conditions"]):
        facts.update(_environment_facts(condition["environment"], f"/planning_conditions/{index}/environment", include_time=True))
    for index, window in enumerate(value["windows"]):
        for field in ("start_utc", "end_utc", "peak_value", "severity", "kind"):
            facts[f"/windows/{index}/{field}"] = _format_fact(field, window[field], window["unit"] if field == "peak_value" else None)
    for field in _MST_FIELDS:
        if value["mst"][field] is not None:
            facts[f"/mst/{field}"] = _format_fact(field, value["mst"][field])
    return facts


_QUALITY_MEANING = {
    "stale": "Verify the affected data against a current source before relying on it for mooring.",
    "missing": "Missing data leaves conditions unassessed; obtain the missing evidence before relying on this assessment.",
    "flagged": "Review the source quality flags before relying on the affected conditions for mooring.",
    "out_of_range": "The input is outside its stated validity or accepted bounds and needs review before use in mooring planning.",
    "mock": "These values are synthetic scenario data and cannot establish actual docking conditions.",
}


def _statements(report, series):
    """Complete statements with code-owned meaning, units and typed facts.

    Selection can emphasize facts, but cannot negate them, attach an operational
    instruction or transplant an explanation to another issue/snapshot.
    """
    facts = _facts(report.model_dump())
    current = "/current"
    summary = {
        "current-wind": f"Current wind is {facts[current + '/wind_speed_kt']} with gusts of {facts[current + '/wind_gust_kt']} from {facts[current + '/wind_from_true_deg']}.",
        "current-current": f"Current flow is {facts[current + '/current_speed_kt']} toward {facts[current + '/current_set_true_deg']}.",
        "current-water-level": f"Water level is {facts[current + '/water_level_mllw_ft']} relative to MLLW.",
        "mooring-review": "This environmental assessment informs mooring planning and does not authorize docking.",
    }
    if report.planning_conditions:
        peak = "/planning_conditions/0/environment"
        summary["peak-gust"] = f"Gusts reach {facts[peak + '/wind_gust_kt']} in the peak-gust planning condition."
        summary["peak-time"] = f"The peak-gust planning condition is at {facts[peak + '/valid_at_utc']}."
    for index, window in enumerate(report.windows):
        prefix = f"/windows/{index}"
        summary[f"window-{index}"] = (
            f"The {facts[prefix + '/severity']} {window.kind.replace('_', ' ')} window runs from "
            f"{facts[prefix + '/start_utc']} to {facts[prefix + '/end_utc']}, "
            f"with a peak of {facts[prefix + '/peak_value']}."
        )
    quality = {f"quality-{index}": _QUALITY_MEANING[issue.issue]
               for index, issue in enumerate(report.data_quality)}
    extra = {f"forecast-{index}": (
        f"Compare the forecast snapshot at {_format_fact('valid_at_utc', snapshot.valid_at_utc)} "
        "with the existing planning conditions; this selection does not authorize docking."
    ) for index, snapshot in enumerate(series)}
    return {"summary": summary, "data_quality": quality, "extra_conditions": extra}


def _unique_indices(items, attribute, length):
    indices = [getattr(item, attribute) for item in items]
    if len(set(indices)) != len(indices) or any(i >= length for i in indices):
        raise GuardrailError("proposal index")


def _apply(report, series, proposal, statements):
    """Build a copy atomically; no partial LLM changes escape failed validation."""
    _unique_indices(proposal.window_priorities, "window_index", len(report.windows))
    _unique_indices(proposal.data_quality_explanations, "issue_index", len(report.data_quality))
    selected = proposal.summary_statement_ids
    if len(set(selected)) != len(selected) or any(key not in statements["summary"] for key in selected):
        raise GuardrailError("statement selection")
    result = report.model_copy(deep=True)
    result.summary = _headline(report) + " " + " ".join(statements["summary"][key] for key in selected)
    scores = {p.window_index: p.impact for p in proposal.window_priorities}
    result.windows = [w for i, w in sorted(enumerate(result.windows), key=lambda pair: -scores.get(pair[0], 0))]
    for item in proposal.data_quality_explanations:
        if item.statement_id != f"quality-{item.issue_index}" or item.statement_id not in statements["data_quality"]:
            raise GuardrailError("statement selection")
        issue = result.data_quality[item.issue_index]
        issue.detail += " " + statements["data_quality"][item.statement_id]
    if proposal.extra_condition is not None:
        extra = proposal.extra_condition
        if extra.forecast_index >= len(series):
            raise GuardrailError("forecast index")
        if extra.reason_id != f"forecast-{extra.forecast_index}" or extra.reason_id not in statements["extra_conditions"]:
            raise GuardrailError("statement selection")
        snapshot = series[extra.forecast_index]
        why = statements["extra_conditions"][extra.reason_id]
        if not any(p.environment == snapshot for p in result.planning_conditions):
            result.planning_conditions.append(PlanningCondition(
                label="Additional forecast condition", environment=snapshot.model_copy(deep=True), why=why,
            ))
    result.summary_source = "llm"
    result.narration_note = None
    return result


async def assess(req: IntakeRequest, tk: PhysicsToolkit) -> IntakeReport:
    report, series = await core.assess_with_forecast(req, tk)
    report = report.model_copy(update={"backend": "real", "summary_source": "deterministic",
                                       "narration_note": None, "summary": _headline(report) + " " + report.summary}, deep=True)
    try:
        model = llm.get_llm()
    except llm.LLMNotConfigured:
        report.narration_note = "provider not configured or unavailable"
        REPORTS[report.report_id] = report
        return report

    statements = _statements(report, series)
    payload = {"report": report.model_dump(mode="json", exclude={"forecast_request"}), "statements": statements,
               "forecast": [s.model_dump(mode="json") for s in series],
               "response_schema": NarrativeProposal.model_json_schema()}
    messages = [llm.Message(role="system", content=files(__package__).joinpath("prompts/summary.txt").read_text()),
                llm.Message(role="user", content=json.dumps(payload))]
    try:
        async with asyncio.timeout(LLM_TIMEOUT_S):
            reply = await model.chat(messages, max_tokens=2048, temperature=0.0)
    except Exception as exc:
        # Provider failures cannot invalidate the deterministic assessment. Do not log payloads/keys.
        timed_out = isinstance(exc, (TimeoutError, httpx.TimeoutException)) or isinstance(exc.__cause__, httpx.TimeoutException)
        report.narration_note = "provider timeout" if timed_out else "provider error"
        logger.warning("Intake narration unavailable (%s); retaining deterministic report", report.narration_note)
    else:
        try:
            if reply.tool_uses or reply.stop_reason not in ("stop", "completed"):
                raise GuardrailError("incomplete response or tool call")
            proposal = NarrativeProposal.model_validate_json(reply.text)
            report = _apply(report, series, proposal, statements)
        except GuardrailError as exc:
            report.narration_note = f"guardrail: {exc}"
            logger.warning("Intake narration rejected (%s); retaining deterministic report", report.narration_note)
        except ValueError:
            report.narration_note = "guardrail: invalid proposal"
            logger.warning("Intake narration rejected (%s); retaining deterministic report", report.narration_note)
    REPORTS[report.report_id] = report
    return report
