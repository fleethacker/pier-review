"""S6 port transit: ships entering or leaving port on their own thrust or with tugs, several vessels on one clock.

Conventions (same as the rest of the repo): ship body +x forward, +y port, +z up; yaw rate positive counterclockwise
seen from above (turning to port). Headings and courses are true bearings, clockwise from north. Local plane
coordinates are east (`x_east_ft`) and north (`y_north_ft`) from the request origin. `rudder_deg` positive turns the
bow to port. Wind is FROM, current is TOWARD. Engine order is a signed fraction of maximum: +1 full ahead, -1 full
astern. Every hull, rudder and propulsion coefficient is an estimate or assumption and is labeled as such.
"""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .common import Envelope, Model, Validity
from .environment import EnvironmentSnapshot
from .missions import TrackFix


class GeoPoint(Model):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class TransitWaypoint(GeoPoint):
    wire_omitted_defaults = {"name": None, "acceptance_radius_ft": None}
    name: str | None = Field(default=None, max_length=120)
    speed_kt: float = Field(ge=0, le=35, description="Target speed through the water on the leg ending here.")
    acceptance_radius_ft: float | None = Field(default=None, gt=0,
        description="Switch to the next leg inside this radius; default two ship lengths. The final waypoint is the arrival point.")


class TransitStart(GeoPoint):
    heading_true_deg: float = Field(ge=0, lt=360)
    speed_kt: float = Field(default=0, ge=0, le=35, description="Initial surge speed through the water.")


class PropulsionAssumptions(Model):
    """Reference data has no propulsion or rudder data; these are explicit, labeled assumptions."""

    wire_omitted_defaults = {"max_speed_kt": None, "bow_thruster_lbf": None}
    max_speed_kt: float | None = Field(default=None, gt=0, le=40,
        description="Calm deep-water speed at full ahead. Null uses the class's labeled default, if any; else invalid.")
    astern_thrust_fraction: float = Field(default=0.6, gt=0, le=1, description="Full-astern thrust / full-ahead thrust.")
    engine_time_constant_s: float = Field(default=20.0, gt=0, le=300, description="First-order lag of delivered thrust.")
    max_rudder_deg: float = Field(default=35.0, gt=0, le=45)
    rudder_rate_degps: float = Field(default=2.33, gt=0, le=20,
        description="Default from the common 35-to-30-degrees-in-28-seconds steering-gear criterion.")
    bow_thruster_lbf: float | None = Field(default=None, gt=0, description="Null means no bow thruster.")


class AutopilotSettings(Model):
    lookahead_ship_lengths: float = Field(default=2.0, gt=0, le=10, description="Line-of-sight lookahead distance.")
    arrival_slowdown_nm: float = Field(default=0.5, ge=0, le=5, description="Ramp speed down over this distance before the final waypoint.")
    arrival_speed_kt: float = Field(default=0.0, ge=0, le=10, description="Target speed at the final waypoint.")


class TransitHelmCommand(Model):
    """Scripted helm/engine order at a simulation time. A null field leaves that control to the autopilot."""

    wire_omitted_defaults = {"rudder_deg": None, "engine_order": None}
    t_s: float = Field(ge=0)
    rudder_deg: float | None = Field(default=None, ge=-45, le=45)
    engine_order: float | None = Field(default=None, ge=-1, le=1)


TugPoint = Literal["bow", "stern", "port_shoulder", "starboard_shoulder", "port_quarter", "starboard_quarter"]


class TransitTugCommand(Model):
    """Timed tug force on the hull at a named point. Direction is relative to the bow, clockwise: 0 = ahead
    (towing forward), 90 = toward starboard, 180 = astern (braking), 270 = toward port."""

    t_s: float = Field(ge=0)
    tug_id: str
    point: TugPoint
    force_lbf: float = Field(ge=0)
    direction_rel_deg: float = Field(ge=0, lt=360)


class TugAssistSettings(Model):
    """Automatic low-speed assist: tugs supply the yaw moment the rudder cannot and brake on arrival."""

    policy: Literal["manual", "auto"] = "auto"
    tug_ids: list[str] = Field(default_factory=list, max_length=4, description="Tugs available; empty uses the catalog's first two.")
    assist_below_kt: float = Field(default=5.0, ge=0, le=12, description="Automatic assist applies below this speed.")


class VesselTransit(Model):
    wire_omitted_defaults = {"tug_assist": None}
    vessel_id: str = Field(min_length=1, max_length=120)
    ship_class_id: str
    loading: str = "full_load"
    start: TransitStart
    route: list[TransitWaypoint] = Field(min_length=1, max_length=200)
    mode: Literal["own_thrust", "tug_assisted"] = "own_thrust"
    propulsion: PropulsionAssumptions = Field(default_factory=PropulsionAssumptions)
    autopilot: AutopilotSettings = Field(default_factory=AutopilotSettings)
    helm_commands: list[TransitHelmCommand] = Field(default_factory=list, max_length=2000)
    tug_commands: list[TransitTugCommand] = Field(default_factory=list, max_length=2000)
    tug_assist: TugAssistSettings | None = None

    @model_validator(mode="after")
    def tugs_only_when_assisted(self):
        if self.mode == "own_thrust" and (self.tug_commands or self.tug_assist is not None):
            raise ValueError("own_thrust transits cannot have tug commands or tug assist")
        return self


