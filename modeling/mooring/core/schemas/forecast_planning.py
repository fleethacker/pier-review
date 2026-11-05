"""Advance docking assessment; times and coverage are explicit and replayable."""
from datetime import timedelta
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .common import Envelope, Model, MooringServiceType, Validity
from .environment import EnvironmentSnapshot
from .plans import MooringConfig, TugAssignment


class ForecastDockingRequest(Model):
    ship_class_id: str
    loading: str = 'full_load'
    berth_id: str
    config: MooringConfig
    tugs: list[TugAssignment] = Field(default_factory=list, max_length=12)
    mst: MooringServiceType = 'II'
    as_of_utc: AwareDatetime
    arrival_from_utc: AwareDatetime
    arrival_to_utc: AwareDatetime
    arrival_step_min: int = Field(default=60, ge=15, le=360)
    operation_hours: float = Field(default=2, gt=0, le=24)
    holding_hours: float = Field(default=6, ge=0, le=48)
    forecast: list[EnvironmentSnapshot] = Field(min_length=2, max_length=721)
    max_gap_min: int = Field(default=60, ge=1, le=180,
        description='Maximum covered interval between snapshots; this is a sampling assumption, not a guarantee against sub-sample peaks.')
    target_pct_wll: float = Field(default=80, gt=0, le=100)
    max_evaluations: int = Field(default=500, ge=1, le=2000)
    optimize_lines: bool = Field(default=False, description='Search a common line plan across supplied conditions before assessing arrival windows.')
    search_budget: int = Field(default=100, ge=1, le=500)

    @model_validator(mode='after')
    def times(self):
        if self.arrival_from_utc < self.as_of_utc + timedelta(hours=24):
            raise ValueError('Advance docking planning requires arrival at least 24 hours after as_of_utc')
        if self.arrival_to_utc < self.arrival_from_utc:
            raise ValueError('arrival_to_utc precedes arrival_from_utc')
        if self.arrival_to_utc + timedelta(hours=self.operation_hours + self.holding_hours) > self.as_of_utc + timedelta(hours=120):
            raise ValueError('Docking and holding must end within the 120-hour planning horizon')
        dates = [s.valid_at_utc for s in self.forecast]
        if any(t.tzinfo is None or t.utcoffset() is None for t in dates):
            raise ValueError('Forecast timestamps must be timezone-aware')
        if any(b <= a for a, b in zip(dates, dates[1:])):
            raise ValueError('Forecast timestamps must be strictly increasing and unique')
        return self


class DockingConditionResult(Model):
    wire_omitted_defaults = {"installed_at_water_level_mllw_ft": None}
    installed_at_water_level_mllw_ft: float | None = None
    valid_at_utc: AwareDatetime
    analysis_result_id: str | None
    outcome: Literal['within_target', 'overloaded', 'invalid', 'undetermined', 'unavailable']
    max_pct_wll: float | None
    governing_element: str | None
    validity: Validity | None
    reasons: list[str] = Field(default_factory=list)


class DockingArrivalWindow(Model):
    wire_omitted_defaults = {"installed_at_water_level_mllw_ft": None}
    installed_at_water_level_mllw_ft: float | None = None
    arrival_utc: AwareDatetime
    operation_end_utc: AwareDatetime
    holding_end_utc: AwareDatetime
    outcome: Literal['supported_limited', 'within_target', 'overloaded', 'invalid', 'undetermined', 'unavailable']
    max_pct_wll: float | None
    governing_at_utc: AwareDatetime | None
    governing_element: str | None
    analysis_result_ids: list[str]
    reasons: list[str] = Field(default_factory=list)


class ForecastDockingResult(Model):
    wire_omitted_defaults = {"selected_config": None, "installed_at_water_level_mllw_ft": None, "retrieved_at_utc": []}
    selected_config: MooringConfig | None = Field(default=None,
        description="Selected arrival's configuration with modeled unstretched paid-out lengths made explicit. Reproduces the static installation assumption; not a deck-handling instruction.")
    installed_at_water_level_mllw_ft: float | None = Field(default=None,
        description="Installation water level for selected_config; unknown/absent when no supported arrival was selected.")
    as_of_utc: AwareDatetime
    forecast_start_utc: AwareDatetime
    forecast_end_utc: AwareDatetime
    issued_at_utc: list[AwareDatetime]
    retrieved_at_utc: list[AwareDatetime] = Field(default_factory=list,
        description="Recorded component retrieval times, separate from actual provider issuance.")
    sources: list[str]
    config: MooringConfig
    tugs: list[TugAssignment]
    recommendation_result_id: str | None
    selected_arrival_utc: AwareDatetime | None
    windows: list[DockingArrivalWindow]
    conditions: list[DockingConditionResult]
    evaluations: int
    complete: bool
    recheck_triggers: list[str]
    limitations: list[str]


class ForecastDockingResponse(Envelope[ForecastDockingResult]):
    pass
