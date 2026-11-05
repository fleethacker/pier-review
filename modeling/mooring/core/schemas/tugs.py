"""Tug planner schemas (module M6): holding tugs, berthing tugs, berthing windows."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator, model_validator

from .common import Envelope, Model, SideTo
from .environment import EnvironmentSnapshot
from .mooring import AnalyzeRequest
from .plans import TugAssignment


def _unique_available_tugs(value: list[str] | None) -> list[str] | None:
    if value is not None and len(value) != len(set(value)):
        raise ValueError("available_tug_ids must be unique; one tug cannot be allocated twice")
    return value


AvailableTugIds = Annotated[list[str] | None, AfterValidator(_unique_available_tugs)]
FLEET_DESCRIPTION = "Unique available tug IDs. Omitted/null uses the catalog fleet; an empty list means no available tugs."


class BerthingTugRequest(Model):
    ship_class_id: str = Field(examples=["DDG-51-FIIA"])
    loading: str = "full_load"
    berth_id: str
    side_to: SideTo
    environment: EnvironmentSnapshot
    margin: float = Field(default=0.25, ge=0, le=1, description="Added to the gust load (pilot practice: 20-25%).")
    available_tug_ids: AvailableTugIds = Field(default=None, description=FLEET_DESCRIPTION)


class HoldTugRequest(AnalyzeRequest):
    margin: float = Field(default=0.25, ge=0, le=1)
    available_tug_ids: AvailableTugIds = Field(default=None, description=FLEET_DESCRIPTION)


class PushPointForce(Model):
    push_point_id: str
    force_lbf: float
    mode: Literal["push", "pull"]


class WrenchLbf(Model):
    """Force and yaw moment in the ship frame (+x forward, +y to port, yaw CCW) about midships."""

    fx_lbf: float
    fy_lbf: float
    mz_ftlbf: float


class TugPlanResult(Model):
    wire_omitted_defaults = {"required_wrench": None, "delivered_wrench": None, "residual_wrench": None, "binding_constraints": [], "ratings_basis": None, "assisted_max_pct_wll": None, "assisted_result_id": None}

    required_lateral_lbf: float
    required_by_point: list[PushPointForce]
    assignments: list[TugAssignment]
    total_bollard_pull_lbf: float
    total_power_hp: float
    recommended_tug_count: int
    feasible: bool
    rationale: list[str]
    required_wrench: WrenchLbf | None = Field(default=None, description="Wrench the tugs must supply (after margin).")
    delivered_wrench: WrenchLbf | None = None
    residual_wrench: WrenchLbf | None = Field(default=None, description="required - delivered. Feasible only when every component is within tolerance.")
    binding_constraints: list[str] = Field(default_factory=list, description="Rating, direction or hull-point limits that are active.")
    ratings_basis: str | None = Field(default=None, description="Where the pull ratings come from (catalog estimate, not certified).")
    assisted_max_pct_wll: float | None = Field(default=None, description="Holding plans: highest line/fitting utilization from a fresh equilibrium solve with the tugs applied.")
    assisted_result_id: str | None = Field(default=None, description="Holding plans: the analysis envelope of that fresh solve.")


class TugPlanResponse(Envelope[TugPlanResult]):
    pass


class BerthingWindowRequest(Model):
    wire_omitted_defaults = {"available_tug_ids": None, "margin": 0.25, "step_min": 6, "min_duration_min": 0.0}

    berth_id: str
    ship_class_id: str
    loading: str = "full_load"
    side_to: SideTo = "starboard"
    from_utc: datetime = Field(description="Timezone-aware window start; normalized to UTC for elapsed-time sampling.")
    to_utc: datetime = Field(description="Timezone-aware window end, at or after start; normalized to UTC.")
    max_current_kt: float = Field(default=0.5, ge=0)
    max_gust_kt: float | None = Field(default=None, ge=0)
    available_tug_ids: AvailableTugIds = Field(default=None, description=FLEET_DESCRIPTION)
    margin: float = Field(default=0.25, ge=0, le=1)
    step_min: int = Field(default=6, ge=1, le=60, description="Coarse sampling interval; threshold crossings between samples are refined to 1 min.")
    min_duration_min: float = Field(default=0.0, ge=0, description="Windows shorter than this are dropped.")

    @field_validator("from_utc", "to_utc")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Berthing-window bounds must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered_window(self):
        if self.to_utc < self.from_utc:
            raise ValueError("to_utc cannot precede from_utc")
        return self


class BerthingWindow(Model):
    start_utc: datetime = Field(description="First feasible minute (inclusive).")
    end_utc: datetime = Field(description="Last feasible minute (inclusive).")
    max_current_kt: float
    max_gust_kt: float
    required_power_hp: float


class BerthingWindowsResult(Model):
    wire_omitted_defaults = {"forecast_coverage_end_utc": None, "gaps": [], "resolution_note": None}

    windows: list[BerthingWindow]
    forecast_coverage_end_utc: datetime | None = Field(default=None, description="Last time with forecast data; later times are gaps, never windows.")
    gaps: list[str] = Field(default_factory=list)
    resolution_note: str | None = None


class BerthingWindowsResponse(Envelope[BerthingWindowsResult]):
    pass


class HorsepowerPlacement(Model):
    tug_id: str
    push_point_id: str
    mode: Literal["push", "pull"]
    force_lbf: float
    capacity_lbf: float = Field(description="min(catalog bollard pull in this mode x efficiency, push-point rating).")
    utilization: float = Field(description="force_lbf / capacity_lbf.")
    power_hp: float = Field(description="Catalog horsepower (seed/synthetic unless published); never converted to force.")


class HorsepowerPlan(Model):
    """P5: minimum-total-horsepower, placement-feasible tug assignment for a required ship-frame wrench."""

    objective: str = "minimize_total_horsepower"
    feasible: bool
    total_power_hp: float = 0.0
    tug_count: int = 0
    placements: list[HorsepowerPlacement] = Field(default_factory=list)
    required_wrench: WrenchLbf
    delivered_wrench: WrenchLbf | None = None
    residual_wrench: WrenchLbf | None = None
    load_scale_margin: float | None = Field(default=None, description="Largest factor s such that s x required wrench is still placement-feasible with the chosen tugs; >=1 when feasible.")
    fleet_scale_margin: float | None = Field(default=None, description="Same factor for the whole available fleet (best case); <1 explains infeasibility.")
    candidates_evaluated: int = 0
    infeasibility_reasons: list[str] = Field(default_factory=list)
    tie_break: str = "lowest total hp, then fewest tugs, then lowest total force, then lexicographic (tug_id, push_point_id)"
    validity: str = Field(default="limited", description="Validity limited where fleet horsepower/bollard-pull data are assumed (seed/synthetic).")
    assumptions: list[str] = Field(default_factory=list)
