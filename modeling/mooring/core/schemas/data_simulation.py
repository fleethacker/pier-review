"""Parameters for reproducible synthetic environment scenarios, not NOAA forecasts."""
from datetime import UTC

from pydantic import AwareDatetime, Field, field_validator

from .common import Model
from .environment import EnvironmentSnapshot


class SyntheticForecastRequest(Model):
    berth_id: str
    start_utc: AwareDatetime
    baseline: EnvironmentSnapshot
    duration_hours: int = Field(default=48, ge=24, le=120)
    step_min: int = Field(default=60, ge=5, le=180)
    seed: int = Field(default=0, ge=0)
    gust_peak_kt: float = Field(default=30, ge=0, description='User-specified synthetic triangular gust peak at midpoint.')
    gust_noise_sigma_kt: float = Field(default=0, ge=0, le=20)
    water_level_amplitude_ft: float = Field(default=0, ge=0, le=20)
    water_level_period_hours: float = Field(default=12, gt=0, description='Scenario oscillation period, not a fitted tidal constituent.')

    @field_validator('start_utc')
    @classmethod
    def utc_start(cls, value):
        """Scenario duration and sampling use elapsed time, including across DST."""
        return value.astimezone(UTC)
