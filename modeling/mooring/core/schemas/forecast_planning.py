"""Advance docking assessment; times and coverage are explicit and replayable."""
from datetime import UTC, timedelta
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .common import Envelope, Model, MooringServiceType, Validity
from .environment import EnvironmentSnapshot
from .plans import MooringConfig, TugAssignment


class ForecastBinding(Model):
    """Explicit input selection. Provider acquisition remains outside the planner."""

    wire_omitted_defaults = {"source_id": None, "env_scenario_id": None, "revision": None,
                            "expected_content_hash": None, "sample_from_utc": None, "sample_to_utc": None}
    source: Literal['supplied', 'scenario'] = 'supplied'
    source_id: str | None = Field(default=None, min_length=1,
        description="Caller-declared dataset/product identity; not proof of provider authenticity.")
    env_scenario_id: str | None = Field(default=None, min_length=1)
    revision: str | None = Field(default=None, min_length=1,
        description="Declared provider/scenario revision. Content is hashed independently even when this is unchanged.")
    expected_content_hash: str | None = Field(default=None, pattern=r'^sha256:[0-9a-f]{64}$',
        description="Optional pin: reject different content instead of silently evaluating a changed revision.")
    sample_from_utc: AwareDatetime | None = Field(default=None,
        description="Scenario-only sampling window retained when rechecking a selected operation from a wider original series.")
    sample_to_utc: AwareDatetime | None = None

    @field_validator('sample_from_utc', 'sample_to_utc')
    @classmethod
    def utc_sampling(cls, value):
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode='after')
    def selection(self):
        if (self.source == 'scenario') != (self.env_scenario_id is not None):
            raise ValueError('Scenario source requires env_scenario_id; supplied source cannot select a scenario')
        if (self.sample_from_utc is None) != (self.sample_to_utc is None):
            raise ValueError('Scenario sampling window requires both endpoints')
        if self.sample_from_utc is not None:
            if self.source != 'scenario':
                raise ValueError('Explicit sampling windows apply only to scenario sources')
            if not self.sample_from_utc < self.sample_to_utc <= self.sample_from_utc + timedelta(hours=120):
                raise ValueError('Scenario sampling window must be increasing and at most 120 hours')
        return self


def _sampling_window(binding, as_of, start, end):
    if binding is not None and binding.sample_from_utc is not None:
        if binding.sample_from_utc > start or binding.sample_to_utc < end:
            raise ValueError('Scenario sampling window must cover the requested operation')
        if binding.sample_from_utc < as_of-timedelta(hours=120) or binding.sample_to_utc > as_of+timedelta(hours=120):
            raise ValueError('Retained scenario samples must be within 120 hours of as_of_utc')


class ForecastResolutionManifest(Model):
    """Immutable identity of the exact series and the requested temporal binding."""

    wire_omitted_defaults = {"source_id": None, "env_scenario_id": None}
    source: Literal['supplied', 'scenario']
    source_id: str | None = None
    env_scenario_id: str | None = None
    revision: str
    content_hash: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    binding_hash: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    as_of_utc: AwareDatetime
    from_utc: AwareDatetime
    to_utc: AwareDatetime
    max_gap_min: int = Field(ge=1, le=180)


class ForecastResolveRequest(Model):
    wire_omitted_defaults = {"forecast": None, "forecast_binding": None}
    berth_id: str
    as_of_utc: AwareDatetime
    from_utc: AwareDatetime
    to_utc: AwareDatetime
    max_gap_min: int = Field(default=60, ge=1, le=180)
    step_min: int = Field(default=30, ge=10, le=180,
        description="Sampling interval for an explicitly selected scenario; supplied series retain every knot.")
    forecast: list[EnvironmentSnapshot] | None = Field(default=None, min_length=2, max_length=721)
    forecast_binding: ForecastBinding | None = None

    @field_validator('as_of_utc', 'from_utc', 'to_utc')
    @classmethod
    def utc_schedule(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode='after')
    def selection_and_horizon(self):
        if self.from_utc < self.as_of_utc or self.to_utc <= self.from_utc:
            raise ValueError('Forecast horizon must start at/after as_of_utc and end after its start')
        if self.to_utc > self.as_of_utc + timedelta(hours=120):
            raise ValueError('Forecast horizon must end within 120 hours of as_of_utc')
        scenario = self.forecast_binding is not None and self.forecast_binding.source == 'scenario'
        if scenario == (self.forecast is not None):
            raise ValueError('Supply exactly one forecast series or a scenario binding')
        _sampling_window(self.forecast_binding, self.as_of_utc, self.from_utc, self.to_utc)
        return self


class ForecastResolvedResult(Model):
    berth_id: str
    forecast_manifest: ForecastResolutionManifest
    series: list[EnvironmentSnapshot]
    coverage_complete: bool
    problems: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ForecastResolvedResponse(Envelope[ForecastResolvedResult]):
    pass


