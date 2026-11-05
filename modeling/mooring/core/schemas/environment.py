"""Environment schemas (module M1). Every data source is normalized into EnvironmentSnapshot."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .common import Model, Provenance

EnvSourceKind = Literal["live", "replay", "forecast", "scenario", "ship_sensor", "mock"]
EnvSourceMode = Literal["mock", "coops", "replay", "auto"]
EnvironmentComponentKind = Literal["wind", "current", "water_level", "forecast", "waves"]
EnvironmentComponentState = Literal["live", "replay", "prediction", "mock", "unavailable"]


def _now() -> datetime:
    return datetime.now(UTC)


class EnvironmentComponentProvenance(Model):
    """Provider timing for one forcing component; retrieval is not provider issuance."""

    wire_omitted_defaults = {"issued_at_utc": None, "retrieved_at_utc": None,
                            "valid_from_utc": None, "valid_to_utc": None,
                            "quality": "unknown", "limitations": []}
    component: Literal["wind", "current", "water_level"]
    source: str = Field(min_length=1, description="Provider, station/bin or grid product that supplied this component.")
    basis: Literal["observation", "prediction", "scenario"]
    issued_at_utc: AwareDatetime | None = Field(default=None,
        description="Actual provider issuance, when supplied; never substitute retrieval time.")
    retrieved_at_utc: AwareDatetime | None = Field(default=None,
        description="Recorded retrieval completion. If issuance is unknown, this proves only availability by this time, not forecast age or accuracy.")
    valid_from_utc: AwareDatetime | None = None
    valid_to_utc: AwareDatetime | None = None
    quality: Literal["good", "suspect", "poor", "unknown"] = "unknown"
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _timing(self):
        if self.valid_from_utc and self.valid_to_utc and self.valid_to_utc.astimezone(UTC) < self.valid_from_utc.astimezone(UTC):
            raise ValueError("component valid_to_utc is before valid_from_utc")
        if self.issued_at_utc and self.retrieved_at_utc and self.issued_at_utc.astimezone(UTC) > self.retrieved_at_utc.astimezone(UTC):
            raise ValueError("component issuance is after its recorded retrieval")
        return self


class EnvironmentMetadata(Model):
    """Where an environment snapshot came from and how to read its numbers (S00a).

    Optional: absent means the basis is undocumented, and the legacy meaning applies (wind is a 10 m, 1-minute
    sustained speed; the gust is assumed to be 30 s). Supplying metadata never changes the numerical values.
    """

    wire_omitted_defaults = {"components": []}
    components: list[EnvironmentComponentProvenance] = Field(default_factory=list, max_length=3,
        description="Optional per-component provenance for composed snapshots. Advance public forecasts require wind, current and water level when this is supplied.")

    basis: Literal["observation", "prediction", "scenario"] = Field(
        description="Measured, forecast/model output, or synthetic what-if input."
    )
    source: str | None = Field(default=None, description="Provider or station, e.g. 'NOAA CO-OPS 8638610'.", examples=["NOAA CO-OPS 8638610"])
    issued_at_utc: AwareDatetime | None = Field(default=None, description="When the observation or forecast was produced.")
    valid_from_utc: AwareDatetime | None = None
    valid_to_utc: AwareDatetime | None = None
    wind_averaging_s: float | None = Field(default=None, gt=0, description="Averaging time of wind_speed_kt.")
    gust_duration_s: float | None = Field(default=None, gt=0, description="Duration of wind_gust_kt.")
    wind_reference_height_m: float | None = Field(default=None, gt=0, description="Anemometer or model height.")
    current_depth_ft: float | None = Field(default=None, ge=0, description="Depth of the current measurement below the surface.")
    current_bin: str | None = Field(default=None, description="Instrument bin or model layer id.")
    vertical_datum: Literal["MLLW", "MSL", "NAVD88", "other"] | None = Field(
        default=None, description="Datum of water_level_mllw_ft. Its name says MLLW; any other value is a conflict."
    )
    quality: Literal["good", "suspect", "poor", "unknown"] = "unknown"
    age_s: float | None = Field(default=None, ge=0, description="Age of the newest observation when the snapshot was built.")
    original: dict[str, float | str] | None = Field(
        default=None,
        description="Provider values exactly as received, with their units in the key names, before normalization.",
    )

    @model_validator(mode="after")
    def _consistent(self):
        if len({item.component for item in self.components}) != len(self.components):
            raise ValueError("component provenance must be unique by component")
        if self.valid_from_utc and self.valid_to_utc and self.valid_to_utc.astimezone(UTC) < self.valid_from_utc.astimezone(UTC):
            raise ValueError("valid_to_utc is before valid_from_utc")
        if self.wind_averaging_s and self.gust_duration_s and self.gust_duration_s >= self.wind_averaging_s:
            raise ValueError("gust_duration_s must be shorter than wind_averaging_s")
        if self.basis == "observation" and self.age_s is None and self.issued_at_utc is None:
            raise ValueError("an observation needs age_s or issued_at_utc so freshness can be judged")
        if self.vertical_datum not in (None, "MLLW"):
            raise ValueError("water_level_mllw_ft is relative to MLLW; convert before sending other datums")
        return self


class StationQuality(Model):
    station_id: str
    age_s: float = Field(ge=0, description="Age of the observation when the snapshot was built.")
    flags: list[str] = Field(default_factory=list)


class EnvironmentSnapshot(Model):
    """Wind, current and water level at one time. Wind is normalized to a 10 m, 1-minute sustained speed."""

    wire_omitted_defaults = {"metadata": None}

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
    metadata: EnvironmentMetadata | None = Field(
        default=None, description="Basis, timing, averaging and datum. Absent means undocumented (legacy)."
    )


class EnvironmentComponentAvailability(Model):
    """Availability and provenance for one independently acquired component.

    This carries no environmental measurement. Missing values stay unavailable here
    instead of being represented as numeric zero in an ``EnvironmentSnapshot``.
    """

    component: EnvironmentComponentKind
    state: EnvironmentComponentState = Field(
        description="Active source state. Stale or missing data is unavailable, never silently relabeled as a prediction."
    )
    source: str | None = Field(
        default=None, description="Provider plus station/bin or grid product when known."
    )
    basis: Literal["observation", "prediction", "scenario"] | None = None
    age_s: float | None = Field(
        default=None, ge=0,
        description="Age according to age_basis. Retrieval time is never substituted for issue or valid time."
    )
    age_basis: Literal["valid_time", "issued_time"] | None = None
    issued_at_utc: AwareDatetime | None = None
    retrieved_at_utc: AwareDatetime | None = None
    valid_from_utc: AwareDatetime | None = None
    valid_to_utc: AwareDatetime | None = None
    quality: Literal["good", "suspect", "poor", "unknown"] = "unknown"
    limitations: list[str] = Field(default_factory=list)
    station_id: str | None = None
    grid_cell: str | None = None
    current_depth_ft: float | None = Field(default=None, ge=0)
    current_bin: str | None = None
    vertical_datum: Literal["MLLW", "MSL", "NAVD88", "other"] | None = None
    wind_averaging_s: float | None = Field(default=None, gt=0)
    gust_duration_s: float | None = Field(default=None, gt=0)
    wind_reference_height_m: float | None = Field(default=None, gt=0)
    reason: str | None = Field(
        default=None, description="Why this component is unavailable; required when state is unavailable."
    )

    @model_validator(mode="after")
    def _consistent(self):
        if self.state == "unavailable" and not self.reason:
            raise ValueError("an unavailable component needs a reason")
        if self.state != "unavailable" and (not self.source or self.basis is None):
            raise ValueError("an available component needs source and basis")
        if (self.age_s is None) != (self.age_basis is None):
            raise ValueError("age_s and age_basis must be supplied together")
        if self.valid_from_utc and self.valid_to_utc and self.valid_to_utc.astimezone(UTC) < self.valid_from_utc.astimezone(UTC):
            raise ValueError("component valid_to_utc is before valid_from_utc")
        if self.issued_at_utc and self.retrieved_at_utc and self.issued_at_utc.astimezone(UTC) > self.retrieved_at_utc.astimezone(UTC):
            raise ValueError("component issuance is after its recorded retrieval")
        if self.wind_averaging_s and self.gust_duration_s and self.gust_duration_s >= self.wind_averaging_s:
            raise ValueError("gust_duration_s must be shorter than wind_averaging_s")
        return self


class EnvironmentAvailability(Model):
    """Per-component status; the complete snapshot endpoint remains unchanged."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "berth_id": "NAVSTA-NORFOLK-P12-N",
        "checked_at_utc": "2026-11-05T12:00:00Z",
        "complete_snapshot_available": False,
        "components": [
            {"component": "wind", "state": "live", "source": "NOAA CO-OPS 8638614", "basis": "observation", "age_s": 360, "age_basis": "valid_time", "quality": "good", "limitations": [], "reason": None},
            {"component": "current", "state": "unavailable", "source": "NOAA CO-OPS cb0402 bin 4", "basis": "observation", "age_s": 2400, "age_basis": "valid_time", "quality": "unknown", "limitations": [], "reason": "latest observation is stale"},
            {"component": "water_level", "state": "live", "source": "NOAA CO-OPS 8638610", "basis": "observation", "age_s": 360, "age_basis": "valid_time", "quality": "good", "limitations": [], "reason": None},
            {"component": "forecast", "state": "unavailable", "source": None, "basis": None, "quality": "unknown", "limitations": [], "reason": "no composed forecast configured"},
            {"component": "waves", "state": "unavailable", "source": None, "basis": None, "quality": "unknown", "limitations": [], "reason": "no wave provider configured"},
        ],
    }]})

    berth_id: str
    checked_at_utc: AwareDatetime
    complete_snapshot_available: bool = Field(
        description="True only when aligned wind, current and water level can form the existing complete snapshot."
    )
    components: list[EnvironmentComponentAvailability] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def _complete_and_unique(self):
        by_component = {item.component: item for item in self.components}
        expected = {"wind", "current", "water_level", "forecast", "waves"}
        if set(by_component) != expected or len(by_component) != len(self.components):
            raise ValueError("availability needs exactly one row for wind, current, water_level, forecast and waves")
        complete = all(by_component[name].state != "unavailable" for name in ("wind", "current", "water_level"))
        if self.complete_snapshot_available != complete:
            raise ValueError("complete_snapshot_available must match wind/current/water-level availability")
        return self


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
    replay_start_utc: AwareDatetime | None = Field(default=None, description="kind='replay': historical window start.")
    replay_end_utc: AwareDatetime | None = None
    replay_source: Literal["synthetic", "recorded_fixture", "recorded_real"] = Field(
        default="synthetic",
        description="kind='replay': 'synthetic' generates the deterministic mock for the window (legacy); 'recorded_fixture' replays the bundled "
        "synthetic recorded-format sample (2026-03-01 12:00-13:00Z); 'recorded_real' selects the manifest-backed NOAA observation package. "
        "Recorded sources are unavailable outside their declared coverage: they are never looped or synthesized.")

    wire_omitted_defaults = {"replay_source": "synthetic"}

    @model_validator(mode="after")
    def _kind_fields(self):
        if self.replay_source != "synthetic" and (self.kind != "replay" or self.replay_end_utc is None):
            raise ValueError("replay_source other than 'synthetic' needs kind 'replay' with replay_start_utc and replay_end_utc")
        ramp = (self.ramp_to_wind_kt, self.ramp_minutes)
        replay = (self.replay_start_utc, self.replay_end_utc)
        if self.kind == "ramp" and any(v is None for v in ramp):
            raise ValueError("kind 'ramp' needs ramp_to_wind_kt and ramp_minutes")
        if self.kind != "ramp" and any(v is not None for v in ramp):
            raise ValueError("ramp_to_wind_kt and ramp_minutes apply only to kind 'ramp'")
        if self.kind != "replay" and any(v is not None for v in replay):
            raise ValueError("replay_start_utc and replay_end_utc apply only to kind 'replay'")
        if self.kind == "replay" and self.replay_start_utc is None:
            raise ValueError("kind 'replay' needs replay_start_utc")
        if self.replay_start_utc and self.replay_end_utc and self.replay_end_utc <= self.replay_start_utc:
            raise ValueError("replay_end_utc must be after replay_start_utc")
        if self.wind_gust_kt is not None and self.wind_gust_kt < self.wind_speed_kt and self.kind != "ramp":
            raise ValueError("wind_gust_kt cannot be below wind_speed_kt")
        return self


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


