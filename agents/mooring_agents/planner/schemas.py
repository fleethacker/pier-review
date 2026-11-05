"""Planner agent schemas (M9). Progress streams as Server-Sent Events."""

from typing import Any, Literal

from pydantic import Field

from mooring.core.schemas import JobState, Model, Status
from mooring.core.schemas import MooringConfig
from mooring.core.schemas import SequenceResult
from mooring.core.schemas import TugPlanResult, TugAssignment


class AgentPlanRequest(Model):
    scenario_id: str
    intake_report_id: str | None = Field(default=None, description="Evaluate every planning condition in this report.")
    objective: Literal["moor_for_forecast", "berthing", "storm_prep"] = "moor_for_forecast"
    target_margin_pct_wll: float = Field(default=80, gt=0, le=100, description="Plan is GREEN only below this.")
    max_iterations: int = Field(default=8, ge=1, le=20)
    constraints: dict[str, Any] = Field(default_factory=dict)


class AgentPlanAccepted(Model):
    plan_id: str
    job_id: str
    events_url: str


class RationaleItem(Model):
    text: str
    cites: list[str] = Field(description="result_ids backing every number in the text.")


class AgentPlan(Model):
    wire_omitted_defaults = {"sequence_result_id": None, "installed_at_water_level_mllw_ft": None}
    plan_id: str
    scenario_id: str
    intake_report_id: str | None = None
    state: JobState
    status: Status | None = None
    config: MooringConfig | None = None
    tug_plan: TugPlanResult | None = None
    sequence: SequenceResult | None = None
    sequence_result_id: str | None = None
    installed_at_water_level_mllw_ft: float | None = Field(default=None,
        description="Common line-installation tide used across assessed conditions; absent on legacy plans.")
    analysis_result_id: str | None = None
    risk_result_id: str | None = None
    rationale: list[RationaleItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    safety_sheet_id: str | None = None
    holding_tugs: list[TugAssignment] = Field(default_factory=list, description="Assistance included in final analyses.")
    condition_analysis_result_ids: list[str] = Field(default_factory=list, description="Final analysis for each required condition.")


class AgentMessage(Model):
    text: str = Field(examples=["What if the wind backs to NW at 35 kt?"])


class AgentMessageAccepted(Model):
    message_id: str


# ---------- SSE payloads on /agent/plans/{plan_id}/events ----------


class AgentStepEvent(Model):
    """`event: step`"""

    iteration: int
    thought_summary: str
    tool: str
    result_id: str | None


class AgentProposalEvent(Model):
    """`event: proposal`"""

    config: MooringConfig
    status: Status


class AgentMessageEvent(Model):
    """`event: message` (answer to a follow-up question)"""

    message_id: str
    text: str
    cites: list[str]


class AgentDoneEvent(Model):
    """`event: done`"""

    wire_omitted_defaults = {"state": None, "error": None}
    plan_id: str
    status: Status
    state: JobState | None = None
    error: str | None = None
