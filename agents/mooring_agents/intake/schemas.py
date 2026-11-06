"""Environment/Intake agent schemas."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from mooring.core.schemas.forecast_planning import ForecastResolveRequest, ForecastResolutionManifest
from ..shared.forecast import optional_wire_schema

from mooring.core.schemas import (
    BerthingWindow,
    EnvironmentSnapshot,
    Model,
    MooringServiceType,
    Severity,
    SideTo,
)


class IntakeRequest(Model):
    wire_omitted_defaults = {"forecast_request": None}
    forecast_request: ForecastResolveRequest | None = Field(default=None, json_schema_extra=optional_wire_schema,
        description="Explicit supplied/scenario forecast selection using the canonical modeling resolver. Its interval must match horizon_hours; no default provider is substituted.")
    scenario_id: str | None = Field(default=None, description="Takes berth, ship and side from the scenario.")
    berth_id: str | None = None
    ship_class_id: str | None = None
    side_to: SideTo | None = None
    horizon_hours: float = Field(default=24, gt=0, le=120, allow_inf_nan=False)
    env_scenario_id: str | None = Field(default=None, description="Use a synthetic environment instead of live data.")

    @model_validator(mode="after")
    def bound_horizon(self):
        if self.forecast_request is None and not float(self.horizon_hours).is_integer():
            raise ValueError("Fractional horizon_hours requires an explicit forecast_request")
        if self.forecast_request is not None:
            if self.forecast_request.to_utc - self.forecast_request.from_utc != timedelta(hours=self.horizon_hours):
                raise ValueError("Forecast interval must equal horizon_hours")
            if self.env_scenario_id is not None:
                raise ValueError("Use forecast_request.forecast_binding to select the forecast scenario")
            if self.berth_id is not None and self.berth_id != self.forecast_request.berth_id:
                raise ValueError("Forecast and intake berth must match")
        return self


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
    wire_omitted_defaults = {"forecast_manifest": None, "forecast_result_id": None, "forecast_request": None}
    forecast_manifest: ForecastResolutionManifest | None = Field(default=None, json_schema_extra=optional_wire_schema)
    forecast_result_id: str | None = Field(default=None, json_schema_extra=optional_wire_schema)
    forecast_request: ForecastResolveRequest | None = Field(default=None, json_schema_extra=optional_wire_schema,
        description="Frozen explicit selection used to re-resolve the same supplied/scenario source; no public latest-revision discovery is implied.")
    report_id: str
    created_at_utc: datetime = Field(description="UTC availability cutoff; explicit forecast selections retain their resolver as_of cutoff. Assessment processing may finish later.")
    berth_id: str
    ship_class_id: str | None
    side_to: SideTo | None
    horizon_hours: float
    current: EnvironmentSnapshot
    mst: MstAssessment
    windows: list[ConcernWindow]
    planning_conditions: list[PlanningCondition] = Field(description="Worst case first. The Planner designs for these.")
    berthing_windows: list[BerthingWindow]
    data_quality: list[DataQualityIssue]
    summary: str
    summary_source: Literal["llm", "deterministic"] | None = Field(
        default=None, description="Source of narration after the code-owned risk headline; null for legacy reports.")
    narration_note: str | None = Field(default=None, description="Sanitized fallback reason; null when narration succeeds.")
    tool_call_ids: list[str] = Field(description="Ledger entries (GET /physics/calls) behind this report.")
    backend: Literal["mock", "real"]
