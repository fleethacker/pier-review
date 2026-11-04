"""Risk engine schemas (module M5): Monte Carlo exceedance, forecast timeline, live alerts."""

from datetime import datetime

from pydantic import Field

from .common import Envelope, Model, Severity, Status
from .environment import EnvironmentSnapshot
from .mooring import AnalyzeRequest


class ExceedanceRequest(AnalyzeRequest):
    horizon_hours: float = Field(default=6, gt=0, le=72)
    n_samples: int = Field(default=2000, ge=10, le=20000)
    seed: int | None = None
    gust_dynamic_factor: float = Field(default=1.0, ge=1.0, le=2.0, description="Phase 1 stand-in for gust dynamics.")


class ElementRisk(Model):
    element_id: str
    p_exceed_wll: float = Field(ge=0, le=1)
    p_exceed_mbs: float = Field(ge=0, le=1)
    tension_p50_lbf: float
    tension_p95_lbf: float


class ExceedanceResult(Model):
    n_samples: int
    p_any_exceeds_wll: float = Field(ge=0, le=1)
    p_any_exceeds_mbs: float = Field(ge=0, le=1)
    elements: list[ElementRisk]
    governing_element: str


class ExceedanceResponse(Envelope[ExceedanceResult]):
    pass


class TimelineRequest(AnalyzeRequest):
    forecast_hours: int = Field(default=48, ge=1, le=120)
    step_min: int = Field(default=30, ge=6, le=180)


class TimelineStep(Model):
    valid_at_utc: datetime
    status: Status
    wind_speed_kt: float
    wind_gust_kt: float
    p_any_exceeds_wll: float
    governing_element: str


class TimelineResult(Model):
    steps: list[TimelineStep]
    first_amber_utc: datetime | None
    first_red_utc: datetime | None
    recommended_actions: list[str]


class TimelineResponse(Envelope[TimelineResult]):
    pass


class Alert(Model):
    """Message on WS /ws/alerts."""

    alert_id: str
    at_utc: datetime
    severity: Severity
    element_id: str | None
    message: str
    env: EnvironmentSnapshot
    limit_wind_kt: float | None = None
