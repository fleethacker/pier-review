"""Intake narration over immutable deterministic findings; no model-authored physics."""

import asyncio
import json
import logging
import re
import unicodedata
from datetime import datetime
from importlib.resources import files

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
    summary_sentences: list[str] = Field(min_length=3, max_length=5)
    window_priorities: list[WindowPriority] = Field(default_factory=list)
    data_quality_explanations: list[QualityExplanation] = Field(default_factory=list)
    extra_condition: ExtraCondition | None = None


def _facts(value, path="") -> dict[str, str]:
    """Only typed numeric/time/enum leaves qualify; IDs and prose cannot launder numbers."""
    if isinstance(value, dict):
        return {k: v for key, child in value.items() for k, v in _facts(child, f"{path}/{key}").items()}
    if isinstance(value, list):
        return {k: v for index, child in enumerate(value) for k, v in _facts(child, f"{path}/{index}").items()}
    if isinstance(value, datetime):
        return {path: value.isoformat()}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {path: str(value)}
    if isinstance(value, str) and path.rsplit("/", 1)[-1] in {"severity", "mst_required", "ship_mst", "kind", "issue", "source"}:
        return {path: value}
    return {}


def _render(template: str, facts: dict[str, str], *, sentence=False) -> str:
    if any(ch.isnumeric() for ch in _REFERENCE.sub("FACT", template)):
        raise ValueError("Narrative quantities require fact references")
    template = unicodedata.normalize("NFKC", template).strip()
    literal = _REFERENCE.sub("FACT", template)
    if (not literal or len(template) > 1000 or any(ch.isnumeric() for ch in literal)
            or _NUMBER_WORDS.search(literal) or "{" in literal or "}" in literal):
        raise ValueError("Narrative must cite structured facts instead of supplying numbers")
    if sentence and (not literal.endswith(".") or re.search(r"[.!?]", literal[:-1])):
        raise ValueError("Each summary entry must be a single sentence")

    def replace(match):
        if match[1] not in facts:
            raise ValueError("Unknown or non-factual reference")
        return facts[match[1]]

    return _REFERENCE.sub(replace, template)


def _unique_indices(items, attribute, length):
    indices = [getattr(item, attribute) for item in items]
    if len(set(indices)) != len(indices) or any(i >= length for i in indices):
        raise ValueError("Duplicate or out-of-range proposal index")


def _apply(report, series, proposal, facts):
    """Build a copy atomically; no partial LLM changes escape failed validation."""
    _unique_indices(proposal.window_priorities, "window_index", len(report.windows))
    _unique_indices(proposal.data_quality_explanations, "issue_index", len(report.data_quality))
    result = report.model_copy(deep=True)
    result.summary = " ".join(_render(s, facts, sentence=True) for s in proposal.summary_sentences)
    scores = {p.window_index: p.impact for p in proposal.window_priorities}
    result.windows = [w for i, w in sorted(enumerate(result.windows), key=lambda pair: -scores.get(pair[0], 0))]
    for item in proposal.data_quality_explanations:
        issue = result.data_quality[item.issue_index]
        issue.detail += " " + _render(item.explanation, facts)
    if proposal.extra_condition is not None:
        extra = proposal.extra_condition
        if extra.forecast_index >= len(series):
            raise ValueError("Planning condition must reference the fetched forecast")
        snapshot = series[extra.forecast_index]
        extra_facts = _facts(snapshot.model_dump(), f"forecast/{extra.forecast_index}")
        why = _render(extra.why, facts | extra_facts)
        if not any(p.environment == snapshot for p in result.planning_conditions):
            result.planning_conditions.append(PlanningCondition(
                label="Additional forecast condition", environment=snapshot.model_copy(deep=True), why=why,
            ))
    return result


async def assess(req: IntakeRequest, tk: PhysicsToolkit) -> IntakeReport:
    report, series = await core.assess_with_forecast(req, tk)
    report = report.model_copy(update={"backend": "real"}, deep=True)
    try:
        model = llm.get_llm()
    except llm.LLMNotConfigured:
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
        logger.warning("Intake narration unavailable (%s); retaining deterministic report", type(exc).__name__)
    else:
        try:
            if reply.tool_uses or reply.stop_reason not in ("stop", "completed"):
                raise ValueError("Narration must be a complete text response without tool calls")
            proposal = NarrativeProposal.model_validate_json(reply.text)
            report = _apply(report, series, proposal, facts)
        except ValueError:
            logger.warning("Intake narration rejected by guardrails; retaining deterministic report")
    REPORTS[report.report_id] = report
    return report
