"""S7 trajectory prediction: the "backup camera for ships".

From a vessel's current state, the commands in force and current conditions, predict where it will be over the next
minutes, with its hull footprint, an uncertainty corridor and the first predicted contact or closest approach to a
hazard. Optional what-if alternatives change the commands; the baseline holds them.

Conventions follow core/schemas/transit.py: body +x forward, +y port, yaw rate + counterclockwise; headings true,
clockwise from north; rudder + turns the bow to port; engine order -1..1; wind FROM, current TOWARD. Predictions use the
same dynamics as the simulators (S6 transit, S1-S3 berthing), so they carry the same limited validity, plus input age.
Decision support for a demonstrator, never navigational guidance.
"""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .common import Envelope, Model, Validity
from .dynamics import ForcingSpec
from .environment import EnvironmentSnapshot
from .missions import TrackFix
from .transit import GeoPoint, PropulsionAssumptions, TransitHelmCommand, TransitTugCommand, TugPoint


class StateUncertainty(Model):
    """One-sigma uncertainty of the starting state (e.g. GPS and heading sensor error)."""

    position_sd_ft: float = Field(default=15.0, ge=0)
    heading_sd_deg: float = Field(default=1.0, ge=0)
    speed_sd_kt: float = Field(default=0.2, ge=0)


class CurrentTugForce(Model):
    tug_id: str
    point: TugPoint
    force_lbf: float = Field(ge=0)
    direction_rel_deg: float = Field(ge=0, lt=360)


class ObservedShipState(Model):
    """The starting state: where the ship is now and what it is doing."""

    wire_omitted_defaults = {"delivered_thrust_lbf": None, "uncertainty": None, "source": None}
    vessel_id: str = Field(min_length=1, max_length=120)
    ship_class_id: str
    loading: str = "full_load"
    observed_utc: AwareDatetime = Field(description="Time the state was observed; input age = as_of_utc - observed_utc.")
    position: GeoPoint
    heading_true_deg: float = Field(ge=0, lt=360)
    surge_kt: float = Field(description="Speed through the water, + ahead.")
    sway_kt: float = Field(default=0.0, description="Through the water, + to port.")
    yaw_rate_degps: float = Field(default=0.0, description="+ counterclockwise (turning to port).")
    rudder_deg: float = Field(default=0.0, ge=-45, le=45)
    engine_order: float = Field(default=0.0, ge=-1, le=1)
    delivered_thrust_lbf: float | None = Field(default=None, description="Null assumes thrust has settled at the order.")
    tugs: list[CurrentTugForce] = Field(default_factory=list, max_length=4)
    uncertainty: StateUncertainty | None = Field(default=None, description="Null: no initial-state spread is sampled.")
    source: str | None = Field(default=None, max_length=120, description="e.g. gps+gyro, ais, replay:<mission_id>, sim:<session>.")


class WhatIf(Model):
    """An alternative set of commands from now on. Times are seconds from the prediction start."""

    alt_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=120)
    helm_commands: list[TransitHelmCommand] = Field(default_factory=list, max_length=50)
    tug_commands: list[TransitTugCommand] = Field(default_factory=list, max_length=50)


class OtherVessel(Model):
    """Another vessel whose path is checked for clearance: a supplied predicted/planned path, not simulated here."""

    vessel_id: str
    beam_ft: float = Field(gt=0)
    length_ft: float = Field(gt=0)
    path: list[TrackFix] = Field(min_length=1, max_length=2000)


class UncertaintySettings(Model):
    samples: int = Field(default=0, ge=0, le=64, description="Monte Carlo samples per alternative; 0 = no corridor.")
    seed: int = Field(default=0, ge=0)
    model: Literal["s10_gust_current"] = Field(default="s10_gust_current",
        description="Seeded gust and current perturbations from the S10 uncertainty model (unqualified), plus initial-state spread.")
    percentile: float = Field(default=90.0, gt=50, lt=100, description="Corridor encloses this share of sampled footprints.")


class HazardSettings(Model):
    wire_omitted_defaults = {"berth_id": None}
    berth_id: str | None = Field(default=None, description="Check clearance to this berth's pier face and fenders.")
    coastline: bool = Field(default=True, description="Check clearance to available coastline data, where covered.")
    min_clearance_ft: float = Field(default=50.0, ge=0, description="Clearance below this is reported as a breach.")


