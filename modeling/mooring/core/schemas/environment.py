"""Environment schemas (module M1). Every data source is normalized into EnvironmentSnapshot."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

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


class ForecastSourceSelection(Model):
    """Explicit acquisition source; a public request never falls through to a scenario."""

    mode: Literal["public", "scenario"]
    env_scenario_id: str | None = None

    @model_validator(mode="after")
    def _scenario_reference(self):
        if self.mode == "scenario" and not self.env_scenario_id:
            raise ValueError("scenario forecast source needs env_scenario_id")
        if self.mode == "public" and self.env_scenario_id:
            raise ValueError("public forecast source cannot include env_scenario_id")
        return self


class ComposedForecastRequest(Model):
    """Bounded forecast acquisition request with an explicit source and planning clock."""

    berth_id: str
    source: ForecastSourceSelection
    as_of_utc: AwareDatetime = Field(
        description="Availability cutoff. Every public component must be issued or recorded as retrieved by this time."
    )
    horizon_start_utc: AwareDatetime
    horizon_end_utc: AwareDatetime
    step_min: int = Field(default=60, ge=6, le=180)
    current_depth_ft: float = Field(
        ge=0, description="Required current depth below the surface; a nearby model layer is not an implicit substitute."
    )
    current_bin: str = Field(
        min_length=1, description="Requested station bin or model-layer identifier; substitutions must be reported unavailable."
    )

    @model_validator(mode="after")
    def _horizon(self):
        self.as_of_utc = self.as_of_utc.astimezone(UTC)
        self.horizon_start_utc = self.horizon_start_utc.astimezone(UTC)
        self.horizon_end_utc = self.horizon_end_utc.astimezone(UTC)
        if self.horizon_start_utc < self.as_of_utc:
            raise ValueError("forecast horizon cannot begin before as_of_utc")
        if self.horizon_end_utc <= self.horizon_start_utc:
            raise ValueError("forecast horizon end must be after its start")
        if self.horizon_end_utc > self.as_of_utc + timedelta(hours=120):
            raise ValueError("forecast horizon cannot exceed 120 hours after as_of_utc")
        return self


class WindForecastPoint(Model):
    component: Literal["wind"] = "wind"
    valid_from_utc: AwareDatetime
    valid_to_utc: AwareDatetime
    wind_speed_kt: float = Field(ge=0)
    wind_gust_kt: float | None = Field(
        default=None, ge=0, description="Missing provider gust stays null and prevents a complete load-model snapshot."
    )
    wind_from_true_deg: float = Field(ge=0, lt=360)
    original: dict[str, float | str] | None = None

    @model_validator(mode="after")
    def _interval(self):
        if self.valid_to_utc.astimezone(UTC) <= self.valid_from_utc.astimezone(UTC):
            raise ValueError("wind valid_to_utc must be after valid_from_utc")
        return self


class CurrentForecastPoint(Model):
    component: Literal["current"] = "current"
    valid_at_utc: AwareDatetime
    current_speed_kt: float = Field(ge=0)
    current_set_true_deg: float = Field(ge=0, lt=360)
    original: dict[str, float | str] | None = None


class WaterLevelForecastPoint(Model):
    component: Literal["water_level"] = "water_level"
    valid_at_utc: AwareDatetime
    water_level_mllw_ft: float
    original: dict[str, float | str] | None = None


ForecastComponentPoint = Annotated[
    WindForecastPoint | CurrentForecastPoint | WaterLevelForecastPoint,
    Field(discriminator="component"),
]


class ForecastComponentSeries(Model):
    """One independently acquired prediction series and its content digest."""

    availability: EnvironmentComponentAvailability
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of the canonical component availability and decoded point content.",
    )
    points: list[ForecastComponentPoint] = Field(default_factory=list, max_length=1201)

    @model_validator(mode="after")
    def _component_and_state(self):
        component = self.availability.component
        if component not in {"wind", "current", "water_level"}:
            raise ValueError("forecast component series supports wind, current and water_level only")
        if self.availability.state not in {"prediction", "mock", "unavailable"}:
            raise ValueError("forecast component state must be prediction, mock or unavailable")
        if self.availability.state == "unavailable":
            if self.points or self.content_sha256:
                raise ValueError("an unavailable forecast component cannot carry points or a content digest")
            return self
        expected_basis = "prediction" if self.availability.state == "prediction" else "scenario"
        if self.availability.basis != expected_basis:
            raise ValueError(f"a {self.availability.state} forecast component needs {expected_basis} basis")
        if not self.points or self.content_sha256 is None:
            raise ValueError("an available forecast component needs points and a content digest")
        if (self.availability.state == "prediction" and self.availability.issued_at_utc is None
                and self.availability.retrieved_at_utc is None):
            raise ValueError("an available forecast component needs issuance or recorded retrieval provenance")
        if any(point.component != component for point in self.points):
            raise ValueError("forecast points must match their component series")
        times = [
            point.valid_from_utc if isinstance(point, WindForecastPoint) else point.valid_at_utc
            for point in self.points
        ]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("forecast component points must be strictly increasing and unique")
        if component == "current" and self.availability.current_depth_ft is None:
            raise ValueError("a current forecast needs its selected depth")
        if component == "water_level" and self.availability.vertical_datum != "MLLW":
            raise ValueError("a water-level forecast must be normalized to MLLW")
        return self


class ComposedForecastManifest(Model):
    """Frozen, content-addressed acquisition manifest shared by every consumer."""

    schema_version: Literal["composed-forecast-v1"] = "composed-forecast-v1"
    revision: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$",
        description="SHA-256 of the canonical manifest excluding this revision field.",
    )
    request: ComposedForecastRequest
    status: Literal["complete", "partial", "unavailable"]
    components: list[ForecastComponentSeries] = Field(min_length=3, max_length=3)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _components_and_status(self):
        by_component = {item.availability.component: item for item in self.components}
        expected = {"wind", "current", "water_level"}
        if set(by_component) != expected or len(by_component) != len(self.components):
            raise ValueError("forecast manifest needs exactly one wind, current and water_level series")
        states = [item.availability.state for item in self.components]
        if self.status == "unavailable" and any(state != "unavailable" for state in states):
            raise ValueError("an unavailable forecast cannot contain an available component")
        if self.status == "partial" and all(state == "unavailable" for state in states):
            raise ValueError("a partial forecast needs at least one available component")
        if self.status == "complete":
            expected_state = "prediction" if self.request.source.mode == "public" else "mock"
            if any(state != expected_state for state in states):
                raise ValueError(f"a complete {self.request.source.mode} forecast needs all three {expected_state} components")
            wind = by_component["wind"]
            if any(point.wind_gust_kt is None for point in wind.points):
                raise ValueError("a complete forecast cannot hide missing wind gusts")
            for component, item in by_component.items():
                availability = item.availability
                if (availability.valid_from_utc is None
                        or availability.valid_from_utc.astimezone(UTC) > self.request.horizon_start_utc
                        or availability.valid_to_utc is None
                        or availability.valid_to_utc.astimezone(UTC) < self.request.horizon_end_utc):
                    raise ValueError(f"a complete forecast needs full requested coverage for {component}")
                first = item.points[0]
                last = item.points[-1]
                point_start = first.valid_from_utc if isinstance(first, WindForecastPoint) else first.valid_at_utc
                point_end = last.valid_to_utc if isinstance(last, WindForecastPoint) else last.valid_at_utc
                if (point_start.astimezone(UTC) > self.request.horizon_start_utc
                        or point_end.astimezone(UTC) < self.request.horizon_end_utc):
                    raise ValueError(f"a complete forecast point series does not cover the requested {component} horizon")
        expected_available_state = "prediction" if self.request.source.mode == "public" else "mock"
        if any(state not in {expected_available_state, "unavailable"} for state in states):
            raise ValueError("forecast component state conflicts with the requested source mode")
        current = by_component["current"].availability
        if current.state != "unavailable" and (
            current.current_depth_ft != self.request.current_depth_ft
            or current.current_bin != self.request.current_bin
        ):
            raise ValueError("current forecast depth/bin does not match the explicit request")
        if self.request.source.mode == "public":
            for item in self.components:
                availability = item.availability
                if availability.state == "unavailable":
                    continue
                available_at = availability.issued_at_utc or availability.retrieved_at_utc
                if available_at is None or available_at.astimezone(UTC) > self.request.as_of_utc:
                    raise ValueError(f"{availability.component} was not available by forecast as_of_utc")
        return self


class ComposedForecast(Model):
    """Public/scenario component series plus only the snapshots safe for existing load consumers."""

    manifest: ComposedForecastManifest
    snapshots: list[EnvironmentSnapshot] = Field(default_factory=list, max_length=1201)

    @model_validator(mode="after")
    def _snapshots_match_status(self):
        if self.manifest.status == "unavailable" and self.snapshots:
            raise ValueError("an unavailable forecast cannot contain snapshots")
        if self.manifest.status == "complete" and not self.snapshots:
            raise ValueError("a complete forecast needs load-model-ready snapshots")
        expected_sources = {"forecast"} if self.manifest.request.source.mode == "public" else {"scenario", "mock"}
        expected_basis = "prediction" if self.manifest.request.source.mode == "public" else "scenario"
        for snapshot in self.snapshots:
            if snapshot.source not in expected_sources or snapshot.metadata is None or snapshot.metadata.basis != expected_basis:
                raise ValueError("composed snapshots must match the manifest source mode and metadata basis")
            if {item.component for item in snapshot.metadata.components} != {"wind", "current", "water_level"}:
                raise ValueError("composed snapshots need all three component provenance rows")
        if self.manifest.status == "complete":
            times = [snapshot.valid_at_utc.astimezone(UTC) for snapshot in self.snapshots]
            if times[0] > self.manifest.request.horizon_start_utc or times[-1] < self.manifest.request.horizon_end_utc:
                raise ValueError("complete snapshots must cover the requested forecast horizon")
            if any(b <= a for a, b in zip(times, times[1:])):
                raise ValueError("composed snapshots must be strictly increasing and unique")
        return self


class WaveComposeRequest(Model):
    """Bounded public wave acquisition with a reproducible availability cutoff."""

    berth_id: str
    as_of_utc: AwareDatetime = Field(
        description="Availability cutoff for observations and forecast cycles; provider retrieval after this time is excluded."
    )
    horizon_start_utc: AwareDatetime
    horizon_end_utc: AwareDatetime
    observation_lookback_hours: int = Field(default=24, ge=1, le=45 * 24)
    max_forecast_gap_hours: int = Field(default=3, ge=1, le=12)
    observation_station_id: Literal["44099"] = "44099"
    independent_check_station_id: Literal["44014"] = "44014"
    forecast_source: Literal["gfs-wave"] = "gfs-wave"
    include_spectrum: bool = True

    @model_validator(mode="after")
    def _horizon(self):
        self.as_of_utc = self.as_of_utc.astimezone(UTC)
        self.horizon_start_utc = self.horizon_start_utc.astimezone(UTC)
        self.horizon_end_utc = self.horizon_end_utc.astimezone(UTC)
        if self.horizon_start_utc < self.as_of_utc:
            raise ValueError("wave forecast horizon cannot begin before as_of_utc")
        if self.horizon_end_utc <= self.horizon_start_utc:
            raise ValueError("wave forecast horizon end must be after its start")
        if self.horizon_end_utc > self.as_of_utc + timedelta(hours=120):
            raise ValueError("wave forecast horizon cannot exceed 120 hours after as_of_utc")
        return self


class WaveBulkParameters(Model):
    """Provider bulk parameters; total sea and partitions are deliberately distinct."""

    component: Literal["total_sea", "swell", "wind_sea", "provider_partition"]
    provider_partition_id: str | None = None
    significant_height_ft: float = Field(ge=0)
    period_s: float | None = Field(default=None, gt=0)
    period_basis: Literal["dominant", "average", "peak", "provider_partition", "unknown"] = "unknown"
    direction_from_true_deg: float | None = Field(default=None, ge=0, lt=360)
    direction_basis: Literal["mean", "dominant", "peak", "provider_partition", "unknown"] = "unknown"

    @model_validator(mode="after")
    def _partition_identity(self):
        if self.component == "provider_partition" and not self.provider_partition_id:
            raise ValueError("a provider partition needs provider_partition_id")
        if self.component != "provider_partition" and self.provider_partition_id is not None:
            raise ValueError("provider_partition_id applies only to provider_partition")
        if self.period_s is None and self.period_basis != "unknown":
            raise ValueError("period_basis must be unknown when period is unavailable")
        if self.direction_from_true_deg is None and self.direction_basis != "unknown":
            raise ValueError("direction_basis must be unknown when direction is unavailable")
        return self


class WaveSpectrumBin(Model):
    """One provider-native frequency bin; Fourier coefficients are never reconstructed."""

    frequency_hz: float = Field(gt=0)
    energy_density_m2_per_hz: float | None = Field(default=None, ge=0)
    alpha1_direction_from_true_deg: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description="NDBC alpha1 mean direction waves come from, clockwise from true north.",
    )
    alpha2_direction_from_true_deg: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description="NDBC alpha2 principal direction waves come from, clockwise from true north.",
    )
    r1: float | None = Field(default=None, ge=0, le=1)
    r2: float | None = Field(default=None, ge=0, le=1)
    quality_flags: list[str] = Field(default_factory=list)


class WaveSpectrum(Model):
    """Native NDBC density/coefficient representation, not a reconstructed 2-D spectrum."""

    representation: Literal["frequency_density", "ndbc_fourier_coefficients"]
    frequency_bin_count: int = Field(ge=1)
    density_coverage: Literal["complete", "partial", "unavailable"]
    alpha1_coverage: Literal["complete", "partial", "unavailable"] = "unavailable"
    alpha2_coverage: Literal["complete", "partial", "unavailable"] = "unavailable"
    r1_coverage: Literal["complete", "partial", "unavailable"] = "unavailable"
    r2_coverage: Literal["complete", "partial", "unavailable"] = "unavailable"
    bins: list[WaveSpectrumBin] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def _bins(self):
        frequencies = [item.frequency_hz for item in self.bins]
        if any(b <= a for a, b in zip(frequencies, frequencies[1:])):
            raise ValueError("wave spectrum frequencies must be strictly increasing")
        if self.frequency_bin_count < len(self.bins):
            raise ValueError("frequency_bin_count cannot be below the supplied bin count")
        coverage = {
            "energy_density_m2_per_hz": self.density_coverage,
            "alpha1_direction_from_true_deg": self.alpha1_coverage,
            "alpha2_direction_from_true_deg": self.alpha2_coverage,
            "r1": self.r1_coverage,
            "r2": self.r2_coverage,
        }
        for field, state in coverage.items():
            values = [getattr(item, field) for item in self.bins]
            if state == "complete" and (self.frequency_bin_count != len(values) or any(value is None for value in values)):
                raise ValueError(f"complete {field} coverage needs every declared frequency bin")
            if state == "unavailable" and any(value is not None for value in values):
                raise ValueError(f"unavailable {field} coverage cannot carry values")
            if state == "partial" and not any(value is not None for value in values):
                raise ValueError(f"partial {field} coverage needs at least one value")
        coefficient_states = [self.alpha1_coverage, self.alpha2_coverage, self.r1_coverage, self.r2_coverage]
        if self.representation == "frequency_density" and (
            self.density_coverage == "unavailable" or any(state != "unavailable" for state in coefficient_states)
        ):
            raise ValueError("frequency_density needs density and cannot carry directional Fourier coefficients")
        if self.representation == "ndbc_fourier_coefficients" and all(state == "unavailable" for state in coefficient_states):
            raise ValueError("ndbc_fourier_coefficients needs at least one native coefficient product")
        return self


class OffshoreWavePoint(Model):
    """One offshore provider time; representations are alternatives, never additive forcing."""

    valid_at_utc: AwareDatetime
    sample_start_utc: AwareDatetime | None = None
    sample_end_utc: AwareDatetime | None = None
    timestamp_basis: Literal["start", "center", "end", "instant", "unknown"] = "unknown"
    total_sea: WaveBulkParameters | None = None
    partitions: list[WaveBulkParameters] = Field(default_factory=list, max_length=16)
    spectrum: WaveSpectrum | None = None
    original: dict[str, float | str] | None = None

    @model_validator(mode="after")
    def _representations(self):
        if self.total_sea is None and not self.partitions and self.spectrum is None:
            raise ValueError("an offshore wave point needs a total, partition or spectrum representation")
        if self.total_sea is not None and self.total_sea.component != "total_sea":
            raise ValueError("total_sea must be labeled total_sea")
        if any(item.component == "total_sea" for item in self.partitions):
            raise ValueError("total sea cannot be repeated as a provider partition")
        partition_keys = [(item.component, item.provider_partition_id) for item in self.partitions]
        if len(set(partition_keys)) != len(partition_keys):
            raise ValueError("wave partitions must be unique")
        if (self.sample_start_utc is None) != (self.sample_end_utc is None):
            raise ValueError("sample bounds must be supplied together")
        if self.sample_start_utc and self.sample_end_utc:
            start, end = self.sample_start_utc.astimezone(UTC), self.sample_end_utc.astimezone(UTC)
            valid = self.valid_at_utc.astimezone(UTC)
            if end <= start:
                raise ValueError("wave sample end must be after its start")
            if self.timestamp_basis == "unknown":
                raise ValueError("bounded wave samples need a timestamp_basis")
            if self.timestamp_basis == "start" and valid != start:
                raise ValueError("a start-stamped wave sample must use sample_start_utc as valid_at_utc")
            if self.timestamp_basis == "end" and valid != end:
                raise ValueError("an end-stamped wave sample must use sample_end_utc as valid_at_utc")
            if self.timestamp_basis == "center" and valid != start + (end - start) / 2:
                raise ValueError("a center-stamped wave sample must use the sample midpoint as valid_at_utc")
            if self.timestamp_basis == "instant":
                raise ValueError("an instant wave point cannot declare sample bounds")
        return self


class WaveSourceLocation(Model):
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=180)
    water_depth_m: float | None = Field(default=None, gt=0)
    grid_cell: str | None = None


class OffshoreWaveSeries(Model):
    """Observation, forecast, or independent check at its source location."""

    role: Literal["observation", "forecast", "independent_check"]
    provider: Literal["ndbc", "gfs-wave"]
    station_id: str | None = None
    model_id: str | None = None
    reference_time_utc: AwareDatetime | None = Field(
        default=None, description="Forecast model reference/cycle time; not a substitute for issue or retrieval time."
    )
    coverage: Literal["complete", "partial", "unavailable"]
    availability: EnvironmentComponentAvailability
    product_ids: list[str] = Field(default_factory=list)
    location: WaveSourceLocation | None = None
    applicability: Literal["offshore_boundary_only"] = "offshore_boundary_only"
    load_ready: Literal[False] = False
    representation_policy: Literal["choose_total_or_partitions_or_spectrum"] = "choose_total_or_partitions_or_spectrum"
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    points: list[OffshoreWavePoint] = Field(default_factory=list, max_length=2401)

    @model_validator(mode="after")
    def _availability_and_content(self):
        if self.availability.component != "waves":
            raise ValueError("an offshore wave series needs waves availability")
        if self.role == "forecast":
            if self.provider != "gfs-wave" or not self.model_id or self.station_id is not None:
                raise ValueError("forecast wave series needs structured GFS-Wave model identity")
        elif self.provider != "ndbc" or not self.station_id or self.model_id is not None:
            raise ValueError("observed wave series needs structured NDBC station identity")
        if self.station_id is not None and self.availability.station_id != self.station_id:
            raise ValueError("wave availability station_id must match the structured series identity")
        if self.coverage == "unavailable":
            if self.availability.state != "unavailable" or self.points or self.content_sha256:
                raise ValueError("an unavailable wave series cannot carry points or content hash")
            return self
        valid_states = {"prediction"} if self.role == "forecast" else {"live", "replay"}
        expected_basis = "prediction" if self.role == "forecast" else "observation"
        if self.availability.state not in valid_states or self.availability.basis != expected_basis:
            raise ValueError(f"available {self.role} wave series has the wrong state or basis")
        if not self.product_ids or self.location is None or not self.points or self.content_sha256 is None:
            raise ValueError("an available wave series needs products, location, points and a content hash")
        if self.availability.retrieved_at_utc is None:
            raise ValueError("an available wave series needs recorded retrieval provenance")
        if self.role != "forecast" and self.coverage != "partial":
            raise ValueError("observed wave completeness is undefined; available observation/check coverage must be partial")
        if self.role == "forecast":
            if self.reference_time_utc is None or self.availability.issued_at_utc is None:
                raise ValueError("an available GFS-Wave series needs reference and issue times")
            reference = self.reference_time_utc.astimezone(UTC)
            issued = self.availability.issued_at_utc.astimezone(UTC)
            retrieved = self.availability.retrieved_at_utc.astimezone(UTC)
            if not reference <= issued <= retrieved:
                raise ValueError("GFS-Wave reference, issue and retrieval times are inconsistent")
        times = [item.valid_at_utc.astimezone(UTC) for item in self.points]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("offshore wave points must be strictly increasing and unique")
        if self.role == "forecast" and any(value < self.reference_time_utc.astimezone(UTC) for value in times):
            raise ValueError("GFS-Wave points cannot precede the model reference time")
        starts = [(item.sample_start_utc or item.valid_at_utc).astimezone(UTC) for item in self.points]
        ends = [(item.sample_end_utc or item.valid_at_utc).astimezone(UTC) for item in self.points]
        available_from = self.availability.valid_from_utc
        available_to = self.availability.valid_to_utc
        if available_from is None or available_from.astimezone(UTC) != min(starts):
            raise ValueError("wave availability valid_from_utc must match the first point/sample bound")
        if available_to is None or available_to.astimezone(UTC) != max(ends):
            raise ValueError("wave availability valid_to_utc must match the last point/sample bound")
        retrieved = self.availability.retrieved_at_utc.astimezone(UTC)
        if self.role != "forecast" and any(value > retrieved for value in ends):
            raise ValueError("observed wave point/sample end cannot follow its recorded retrieval")
        if self.role == "forecast":
            if self.location.grid_cell is None or self.availability.grid_cell != self.location.grid_cell:
                raise ValueError("GFS-Wave availability and source location must identify the same grid cell")
            if any(
                point.spectrum is not None and point.spectrum.representation == "ndbc_fourier_coefficients"
                for point in self.points
            ):
                raise ValueError("GFS-Wave series cannot carry NDBC Fourier coefficient products")
        payload = self.model_dump(mode="json")
        digest = payload.pop("content_sha256")
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        if digest != hashlib.sha256(encoded).hexdigest():
            raise ValueError("offshore wave content_sha256 does not match its canonical content")
        return self


class WaveBerthExposureAvailability(Model):
    """Status of one physically distinct berth exposure; this model carries no measurements."""

    component: Literal["ocean_swell", "local_chop", "ship_wake", "tug_wake"]
    state: Literal["unavailable"] = "unavailable"
    reason_code: Literal[
        "NO_BERTH_WAVE_TRANSFER", "NO_DIRECTIONAL_FETCH", "NO_WAKE_SOURCE", "SOURCE_UNAVAILABLE"
    ] | None = None
    reason: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status(self):
        if self.reason_code is None or not self.reason:
            raise ValueError("unavailable berth wave exposure needs a reason code and reason")
        allowed = {
            "ocean_swell": {"NO_BERTH_WAVE_TRANSFER", "SOURCE_UNAVAILABLE"},
            "local_chop": {"NO_DIRECTIONAL_FETCH", "SOURCE_UNAVAILABLE"},
            "ship_wake": {"NO_WAKE_SOURCE", "SOURCE_UNAVAILABLE"},
            "tug_wake": {"NO_WAKE_SOURCE", "SOURCE_UNAVAILABLE"},
        }[self.component]
        if self.reason_code not in allowed:
            raise ValueError(f"{self.reason_code} does not apply to {self.component}")
        return self


class ComposedWaveManifest(Model):
    """Frozen offshore acquisition and explicit berth-applicability gaps."""

    schema_version: Literal["composed-waves-v1"] = "composed-waves-v1"
    revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    request: WaveComposeRequest
    offshore_series: list[OffshoreWaveSeries] = Field(min_length=3, max_length=3)
    berth_exposure: list[WaveBerthExposureAvailability] = Field(min_length=4, max_length=4)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _roles_coverage_and_time(self):
        by_role = {item.role: item for item in self.offshore_series}
        if set(by_role) != {"observation", "forecast", "independent_check"} or len(by_role) != len(self.offshore_series):
            raise ValueError("wave manifest needs observation, forecast and independent_check series")
        if by_role["observation"].station_id != self.request.observation_station_id:
            raise ValueError("wave observation station does not match the request")
        if by_role["independent_check"].station_id != self.request.independent_check_station_id:
            raise ValueError("independent wave check station does not match the request")
        if by_role["forecast"].model_id != self.request.forecast_source:
            raise ValueError("wave forecast model does not match the request")
        by_exposure = {item.component: item for item in self.berth_exposure}
        expected_exposure = {"ocean_swell", "local_chop", "ship_wake", "tug_wake"}
        if set(by_exposure) != expected_exposure or len(by_exposure) != len(self.berth_exposure):
            raise ValueError("wave manifest needs all four distinct berth exposure rows")
        cutoff = self.request.as_of_utc.astimezone(UTC)
        lookback = cutoff - timedelta(hours=self.request.observation_lookback_hours)
        for series in self.offshore_series:
            if series.coverage == "unavailable":
                continue
            retrieved = series.availability.retrieved_at_utc
            if retrieved is None or retrieved.astimezone(UTC) > cutoff:
                raise ValueError(f"{series.role} waves were not available by as_of_utc")
            if series.role != "forecast":
                for point in series.points:
                    valid = point.valid_at_utc.astimezone(UTC)
                    if valid > cutoff:
                        raise ValueError(f"{series.role} cannot contain future observations")
                    if valid < lookback:
                        raise ValueError(f"{series.role} is outside the requested observation lookback")
            if not self.request.include_spectrum and any(point.spectrum is not None for point in series.points):
                raise ValueError("wave manifest includes spectra excluded by the request")
            if series.availability.age_s is not None:
                if series.availability.age_basis == "valid_time":
                    basis_time = max(
                        (point.sample_end_utc or point.valid_at_utc).astimezone(UTC) for point in series.points
                    )
                else:
                    issued = series.availability.issued_at_utc
                    if issued is None:
                        raise ValueError("issued-time wave age needs an actual issue time")
                    basis_time = issued.astimezone(UTC)
                expected_age = (cutoff - basis_time).total_seconds()
                if expected_age < 0 or abs(series.availability.age_s - expected_age) > 1e-6:
                    raise ValueError(f"{series.role} wave age contradicts its declared basis and as_of_utc")
        forecast = by_role["forecast"]
        if forecast.coverage == "partial":
            if not any(
                self.request.horizon_start_utc <= point.valid_at_utc.astimezone(UTC) <= self.request.horizon_end_utc
                for point in forecast.points
            ):
                raise ValueError("partial wave forecast does not intersect the requested horizon")
        if forecast.coverage == "complete":
            times = [point.valid_at_utc.astimezone(UTC) for point in forecast.points]
            first, last = times[0], times[-1]
            if first > self.request.horizon_start_utc or last < self.request.horizon_end_utc:
                raise ValueError("complete wave forecast points must cover the requested horizon")
            maximum_gap = timedelta(hours=self.request.max_forecast_gap_hours)
            if any(b - a > maximum_gap for a, b in zip(times, times[1:])):
                raise ValueError("complete wave forecast exceeds the requested maximum gap")
        payload = self.model_dump(mode="json")
        revision = payload.pop("revision")
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        if revision != "sha256:" + hashlib.sha256(encoded).hexdigest():
            raise ValueError("wave manifest revision does not match its canonical content")
        return self


class ComposedWaves(Model):
    manifest: ComposedWaveManifest


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
