"""Mooring Evolution Safety Sheet schemas (module M10)."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .planner import RationaleItem
from mooring.core.schemas import Finding, Model, MooringServiceType, Provenance, SideTo, Status
from mooring.core.schemas import EnvironmentSnapshot
from mooring.core.schemas import PierFittingResult
from mooring.core.schemas import SequenceStep
from mooring.core.schemas import TugPlanResult


class SafetySheetCreate(Model):
    plan_id: str


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
    sheet_id: str
    version: int
    plan_id: str
    locked: bool = Field(description="True once any approval is recorded; changes create a new version.")
    status: Status
    header: SheetHeader
    environment: SheetEnvironment
    line_plan: list[SheetLineRow]
    fitting_utilization: list[PierFittingResult]
    tug_plan: TugPlanResult | None
    sequence: list[SequenceStep]
    go_no_go: list[GoNoGo]
    warnings: list[Finding]
    rationale: list[RationaleItem]
    assumptions: list[str]
    cited_result_ids: list[str]
    sources: list[Provenance]
    approvals: list[Approval]
    disclaimer: str
