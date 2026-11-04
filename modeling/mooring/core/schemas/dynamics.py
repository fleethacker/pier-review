"""Berthing simulator (module M11, Phase 2) and approach planner (module M12, Phase 3) schemas."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .common import Envelope, Model, Status, Validity
from .mooring import FenderResult, LineTension

# ---------- M11 Berthing ----------


class ShipState(Model):
    """Ship pose and velocity in the berth frame. y_ft is the distance from the pier face to the centerline."""

    x_ft: float
    y_ft: float
    heading_true_deg: float = Field(ge=0, lt=360)
    u_kt: float = Field(default=0, description="Surge speed, + forward.")
    v_kt: float = Field(default=0, description="Sway speed, + toward the pier.")
    r_degps: float = Field(default=0, description="Yaw rate.")


class TugCommand(Model):
    t_s: float = Field(ge=0)
    tug_id: str
    force_lbf: float = Field(ge=0)
    direction_rel_deg: float = Field(
        ge=0, lt=360, description="Direction the tug pushes the ship, relative to the bow (90 = toward starboard)."
    )


class LineEvent(Model):
    t_s: float = Field(ge=0)
    line_number: int
    event: Literal["secured", "tensioned", "released"]


class BerthingSimRequest(Model):
    wire_omitted_defaults = {"sample_interval_s": None}

    scenario_id: str
    initial_state: ShipState
    tug_commands: list[TugCommand] = Field(default_factory=list, max_length=1000)
    line_events: list[LineEvent] = Field(default_factory=list, max_length=1000)
    duration_s: float = Field(default=900, gt=0, le=7200)
    dt_s: float = Field(default=0.1, ge=0.0001, le=1)
    sample_interval_s: float | None = Field(default=None, ge=0.1, description="Output sampling only; defaults to 1 s.")
    env_mode: Literal["steady", "gusting"] = "steady"

    @model_validator(mode="after")
    def bounded_run(self):
        if self.duration_s / (self.sample_interval_s or 1.0) > 9998:
            raise ValueError("at most 10000 output frames per simulation")
        if any(c.t_s > self.duration_s for c in [*self.tug_commands, *self.line_events]):
            raise ValueError("command is after the simulation end")
        return self


class SimEvent(Model):
    t_s: float
    kind: Literal["fender_contact", "line_overload", "speed_exceeded", "all_fast"]
    detail: str


class ContactSummary(Model):
    lateral_speed_fps: float
    energy_ftlbf: float
    fender_id: str
    pct_rated: float
    status: Status


class SimulationTransition(Model):
    t_s: float
    kind: Literal["contact_start", "contact_end", "line_taut", "line_slack", "secured", "tensioned", "released"]
    element_id: str


class SimulationDiagnostics(Model):
    parameter_set: str
    qualification: Literal["unqualified"] = "unqualified"
    integration_steps: int
    simulated_time_s: float
    initial_energy_ftlbf: float
    final_energy_ftlbf: float
    applied_work_ftlbf: float
    dissipated_energy_ftlbf: float
    line_event_energy_ftlbf: float
    energy_residual_ftlbf: float
    integration_dt_s: float


class BerthingSimResult(Model):
    wire_omitted_defaults = {"transitions": None, "diagnostics": None}
    transitions: list[SimulationTransition] | None = None
    diagnostics: SimulationDiagnostics | None = None

    series_url: str
    events: list[SimEvent]
    contact: ContactSummary | None
    max_line_tension_lbf: float


class BerthingSimResponse(Envelope[BerthingSimResult]):
    pass


class TugState(Model):
    tug_id: str
    force_lbf: float
    direction_rel_deg: float


class SimFrame(Model):
    """One frame: a WS /ws/sim/{session_id} message, or one entry of a batch run's series."""

    wire_omitted_defaults = {"validity": None, "diagnostics": None}
    validity: Validity | None = None
    diagnostics: SimulationDiagnostics | None = None

    t_s: float
    pose: ShipState
    tugs: list[TugState]
    lines: list[LineTension]
    fenders: list[FenderResult]
    alerts: list[str]


class SimSeries(Model):
    job_id: str
    frames: list[SimFrame]


class SimSessionCreate(Model):
    wire_omitted_defaults = {"dt_s": None, "duration_s": None}
    dt_s: float | None = Field(default=None, ge=0.0001, le=1)
    duration_s: float | None = Field(default=None, gt=0, le=7200)
    scenario_id: str
    initial_state: ShipState


class SimSessionCreated(Model):
    wire_omitted_defaults = {"validity": None}
    validity: Validity | None = None
    session_id: str
    ws_url: str


class SimTugCommandMessage(Model):
    """Client message on WS /ws/sim/{session_id}."""

    wire_omitted_defaults = {"t_s": None}
    t_s: float | None = Field(default=None, ge=0, description="Simulation time; absent schedules at the next integration boundary.")

    type: Literal["tug_command"]
    tug_id: str
    force_lbf: float = Field(ge=0)
    direction_rel_deg: float = Field(ge=0, lt=360)


class SimLineEventMessage(Model):
    wire_omitted_defaults = {"t_s": None}
    t_s: float | None = Field(default=None, ge=0, description="Simulation time; absent schedules at the next integration boundary.")

    type: Literal["line_event"]
    line_number: int
    event: Literal["secured", "tensioned", "released"]


class SimControlMessage(Model):
    type: Literal["pause", "resume", "reset"]


# ---------- M12 Approach ----------


class LatLon(Model):
    lat: float
    lon: float


class Waypoint(LatLon):
    leg_name: str
    channel_depth_mllw_ft: float
    width_ft: float


class RouteRequest(Model):
    origin: LatLon | None = Field(default=None, description="Start point; or give anchorage_id.")
    anchorage_id: str | None = None
    berth_id: str
    ship_class_id: str
    loading: str = "full_load"


class RouteResult(Model):
    waypoints: list[Waypoint]
    tug_rendezvous: LatLon
    abort_points: list[LatLon]


class RouteResponse(Envelope[RouteResult]):
    pass


class UkcRequest(Model):
    ship_class_id: str
    loading: str = "full_load"
    waypoints: list[Waypoint]
    eta_utc: datetime = Field(description="Time at the first waypoint.")
    speed_profile_kt: list[float] = Field(description="Speed on each leg (len = waypoints - 1).")


class UkcLeg(Model):
    leg_name: str
    min_ukc_ft: float
    squat_ft: float
    water_level_ft: float
    status: Status


class TimeWindow(Model):
    earliest_utc: datetime
    latest_utc: datetime


class UkcResult(Model):
    legs: list[UkcLeg]
    window: TimeWindow


class UkcResponse(Envelope[UkcResult]):
    pass


class ApproachSimRequest(Model):
    ship_class_id: str
    loading: str = "full_load"
    waypoints: list[Waypoint]
    eta_utc: datetime
    speed_profile_kt: list[float]
    env_mode: Literal["steady", "gusting"] = "steady"


class TrackPoint(LatLon):
    t_s: float
    heading_true_deg: float
    speed_kt: float
    cross_track_ft: float
    ukc_ft: float


class ApproachSimResult(Model):
    track_url: str
    max_cross_track_ft: float
    min_ukc_ft: float
    events: list[SimEvent]


class ApproachSimResponse(Envelope[ApproachSimResult]):
    pass


class ApproachTrack(Model):
    job_id: str
    points: list[TrackPoint]