class PredictionRequest(Model):
    wire_omitted_defaults = {"environment": None, "as_of_utc": None, "forcing": None, "engine": None}
    vessel: ObservedShipState
    environment: EnvironmentSnapshot | None = Field(default=None,
        description="Conditions held over the horizon. Null means explicitly calm (labeled), not unknown.")
    as_of_utc: AwareDatetime | None = Field(default=None, description="Prediction time; default now.")
    forcing: ForcingSpec | None = Field(default=None, description=(
        "S7b: time-varying forcing (S2 ForcingSpec), sampled at prediction-relative time (t = 0 is as_of_utc) through "
        "the S2 resolver around `environment` (null = calm base). Absent = fixed environment, unchanged behavior. A replay "
        "series that ends before the horizon is rejected (on_uncovered 'stop') or the horizon is truncated, with a validity "
        "reason ('invalidate'); it is never extrapolated."))
    engine: Literal["transit", "berthing"] | None = Field(default=None, description=(
        "Requested engine. Never switched automatically. 'berthing' (S1-S3) has no validated state/parameter handoff and is "
        "answered 501 unsupported."))
    horizon_s: float = Field(default=300, gt=0, le=900)
    tick_s: float = Field(default=10, ge=1, le=60, description="Output spacing of predicted states and footprints.")
    dt_s: float = Field(default=0.2, ge=0.05, le=1.0)
    propulsion: PropulsionAssumptions = Field(default_factory=PropulsionAssumptions)
    alternatives: list[WhatIf] = Field(default_factory=list, max_length=4,
        description="What-if command sets; the baseline (commands held) is always predicted as alt_id 'hold'.")
    others: list[OtherVessel] = Field(default_factory=list, max_length=16)
    uncertainty: UncertaintySettings = Field(default_factory=UncertaintySettings)
    hazards: HazardSettings = Field(default_factory=HazardSettings)

    @model_validator(mode="after")
    def unique_alternatives(self):
        ids = [a.alt_id for a in self.alternatives]
        if "hold" in ids or len(ids) != len(set(ids)):
            raise ValueError("alternative ids must be unique and must not be 'hold'")
        if self.horizon_s / self.tick_s > 900:
            raise ValueError("at most 900 ticks")
        return self


class PredictedTick(Model):
    wire_omitted_defaults = {"cog_true_deg": None, "position_sd_ft": None}
    t_s: float = Field(ge=0, description="Seconds after as_of_utc.")
    t_utc: AwareDatetime
    position: GeoPoint
    heading_true_deg: float = Field(ge=0, lt=360)
    sog_kt: float = Field(ge=0)
    cog_true_deg: float | None = Field(default=None, ge=0, lt=360)
    rudder_deg: float
    engine_order: float = Field(ge=-1, le=1)
    footprint: list[GeoPoint] = Field(min_length=3, max_length=64, description="Hull outline at this tick (parametric planform).")
    position_sd_ft: float | None = Field(default=None, ge=0, description="Spread of sampled positions; null without samples.")


HazardKind = Literal["pier", "fender", "coastline", "vessel"]


class HazardApproach(Model):
    wire_omitted_defaults = {"probability": None}
    t_s: float = Field(ge=0)
    kind: HazardKind
    element_id: str
    clearance_ft: float = Field(description="Hull-to-hazard distance at that time; <= 0 means contact.")
    position: GeoPoint = Field(description="Closest point on the hull.")
    probability: float | None = Field(default=None, ge=0, le=1,
        description="Share of uncertainty samples that breach; null without samples. Not a calibrated probability.")


class PredictionAlternative(Model):
    wire_omitted_defaults = {"corridor": None, "closest_approach": None, "first_breach": None}
    alt_id: str
    label: str
    ticks: list[PredictedTick]
    corridor: list[GeoPoint] | None = Field(default=None,
        description="Outline enclosing the chosen percentile of sampled hull footprints over the horizon; null without samples.")
    closest_approach: HazardApproach | None = Field(default=None, description="Smallest clearance to any checked hazard.")
    first_breach: HazardApproach | None = Field(default=None,
        description="First time clearance falls below min_clearance_ft on the central prediction.")


class ForcingCoverage(Model):
    start_s: float
    end_s: float


class ForcingBasis(Model):
    """What the environment over the horizon was: fixed, or sampled from an immutable forcing series."""

    kind: Literal["fixed_environment", "time_varying"] = "fixed_environment"
    revision: str | None = Field(default=None, description="S2 series revision (frc-...); null for a fixed environment.")
    synthetic: bool = Field(default=False, description="True when the series is generated (steady/ramp/gusts), not observed.")
    series_kind: str | None = None
    coverage: ForcingCoverage | None = Field(default=None, description="Prediction-relative seconds the series is defined over.")
    requested_horizon_s: float | None = None
    horizon_s: float | None = Field(default=None, description="Horizon actually predicted; less than requested when truncated.")
    truncated: bool = False


class PredictionResult(Model):
    wire_omitted_defaults = {"forcing_basis": ForcingBasis().model_dump(mode="json")}
    vessel_id: str
    engine: Literal["transit", "berthing"]
    as_of_utc: AwareDatetime
    input_age_s: float = Field(ge=0, description="as_of_utc - observed_utc. Stale inputs reduce validity.")
    hazards_checked: list[HazardKind] = Field(description="Hazard kinds actually checked; unchecked kinds are not clear, just unknown.")
    alternatives: list[PredictionAlternative] = Field(min_length=1, description="'hold' first, then what-ifs in request order.")
    forcing_basis: ForcingBasis = Field(default_factory=ForcingBasis,
        description="Omitted on the wire for the default fixed environment; absent means fixed_environment.")


class PredictionResponse(Envelope[PredictionResult]):
    pass


class PredictionPreset(Model):
    preset_id: str
    title: str
    request: PredictionRequest
    validity: Validity
