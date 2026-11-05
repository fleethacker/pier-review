"""Safety/Brief agent schemas: plan review, gust warnings and the Mooring Evolution Safety Sheet (M10)."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from mooring.core.schemas import (
    EnvironmentSnapshot,
    Finding,
    Model,
    MooringServiceType,
    PierFittingResult,
    Provenance,
    SequenceStep,
    Severity,
    SideTo,
    Status,
    TugPlanResult,
    Validity,
)

from ..planner.schemas import RationaleItem

# ---------- Review ----------


class SafetyReviewRequest(Model):
    plan_id: str
    intake_report_id: str | None = Field(default=None, description="Add this report's conditions to the original intake conditions; neither report is discarded.")
    target_margin_pct_wll: float = Field(default=80, gt=0, le=100)


class CheckResult(Model):
    check_id: str = Field(examples=["CITES-IN-LEDGER"])
    title: str
    passed: bool
    severity: Severity = Field(description="Severity when the check fails (INFO when it passes).")
    detail: str
    cites: list[str] = Field(default_factory=list)


class Thresholds(Model):
    """Model-computed gust limits; breaking remains unavailable without a separate validated model."""

    wind_rel_deg: float | None = Field(description="Worst relative wind direction from the limit envelope.")
    governing_element: str | None
    limit_wll_gust_kt: float | None = Field(description="Gust at which the first element reaches its working limit.")
    limit_breaking_gust_kt: float | None = Field(
        description="Unavailable unless a separate validated breaking-limit model establishes it; legacy values were estimates.")
    forecast_max_gust_kt: float
    cites: list[str]
    directions: list["DirectionalThreshold"] = Field(default_factory=list)


class DirectionalThreshold(Model):
    """Direction-specific limits. Breaking gust is an estimate, not a direct solver result."""

    wind_rel_deg: float
    governing_element: str | None
    limit_wll_gust_kt: float | None
    estimated_breaking_gust_kt: float | None


class SafetyReview(Model):
    wire_omitted_defaults = {"validity": None}
    validity: Validity | None = None
    review_id: str
    plan_id: str
    created_at_utc: datetime
    verdict: Literal["ready_for_signature", "revise", "reject"]
    status: Status
    checks: list[CheckResult]
    thresholds: Thresholds
    summary: str
    brief: str | None = None
    summary_source: Literal["llm", "deterministic"] | None = None
    narration_note: str | None = None
    intake_report_id: str | None = None
    backend: Literal["mock", "real"]


class GustWarning(Model):
    """SSE `warning` event on GET /safety/watch/{plan_id}."""

    warning_id: str
    plan_id: str
    at_utc: datetime
    severity: Severity
    gust_kt: float
    wind_from_true_deg: float
    pct_of_wll_limit: float | None
    pct_of_breaking_limit: float | None
    element_id: str | None
    message: str


# ---------- Safety sheet ----------


class SafetySheetCreate(Model):
    plan_id: str
    review_id: str | None = Field(default=None, description="Use this review; one is run if omitted.")


class SafetySheetCreated(Model):
    sheet_id: str
    version: int


class SheetHeader(Model):
    ship_class_id: str
    ship_name: str | None = None
    berth_id: str
    side_to: SideTo
    evolution: Literal["moor", "berthing", "storm_prep", "unmoor"]
    planned_utc: datetime | None = None


class SheetEnvironment(Model):
    observed: EnvironmentSnapshot
    forecast_summary: str
    mst: MooringServiceType


class SheetLineRow(Model):
    line_number: int
    role: str
    spec_id: str
    parts: int
    ship_fitting_id: str
    pier_fitting_id: str
    tension_lbf: float
    pct_wll: float
    status: Status


class GoNoGo(Model):
    condition: str = Field(examples=["Sustained wind above 30 kt"])
    action: str = Field(examples=["Double up lines 2 and 5"])


class Approval(Model):
    role: Literal["pilot", "first_lt", "co"]
    name: str
    decision: Literal["approve", "reject"]
    comment: str | None = None
    at_utc: datetime


class ApprovalCreate(Model):
    role: Literal["pilot", "first_lt", "co"]
    name: str
    decision: Literal["approve", "reject"]
    comment: str | None = None


class SafetySheet(Model):
    wire_omitted_defaults = {"validity": None}
    validity: Validity | None = None
    sheet_id: str
    version: int
    plan_id: str
    review_id: str | None = None
    locked: bool = Field(description="True once any approval is recorded; changes create a new version.")
    status: Status
    header: SheetHeader
    environment: SheetEnvironment
    line_plan: list[SheetLineRow]
    fitting_utilization: list[PierFittingResult]
    tug_plan: TugPlanResult | None
    sequence: list[SequenceStep]
    sequence_review_status: str | None = Field(
        default=None, description="Review state of the line-handling sequence from the modeling service; 'draft_unreviewed' until a deck officer or pilot reviews it.")
    sequence_limitations: list[str] = Field(default_factory=list)
    go_no_go: list[GoNoGo]
    brief: str | None = None
    directional_thresholds: list[DirectionalThreshold] = Field(default_factory=list)
    warnings: list[Finding]
    rationale: list[RationaleItem]
    assumptions: list[str]
    cited_result_ids: list[str]
    sources: list[Provenance]
    approvals: list[Approval]
    disclaimer: str
