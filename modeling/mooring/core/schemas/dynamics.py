"""Berthing simulator (module M11, Phase 2) and approach planner (module M12, Phase 3) schemas."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Envelope, Model, Status
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
    scenario_id: str
    initial_state: ShipState
    tug_commands: list[TugCommand] = Field(default_factory=list)
    line_events: list[LineEvent] = Field(default_factory=list)
    duration_s: float = Field(default=900, gt=0, le=7200)
    dt_s: float = Field(default=0.1, gt=0, le=1)
    env_mode: Literal["steady", "gusting"] = "steady"


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


class BerthingSimResult(Model):
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
    scenario_id: str
    initial_state: ShipState


class SimSessionCreated(Model):
    session_id: str
    ws_url: str


class SimTugCommandMessage(Model):
    """Client message on WS /ws/sim/{session_id}."""

    type: Literal["tug_command"]
    tug_id: str
    force_lbf: float = Field(ge=0)
    direction_rel_deg: float = Field(ge=0, lt=360)


class SimLineEventMessage(Model):
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
