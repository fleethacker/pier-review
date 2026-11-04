"""Configuration optimizer and line sequence schemas (module M7)."""

from typing import Literal

from pydantic import Field

from .common import Envelope, Model, MooringServiceType, SideTo
from .environment import EnvironmentSnapshot
from .plans import MooringConfig, MooringLine
from .refdata import LineInventoryItem


class RecommendRequest(Model):
    ship_class_id: str = Field(examples=["DDG-51-FIIA"])
    loading: str = "full_load"
    berth_id: str
    side_to: SideTo
    ship_x_ft: float | None = Field(default=None, description="Defaults to the middle of the berth face.")
    design_mst: MooringServiceType = "II"
    forecast_env: list[EnvironmentSnapshot] = Field(
        default_factory=list, description="Extra conditions to check besides the MST design condition."
    )
    available_lines: list[LineInventoryItem] = Field(default_factory=list, description="Defaults to the ship's outfit.")
    locked_lines: list[MooringLine] = Field(default_factory=list)
    excluded_fitting_ids: list[str] = Field(default_factory=list)
    max_candidates: int = Field(default=3, ge=1, le=10)


class Candidate(Model):
    config: MooringConfig
    min_margin_pct_wll: float = Field(description="Highest utilization under the design condition (lower is better).")
    limit_wind_kt_worst: float | None
    line_count: int
    analysis_result_id: str
    why: list[str]


class RecommendResult(Model):
    candidates: list[Candidate]
    design_environment: EnvironmentSnapshot


class RecommendResponse(Envelope[RecommendResult]):
    pass


class SequenceRequest(Model):
    ship_class_id: str
    berth_id: str
    config: MooringConfig
    environment: EnvironmentSnapshot
    tug_plan_result_id: str | None = None
    line_handling_crews: int = Field(default=6, ge=1)


SequenceAction = Literal["pass", "secure_pier", "hold", "take_to_power", "double_up", "tend"]


class SequenceStep(Model):
    step: int
    line_number: int | None
    action: SequenceAction
    station: Literal["forecastle", "waist", "fantail", "bridge", "pier"]
    crews: int
    trigger: str
    caution: str | None = None
    reference: str


class SequenceResult(Model):
    steps: list[SequenceStep]
    crews_required: int


class SequenceResponse(Envelope[SequenceResult]):
    pass
