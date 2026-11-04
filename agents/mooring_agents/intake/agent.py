"""Intake narration over immutable deterministic findings; no model-authored physics."""

import asyncio
import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from importlib.resources import files

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..physics.toolkit import PhysicsToolkit
from ..shared import llm
from . import core
from .schemas import IntakeReport, IntakeRequest, PlanningCondition

REPORTS = core.REPORTS
logger = logging.getLogger(__name__)
LLM_TIMEOUT_S = 30
_REFERENCE = re.compile(r"\{\{([^{}]+)\}\}")
_NUMBER_WORDS = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred|thousand|million|billion|half|quarter|twice|"
    r"double|triple|dozen|couple|first|second|third|fourth|fifth)\b", re.IGNORECASE,
)


class _ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WindowPriority(_ProposalModel):
    window_index: int = Field(ge=0)
    impact: int = Field(ge=0, le=10)


class QualityExplanation(_ProposalModel):
    issue_index: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=1000)


class ExtraCondition(_ProposalModel):
    forecast_index: int = Field(ge=0)
    why: str = Field(min_length=1, max_length=1000)


class NarrativeProposal(_ProposalModel):
    summary_sentences: list[str] = Field(min_length=2, max_length=4)
    window_priorities: list[WindowPriority] = Field(default_factory=list)
    data_quality_explanations: list[QualityExplanation] = Field(default_factory=list)
    extra_condition: ExtraCondition | None = None


# Only these typed facts may enter model-written text; never recurse through arbitrary fields.
_ENVIRONMENT_FIELDS = (
    "wind_speed_kt", "wind_gust_kt", "wind_from_true_deg", "current_speed_kt",
    "current_set_true_deg", "water_level_mllw_ft",
)
_MST_FIELDS = ("mst_required", "ship_mst", "exceeds_ship_mst", "max_wind_kt", "max_broadside_current_kt")
_RISK_LANGUAGE = re.compile(
    r"\b(?:RED|AMBER|GREEN|safe(?:r|st)?|calm(?:er|est)?|benign)\b|\blow[\W_]+risk\b|"
    r"\bMST[\s:=-]+[IVXLCDM]+A?\b", re.IGNORECASE,
)
_UNIT_TOKENS = re.compile(r"(?<!\w)(?:kts?|knots?|m\s*/\s*s|mph|deg(?:ree)?s?|ft)(?!\w)|°", re.IGNORECASE)


class GuardrailError(ValueError):
    """A fixed, non-sensitive reason suitable for report provenance."""


def _headline(report: IntakeReport) -> str:
    severity = max((w.severity for w in report.windows), key={"INFO": 0, "AMBER": 1, "RED": 2}.get, default=None)
    concern = f"Highest window severity is {severity}" if severity else "No windows of concern"
    required = "above III" if report.mst.mst_required == "exceeds_III" else report.mst.mst_required
    if report.mst.ship_mst is None:
        comparison = "ship MST is unknown, so exceedance cannot be assessed"
    else:
        relation = "exceeds" if report.mst.exceeds_ship_mst else "does not exceed"
        comparison = f"it {relation} the ship's MST {report.mst.ship_mst}"
    return f"{concern}; MST required is {required}; {comparison}."


def _format_fact(field, value, unit=None):
    if field.endswith("_utc"):
        if not isinstance(value, datetime):
            raise ValueError("Time facts must be typed datetimes")
        return value.astimezone(UTC).strftime("%H:%MZ %d %b")
    if isinstance(value, bool):
        return "yes" if value else "no"
    if unit is None:
        unit = next((suffix for suffix in ("kt", "deg", "ft") if field.endswith("_" + suffix)), None)
    suffix = "°" if unit == "deg" else f" {unit}" if unit else ""
    return f"{value}{suffix}"


def _environment_facts(value, path, *, include_time):
    fields = (*_ENVIRONMENT_FIELDS, "valid_at_utc") if include_time else _ENVIRONMENT_FIELDS
    return {f"{path}/{field}": _format_fact(field, value[field]) for field in fields if value.get(field) is not None}


def _facts(value, path="") -> dict[str, str]:
    """Allowlisted report facts with code-owned units and UTC presentation."""
    if path.startswith("forecast/"):
        # Only used for the exact snapshot selected as an extra planning condition.
        return _environment_facts(value, path, include_time=True)
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


def _render(template: str, facts: dict[str, str], *, sentence=False) -> str:
    if any(ch.isnumeric() for ch in _REFERENCE.sub("FACT", template)):
        raise GuardrailError("numeric literal")
    template = unicodedata.normalize("NFKC", template).strip()
    literal = _REFERENCE.sub("FACT", template)
    if (not literal or len(template) > 1000 or any(ch.isnumeric() for ch in literal)
            or _NUMBER_WORDS.search(literal) or "{" in literal or "}" in literal):
        raise GuardrailError("numeric literal or malformed reference")
    if _RISK_LANGUAGE.search(literal):
        raise GuardrailError("risk language")
    if _UNIT_TOKENS.search(literal):
        raise GuardrailError("unit token")
    if sentence and (not literal.endswith(".") or re.search(r"[.!?]", literal[:-1])):
        raise GuardrailError("sentence structure")

    def replace(match):
        if match[1] not in facts:
            raise GuardrailError("fact reference")
        return facts[match[1]]

    return _REFERENCE.sub(replace, template)


def _unique_indices(items, attribute, length):
    indices = [getattr(item, attribute) for item in items]
    if len(set(indices)) != len(indices) or any(i >= length for i in indices):
        raise GuardrailError("proposal index")


def _apply(report, series, proposal, facts):
    """Build a copy atomically; no partial LLM changes escape failed validation."""
    _unique_indices(proposal.window_priorities, "window_index", len(report.windows))
    _unique_indices(proposal.data_quality_explanations, "issue_index", len(report.data_quality))
    result = report.model_copy(deep=True)
    result.summary = _headline(report) + " " + " ".join(_render(s, facts, sentence=True) for s in proposal.summary_sentences)
    scores = {p.window_index: p.impact for p in proposal.window_priorities}
    result.windows = [w for i, w in sorted(enumerate(result.windows), key=lambda pair: -scores.get(pair[0], 0))]
    for item in proposal.data_quality_explanations:
        issue = result.data_quality[item.issue_index]
        issue.detail += " " + _render(item.explanation, facts)
    if proposal.extra_condition is not None:
        extra = proposal.extra_condition
        if extra.forecast_index >= len(series):
            raise GuardrailError("forecast index")
        snapshot = series[extra.forecast_index]
        extra_facts = _facts(snapshot.model_dump(), f"forecast/{extra.forecast_index}")
        why = _render(extra.why, facts | extra_facts)
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

    facts = _facts(report.model_dump(exclude={"summary"}))
    payload = {"report": report.model_dump(mode="json"), "facts": facts,
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
            report = _apply(report, series, proposal, facts)
        except GuardrailError as exc:
            report.narration_note = f"guardrail: {exc}"
            logger.warning("Intake narration rejected (%s); retaining deterministic report", report.narration_note)
        except ValueError:
            report.narration_note = "guardrail: invalid proposal"
            logger.warning("Intake narration rejected (%s); retaining deterministic report", report.narration_note)
    REPORTS[report.report_id] = report
    return report
