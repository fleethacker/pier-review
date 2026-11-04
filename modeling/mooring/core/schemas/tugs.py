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


class TugPlanResult(Model):
    required_lateral_lbf: float
    required_by_point: list[PushPointForce]
    assignments: list[TugAssignment]
    total_bollard_pull_lbf: float
    total_power_hp: float
    recommended_tug_count: int
    feasible: bool
    rationale: list[str]


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


class BerthingWindow(Model):
    start_utc: datetime
    end_utc: datetime
    max_current_kt: float
    max_gust_kt: float
    required_power_hp: float


class BerthingWindowsResult(Model):
    windows: list[BerthingWindow]


class BerthingWindowsResponse(Envelope[BerthingWindowsResult]):
    pass