# ---------- Stochastic environment model metadata (S10) ----------


class HeldOutValidation(Model):
    """Calibration check on data not used for fitting."""

    n_heldout: int = Field(ge=0)
    nominal_coverage: float = Field(gt=0, lt=1)
    observed_coverage: float | None = Field(default=None, ge=0, le=1)


class UncertaintySector(Model):
    """Direction-sector gust fit; boundaries are true directions wind comes from."""

    from_deg: float = Field(ge=0, lt=360)
    to_deg: float = Field(gt=0, le=360)
    gust_factor_mu: float
    gust_factor_sigma: float = Field(ge=0)
    n_fit: int = Field(ge=2)

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.from_deg >= self.to_deg:
            raise ValueError("sector boundaries must increase; split wraparound sectors at zero")
        return self


class UncertaintyModel(Model):
    """A versioned description of what is random in the environment and how it was obtained.

    `qualification` is 'qualified' only when the minimum-data policy and held-out calibration pass. A synthetic or
    underfit model validates algorithms only: probabilities computed from it are scenario outputs, not risk estimates.
    """

    wire_omitted_defaults = {"sectors": []}

    model_id: str
    revision: str
    kind: Literal["synthetic", "fitted"]
    station_ids: list[str] = Field(default_factory=list)
    fit_start_utc: datetime | None = None
    fit_end_utc: datetime | None = None
    filters: list[str] = Field(default_factory=list, description="Quality filters applied to the fitting data.")
    gust_factor_mu: float = Field(description="Log-mean of gust / sustained wind.")
    gust_factor_sigma: float = Field(ge=0)
    sectors: list[UncertaintySector] = Field(default_factory=list, description="Exploratory direction-sector gust fits; not used by the global risk sampler or independently qualified.")
    direction_sigma_deg: float = Field(ge=0, description="Circular standard deviation of wind direction scatter.")
    current_sigma_kt: float = Field(ge=0, description="Std. dev. of observed minus predicted current speed.")
    correlation_time_min: float = Field(gt=0, description="e-folding time of the AR(1) wind and current deviations.")
    n_events: int = Field(ge=0)
    n_days: float = Field(ge=0)
    validation: HeldOutValidation | None = None
    applicability: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    qualification: Literal["qualified", "unqualified"]
    qualification_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def nonoverlapping_sectors(self):
        ordered = sorted(self.sectors, key=lambda sector: sector.from_deg)
        if any(a.to_deg > b.from_deg for a, b in zip(ordered, ordered[1:])):
            raise ValueError("uncertainty sectors must not overlap")
        return self
