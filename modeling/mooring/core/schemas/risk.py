"""Risk engine schemas (module M5): Monte Carlo exceedance, forecast timeline, live alerts."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from .common import Envelope, Finding, Model, Severity, Status, Validity
from .environment import EnvironmentSnapshot, UncertaintyModel
from .mooring import AnalyzeRequest


class ExceedanceRequest(AnalyzeRequest):
    wire_omitted_defaults = {**AnalyzeRequest.wire_omitted_defaults, **AnalyzeRequest.wire_omitted_defaults, "uncertainty_model_id": None, "include_horizon": False, "n_trajectories": 200, "horizon_step_min": 30}

    horizon_hours: float = Field(default=6, gt=0, le=72)
    n_samples: int = Field(default=2000, ge=10, le=20000)
    seed: int | None = None
    gust_dynamic_factor: float = Field(
        default=1.0, ge=1.0, le=2.0,
        description="Force multiplier on the wind force, applied exactly once (the wind speed is scaled by its square root). "
        "It does not touch current, and it is not a validated dynamic model.")
    uncertainty_model_id: str | None = Field(default=None, description="Defaults to the synthetic demonstration model (unqualified).")
    include_horizon: bool = Field(default=False, description="Also simulate time-correlated trajectories over horizon_hours.")
    n_trajectories: int = Field(default=200, ge=10, le=2000)
    horizon_step_min: int = Field(default=30, ge=6, le=180)


class ElementRisk(Model):
    wire_omitted_defaults = {"p_exceed_wll_ci95": None}

    element_id: str
    p_exceed_wll: float = Field(ge=0, le=1, description="Probability the element's limit (WLL, or rated capacity for fittings) is exceeded, among valid samples.")
    p_exceed_mbs: float | None = Field(default=None, ge=0, le=1, description="Lines only; null for fittings and fenders, which have no MBS.")
    tension_p50_lbf: float = Field(description="Load (lbf) median among valid samples.")
    tension_p95_lbf: float
    p_exceed_wll_ci95: list[float] | None = Field(default=None, description="95% Wilson interval on p_exceed_wll.")


class HorizonRisk(Model):
    """Probability of the event over the horizon, from correlated trajectories (not a combination of pointwise values)."""

    wire_omitted_defaults = {"p_event_bounds": None, "effective_step_min": None}

    event: str
    n_trajectories: int
    step_min: int
    horizon_hours: float
    p_event: float = Field(ge=0, le=1, description="Known exceedances / all trajectories; a lower bound when solves fail. Consult p_event_bounds.")
    p_event_ci95: list[float] = Field(description="95% Wilson interval widened over both possible outcomes of failed trajectories.")
    n_failed: int
    correlation_time_min: float
    p_event_bounds: list[float] | None = Field(default=None, description="[known exceedances / n, (known exceedances + failed) / n]. Failed trajectories are unknown, never safe.")
    effective_step_min: float | None = Field(default=None, description="Actual uniform sampling interval, no larger than step_min, including both horizon endpoints.")


class ExceedanceResult(Model):
    wire_omitted_defaults = {"n_valid": None, "n_failed": None, "p_any_ci95": None, "p_any_bounds": None, "seed": None, "uncertainty_model": None, "pointwise_only": None, "horizon": None, "error_criterion": None}

    n_samples: int = Field(description="Samples requested and run; never silently capped.")
    p_any_exceeds_wll: float = Field(ge=0, le=1, description="Instantaneous probability (pointwise), among valid samples.")
    p_any_exceeds_mbs: float = Field(ge=0, le=1)
    elements: list[ElementRisk]
    governing_element: str
    n_valid: int | None = None
    n_failed: int | None = Field(default=None, description="Samples whose equilibrium solve failed; never dropped from the accounting.")
    p_any_ci95: list[float] | None = Field(default=None, description="95% Wilson interval on p_any_exceeds_wll (valid samples).")
    p_any_bounds: list[float] | None = Field(default=None, description="[exceedances / n, (exceedances + failed) / n]: bounds if every failed sample were safe / exceeding.")
    seed: int | None = None
    uncertainty_model: UncertaintyModel | None = None
    pointwise_only: bool | None = Field(default=None, description="True when no horizon probability was computed.")
    horizon: HorizonRisk | None = None
    error_criterion: str | None = None


class ExceedanceResponse(Envelope[ExceedanceResult]):
    pass


class TimelineRequest(AnalyzeRequest):
    wire_omitted_defaults = {**AnalyzeRequest.wire_omitted_defaults, "start_utc": None, "n_samples_per_step": 0, "forecast": None}

    forecast_hours: int = Field(default=48, ge=1, le=120)
    step_min: int = Field(default=30, ge=6, le=180)
    start_utc: datetime | None = Field(default=None, description="First step time; defaults to the current hour (inject for reproducible runs).")
    n_samples_per_step: int = Field(default=0, ge=0, le=2000, description="0 = deterministic utilization only, no probability.")
    forecast: list[EnvironmentSnapshot] | None = Field(default=None, min_length=2, max_length=721,
        description="Exact supplied snapshots; all knots in the requested window are evaluated. Requires start_utc, both horizon endpoints and gaps <=60 minutes. No interpolation or provider fallback. Omitted means synthetic training forcing.")

    @model_validator(mode="after")
    def timeline_times(self):
        if self.start_utc is not None and (self.start_utc.tzinfo is None or self.start_utc.utcoffset() is None):
            raise ValueError("start_utc must be timezone-aware")
        if self.start_utc is not None:
            self.start_utc = self.start_utc.astimezone(UTC)
        if self.forecast is None:
            return self
        if self.start_utc is None:
            raise ValueError("Supplied forecast requires explicit start_utc")
        times = [s.valid_at_utc for s in self.forecast]
        if any(t.tzinfo is None or t.utcoffset() is None for t in times):
            raise ValueError("Forecast timestamps must be timezone-aware")
        self.forecast = [sample.model_copy(update={"valid_at_utc": sample.valid_at_utc.astimezone(UTC)})
                         for sample in self.forecast]
        times = [sample.valid_at_utc for sample in self.forecast]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("Forecast timestamps must be strictly increasing")
        end = self.start_utc + timedelta(hours=self.forecast_hours)
        if self.start_utc not in times or end not in times:
            raise ValueError("Supplied forecast must contain both requested horizon endpoints")
        selected = [t for t in times if self.start_utc <= t <= end]
        if any(b - a > timedelta(minutes=60) for a, b in zip(selected, selected[1:])):
            raise ValueError("Supplied forecast has a gap greater than 60 minutes")
        return self


class TimelineStep(Model):
    wire_omitted_defaults = {"max_pct_wll": None, "valid": None, "environment": None, "validity": None,
                             "n_valid": None, "n_failed": None, "p_any_bounds": None}

    valid_at_utc: datetime
    status: Status
    wind_speed_kt: float
    wind_gust_kt: float
    p_any_exceeds_wll: float | None = Field(default=None, description="Null unless n_samples_per_step > 0; pointwise, not a horizon probability.")
    governing_element: str
    max_pct_wll: float | None = None
    valid: bool | None = None
    environment: EnvironmentSnapshot | None = None
    validity: Validity | None = None
    n_valid: int | None = None
    n_failed: int | None = None
    p_any_bounds: list[float] | None = None


class TimelineResult(Model):
    wire_omitted_defaults = {"forcing_source": None}
    forcing_source: Literal["synthetic_training", "supplied"] | None = None
    steps: list[TimelineStep]
    first_amber_utc: datetime | None
    first_red_utc: datetime | None
    recommended_actions: list[str]


class TimelineResponse(Envelope[TimelineResult]):
    pass


class Alert(Model):
    """Message on WS /ws/alerts."""

    wire_omitted_defaults = {"stale": None, "provenance": None, "validity": None}

    validity: Validity | None = Field(default=None, description="Input and model validity; observations without a plan do not establish mooring adequacy.")
    alert_id: str
    at_utc: datetime
    severity: Severity
    element_id: str | None
    message: str
    env: EnvironmentSnapshot
    limit_wind_kt: float | None = None
    stale: bool | None = Field(default=None, description="True when the environment snapshot is older than the freshness limit.")
    provenance: str | None = Field(default=None, description="How the alert was computed (deterministic equilibrium vs probabilistic model).")
