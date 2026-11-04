"""Environment schemas (module M1). Every data source is normalized into EnvironmentSnapshot."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from .common import Model, Provenance

EnvSourceKind = Literal["live", "replay", "forecast", "scenario", "ship_sensor", "mock"]


def _now() -> datetime:
    return datetime.now(UTC)


class StationQuality(Model):
    station_id: str
    age_s: float = Field(ge=0, description="Age of the observation when the snapshot was built.")
    flags: list[str] = Field(default_factory=list)


class EnvironmentSnapshot(Model):
    """Wind, current and water level at one time. Wind is normalized to a 10 m, 1-minute sustained speed."""

    valid_at_utc: datetime = Field(default_factory=_now)
    source: EnvSourceKind = "scenario"
    wind_speed_kt: float = Field(ge=0, description="Sustained wind, 10 m height, 1-minute average.")
    wind_gust_kt: float = Field(ge=0)
    wind_from_true_deg: float = Field(ge=0, lt=360, description="Direction the wind blows FROM.")
    current_speed_kt: float = Field(ge=0)
    current_set_true_deg: float = Field(ge=0, lt=360, description="Direction the current flows TOWARD.")
    water_level_mllw_ft: float
    tide_stage: Literal["flood", "ebb", "slack"] | None = None
    air_density_kgm3: float = Field(default=1.225, gt=0)
    water_density_kgm3: float = Field(default=1020.0, gt=0, description="Brackish Chesapeake default.")
    wind_rel_ship_deg: float | None = Field(
        default=None, description="Relative bearing the wind comes from (0 = bow, 90 = starboard beam)."
    )
    current_rel_ship_deg: float | None = Field(
        default=None, description="Relative bearing the current flows toward (0 = bow, 90 = starboard beam)."
    )
    quality: list[StationQuality] = Field(default_factory=list)


class ForecastSeries(Model):
    berth_id: str
    step_min: int
    series: list[EnvironmentSnapshot]


class HistorySeries(Model):
    station_id: str
    start_utc: datetime
    end_utc: datetime
    series: list[EnvironmentSnapshot]


class EnvScenarioCreate(Model):
    """A synthetic environment for what-if runs and repeatable demos."""

    name: str = Field(examples=["MST II design condition"])
    kind: Literal["steady", "ramp", "replay"]
    wind_speed_kt: float = Field(default=0, ge=0)
    wind_gust_kt: float | None = Field(default=None, ge=0, description="Defaults to wind_speed_kt.")
    wind_from_true_deg: float = Field(default=0, ge=0, lt=360)
    current_speed_kt: float = Field(default=0, ge=0)
    current_set_true_deg: float = Field(default=0, ge=0, lt=360)
    water_level_mllw_ft: float = 0.0
    ramp_to_wind_kt: float | None = Field(default=None, description="kind='ramp': wind at the end of the ramp.")
    ramp_minutes: float | None = Field(default=None, gt=0)
    replay_start_utc: datetime | None = Field(default=None, description="kind='replay': historical window start.")
    replay_end_utc: datetime | None = None


class EnvScenario(EnvScenarioCreate):
    env_scenario_id: str
    created_at_utc: datetime


class Distribution(Model):
    dist: str = Field(examples=["lognormal"])
    params: dict[str, float]


class GustSector(Model):
    from_deg: float
    to_deg: float
    gust_factor: Distribution = Field(description="Distribution of gust / sustained wind.")
    dir_sigma_deg: float = Field(description="Standard deviation of wind direction scatter.")


class FitWindow(Model):
    start_utc: datetime
    end_utc: datetime
    n: int


class GustModel(Model):
    station_id: str
    sectors: list[GustSector]
    current_residual_sigma_kt: float = Field(description="Std. dev. of observed minus predicted current.")
    fitted_on: FitWindow
    provenance: Provenance
