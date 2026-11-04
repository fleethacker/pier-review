"""Tug planner schemas (module M6): holding tugs, berthing tugs, berthing windows."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Envelope, Model, SideTo
from .environment import EnvironmentSnapshot
from .mooring import AnalyzeRequest
from .plans import TugAssignment


class BerthingTugRequest(Model):
    ship_class_id: str = Field(examples=["DDG-51-FIIA"])
    loading: str = "full_load"
    berth_id: str
    side_to: SideTo
    environment: EnvironmentSnapshot
    margin: float = Field(default=0.25, ge=0, le=1, description="Added to the gust load (pilot practice: 20-25%).")
    available_tug_ids: list[str] | None = Field(default=None, description="Defaults to the whole fleet.")


class HoldTugRequest(AnalyzeRequest):
    margin: float = Field(default=0.25, ge=0, le=1)
    available_tug_ids: list[str] | None = None


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
    berth_id: str
    ship_class_id: str
    loading: str = "full_load"
    side_to: SideTo = "starboard"
    from_utc: datetime
    to_utc: datetime
    max_current_kt: float = Field(default=0.5, ge=0)
    max_gust_kt: float | None = Field(default=None, ge=0)
    available_tug_ids: list[str] | None = Field(default=None, description="Fleet requested for the berthing; defaults to the whole catalog fleet.")
    margin: float = Field(default=0.25, ge=0, le=1)
    step_min: int = Field(default=6, ge=1, le=60, description="Coarse sampling interval; threshold crossings between samples are refined to 1 min.")
    min_duration_min: float = Field(default=0.0, ge=0, description="Windows shorter than this are dropped.")


class BerthingWindow(Model):
    start_utc: datetime = Field(description="First feasible minute (inclusive).")
    end_utc: datetime = Field(description="Last feasible minute (inclusive).")
    max_current_kt: float
    max_gust_kt: float
    required_power_hp: float


class BerthingWindowsResult(Model):
    windows: list[BerthingWindow]
    forecast_coverage_end_utc: datetime | None = Field(default=None, description="Last time with forecast data; later times are gaps, never windows.")
    gaps: list[str] = Field(default_factory=list)
    resolution_note: str | None = None


class BerthingWindowsResponse(Envelope[BerthingWindowsResult]):
    pass