class ForecastDockingRequest(Model):
    wire_omitted_defaults = {"allow_short_lead": False, "forecast_binding": None,
                            "forecast_step_min": 30, "forecast": None,
                            "installed_at_water_level_mllw_ft": None}

    installed_at_water_level_mllw_ft: float | None = Field(default=None,
        description="Preserve an existing installation tide during explicit reassessment; omitted means install at each candidate arrival's tide.")

    allow_short_lead: bool = Field(default=False,
        description="Explicitly permit reassessment less than 24 hours before arrival. Arrival cannot precede as_of_utc; all forecast provenance/coverage gates remain. Default retains the advance-planning lead requirement.")
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
    forecast: list[EnvironmentSnapshot] | None = Field(default=None, min_length=2, max_length=721)
    forecast_binding: ForecastBinding | None = None
    forecast_step_min: int = Field(default=30, ge=10, le=180,
        description="Sampling interval only for an explicitly selected environment scenario.")
    max_gap_min: int = Field(default=60, ge=1, le=180,
        description='Maximum covered interval between snapshots; this is a sampling assumption, not a guarantee against sub-sample peaks.')
    target_pct_wll: float = Field(default=80, gt=0, le=100)
    max_evaluations: int = Field(default=500, ge=1, le=2000)
    optimize_lines: bool = Field(default=False, description='Search a common line plan across supplied conditions before assessing arrival windows.')
    search_budget: int = Field(default=100, ge=1, le=500)

    @field_validator('as_of_utc', 'arrival_from_utc', 'arrival_to_utc')
    @classmethod
    def utc_schedule(cls, value):
        # Arithmetic in a named local zone uses wall time across DST transitions.
        return value.astimezone(UTC)

    @model_validator(mode='after')
    def times(self):
        scenario = self.forecast_binding is not None and self.forecast_binding.source == 'scenario'
        if scenario == (self.forecast is not None):
            raise ValueError('Supply exactly one forecast series or a scenario binding')
        if self.allow_short_lead and self.arrival_from_utc < self.as_of_utc:
            raise ValueError('Reassessment arrival cannot precede as_of_utc')
        if not self.allow_short_lead and self.arrival_from_utc < self.as_of_utc + timedelta(hours=24):
            raise ValueError('Advance docking planning requires arrival at least 24 hours after as_of_utc')
        if self.arrival_to_utc < self.arrival_from_utc:
            raise ValueError('arrival_to_utc precedes arrival_from_utc')
        if self.arrival_to_utc + timedelta(hours=self.operation_hours + self.holding_hours) > self.as_of_utc + timedelta(hours=120):
            raise ValueError('Docking and holding must end within the 120-hour planning horizon')
        _sampling_window(self.forecast_binding, self.as_of_utc, self.arrival_from_utc,
                         self.arrival_to_utc + timedelta(hours=self.operation_hours+self.holding_hours))
        if self.forecast is None:
            return self
        dates = [s.valid_at_utc for s in self.forecast]
        if any(t.tzinfo is None or t.utcoffset() is None for t in dates):
            raise ValueError('Forecast timestamps must be timezone-aware')
        # Copy snapshots so validation cannot mutate a caller's input objects.
        self.forecast = [s.model_copy(update={'valid_at_utc': s.valid_at_utc.astimezone(UTC)})
                         for s in self.forecast]
        dates = [s.valid_at_utc for s in self.forecast]
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
    wire_omitted_defaults = {"selected_config": None, "installed_at_water_level_mllw_ft": None, "retrieved_at_utc": [],
                            "forecast_manifest": None, "result_hash": None}
    forecast_manifest: ForecastResolutionManifest | None = None
    result_hash: str | None = Field(default=None, pattern=r'^sha256:[0-9a-f]{64}$',
        description="Hash of the semantic assessment, excluding newly allocated result IDs and execution timestamps.")
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


class ForecastRecheckRequest(Model):
    wire_omitted_defaults = {"forecast": None, "forecast_binding": None}
    prior_result_id: str = Field(min_length=1)
    as_of_utc: AwareDatetime
    forecast: list[EnvironmentSnapshot] | None = Field(default=None, min_length=2, max_length=721)
    forecast_binding: ForecastBinding | None = None

    @field_validator('as_of_utc')
    @classmethod
    def utc_cutoff(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode='after')
    def selection(self):
        scenario = self.forecast_binding is not None and self.forecast_binding.source == 'scenario'
        if scenario == (self.forecast is not None):
            raise ValueError('Supply exactly one forecast series or a scenario binding')
        return self


class ForecastRecheckResult(Model):
    wire_omitted_defaults = {"previous_forecast_manifest": None, "current_forecast_manifest": None,
                            "reassessment_request": None, "installed_at_water_level_mllw_ft": None}
    state: Literal['unchanged', 'recheck_required', 'unavailable']
    prior_result_id: str
    previous_forecast_manifest: ForecastResolutionManifest | None = None
    current_forecast_manifest: ForecastResolutionManifest | None = None
    reasons: list[str]
    reassessment_request: ForecastDockingRequest | None = Field(default=None,
        description="Suggested explicit new calculation preserving the installation. This comparison neither runs it nor transfers approval.")
    installed_at_water_level_mllw_ft: float | None = None


class ForecastRecheckResponse(Envelope[ForecastRecheckResult]):
    pass
