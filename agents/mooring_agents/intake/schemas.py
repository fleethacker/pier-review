"""Environment/Intake agent schemas."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from mooring.core.schemas import (
    BerthingWindow,
    EnvironmentSnapshot,
    Model,
    MooringServiceType,
    Severity,
    SideTo,
)


class IntakeRequest(Model):
    scenario_id: str | None = Field(default=None, description="Takes berth, ship and side from the scenario.")
    berth_id: str | None = None
    ship_class_id: str | None = None
    side_to: SideTo | None = None
    horizon_hours: int = Field(default=24, ge=1, le=120)
    env_scenario_id: str | None = Field(default=None, description="Use a synthetic environment instead of live data.")


class ConcernWindow(Model):
    """A stretch of the horizon that matters for mooring."""

    start_utc: datetime
    end_utc: datetime
    kind: Literal["gust", "sustained_wind", "current", "wind_shift", "data_gap"]
    severity: Severity
    peak_value: float
    unit: Literal["kt", "deg", "min"]
    reason: str


class MstAssessment(Model):
    mst_required: MooringServiceType | Literal["exceeds_III"] = Field(
        description="Lowest Mooring Service Type whose limits cover the horizon.")
    ship_mst: Literal["II", "IIA"] | None
    exceeds_ship_mst: bool
    max_wind_kt: float
    max_broadside_current_kt: float | None
    reason: str


class PlanningCondition(Model):
    """An environment the Planner must design for, with why it was chosen."""

    label: str = Field(examples=["Worst gust in horizon"])
    environment: EnvironmentSnapshot
    why: str


class DataQualityIssue(Model):
    station_id: str
    issue: Literal["stale", "missing", "flagged", "out_of_range", "mock"]
    severity: Severity
    detail: str


class IntakeReport(Model):
    report_id: str
    created_at_utc: datetime
    berth_id: str
    ship_class_id: str | None
    side_to: SideTo | None
    horizon_hours: int
    current: EnvironmentSnapshot
    mst: MstAssessment
    windows: list[ConcernWindow]
    planning_conditions: list[PlanningCondition] = Field(description="Worst case first. The Planner designs for these.")
    berthing_windows: list[BerthingWindow]
    data_quality: list[DataQualityIssue]
    summary: str
    tool_call_ids: list[str] = Field(description="Ledger entries (GET /physics/calls) behind this report.")
    backend: Literal["mock", "real"]