class TransitRequest(Model):
    wire_omitted_defaults = {"environment": None, "start_utc": None, "origin": None, "sample_interval_s": None}
    vessels: list[VesselTransit] = Field(min_length=1, max_length=8)
    environment: EnvironmentSnapshot | None = Field(default=None,
        description="Steady wind/current for the whole run. Null means explicitly calm (labeled), not unknown.")
    start_utc: AwareDatetime | None = Field(default=None, description="Optional UTC epoch for track timestamps.")
    origin: GeoPoint | None = Field(default=None, description="Local plane origin; default the first vessel's start.")
    duration_s: float = Field(default=3600, gt=0, le=14_400)
    dt_s: float = Field(default=0.2, ge=0.05, le=1.0)
    sample_interval_s: float | None = Field(default=None, ge=0.5, description="Output frame spacing; default 2 s.")

    @model_validator(mode="after")
    def unique_vessels(self):
        ids = [v.vessel_id for v in self.vessels]
        if len(ids) != len(set(ids)):
            raise ValueError("vessel_id must be unique")
        if self.duration_s / (self.sample_interval_s or 2.0) > 20_000:
            raise ValueError("at most 20000 output frames per vessel")
        return self


class BodyWrench(Model):
    """Force and yaw moment on the ship in BODY axes (surge forward, sway port, yaw counterclockwise)."""

    surge_lbf: float
    sway_lbf: float
    yaw_ftlbf: float


class TransitForces(Model):
    hull: BodyWrench
    propeller: BodyWrench
    rudder: BodyWrench
    wind: BodyWrench
    tugs: BodyWrench
    bow_thruster: BodyWrench


class TransitTugState(Model):
    tug_id: str
    point: TugPoint
    force_lbf: float = Field(ge=0)
    direction_rel_deg: float = Field(ge=0, lt=360)
    lat: float = Field(ge=-90, le=90, description="Hull contact point; tug hull kinematics are not modeled.")
    lon: float = Field(ge=-180, le=180)
    source: Literal["command", "auto_assist"]


class TransitVesselState(Model):
    vessel_id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    x_east_ft: float
    y_north_ft: float
    heading_true_deg: float = Field(ge=0, lt=360)
    cog_true_deg: float | None = Field(default=None, ge=0, lt=360, description="Null when nearly stopped.")
    sog_kt: float = Field(ge=0)
    stw_kt: float = Field(description="Surge speed through the water, + ahead.")
    u_kt: float
    v_kt: float = Field(description="Sway through the water, + to port.")
    r_degps: float = Field(description="Yaw rate, + counterclockwise (to port).")
    rudder_deg: float
    engine_order: float = Field(ge=-1, le=1, description="Commanded order.")
    thrust_lbf: float = Field(description="Delivered thrust after engine lag, + ahead.")
    leg_index: int = Field(ge=0, description="Index of the waypoint being steered for.")
    cross_track_ft: float = Field(description="Signed distance from the current leg, + to port of track.")
    distance_to_go_nm: float = Field(ge=0)
    status: Literal["underway", "arrived", "stopped_short", "invalid"]
    tugs: list[TransitTugState] = Field(default_factory=list)
    forces: TransitForces


class TransitFrame(Model):
    wire_omitted_defaults = {"t_utc": None}
    t_s: float = Field(ge=0)
    t_utc: AwareDatetime | None = None
    vessels: list[TransitVesselState]


class TransitEvent(Model):
    t_s: float = Field(ge=0)
    vessel_id: str
    kind: Literal["waypoint_reached", "arrived", "rudder_saturated", "tug_saturated", "large_cross_track",
                  "stopped_short", "integration_failed"]
    detail: str


class TransitVesselSummary(Model):
    wire_omitted_defaults = {"arrival_t_s": None}
    vessel_id: str
    ship_class_id: str
    mode: Literal["own_thrust", "tug_assisted"]
    arrived: bool
    arrival_t_s: float | None = None
    distance_nm: float = Field(ge=0)
    max_cross_track_ft: float = Field(ge=0)
    max_rudder_deg: float = Field(ge=0)
    max_tug_force_lbf: float = Field(ge=0)
    max_speed_assumed_kt: float = Field(gt=0)
    track: list[TrackFix] = Field(description="Sampled positions in the S5 fix format, for storyboard replay.")


class TransitResult(Model):
    series_url: str
    vessels: list[TransitVesselSummary]
    events: list[TransitEvent]


class TransitResponse(Envelope[TransitResult]):
    pass


class TransitSeries(Model):
    job_id: str
    frames: list[TransitFrame]


class TransitPreset(Model):
    preset_id: str
    title: str
    description: str
    request: TransitRequest
    validity: Validity
