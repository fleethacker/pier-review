"""Berthing simulator (module M11, Phase 2) and approach planner (module M12, Phase 3) schemas."""

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .common import Envelope, Model, Status, Validity
from .mooring import FenderResult, LineTension
from .motion import (
    _require_qualified_motion,
    MotionAlert,
    MotionEnvironment,
    MotionFenderState,
    MotionFittingLoad,
    MotionForces,
    MotionLineState,
    MotionProvenance,
    MotionTugState,
    ShipMotion,
    SimLifecycle,
    SimSamplingPolicy,
)

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

    # Describe the opt-in identity rule to JSON Schema clients as well as Python.
    model_config = ConfigDict(json_schema_extra={"allOf": [{
        "if": {"required": ["schema_version"], "properties": {"schema_version": {"const": "rm0-v1"}}},
        "then": {
            "required": ["sequence", "session_id", "run_id", "scene_id", "scene_revision"],
            "properties": {
                "sequence": {"type": "integer", "minimum": 0},
                **{name: {"type": "string", "minLength": 1, "pattern": r"\S"}
                   for name in ("session_id", "run_id", "scene_id", "scene_revision")},
            },
        },
    }]})

    wire_omitted_defaults = dict.fromkeys((
        "schema_version", "sequence", "session_id", "run_id", "scene_id", "scene_revision", "motion",
        "tug_states", "environment", "line_states", "fitting_loads", "fender_states", "forces", "validity",
        "provenance", "structured_alerts", "diagnostics",
    ))
    diagnostics: SimulationDiagnostics | None = None

    t_s: float
    pose: ShipState
    tugs: list[TugState]
    lines: list[LineTension]
    fenders: list[FenderResult]
    alerts: list[str]

    schema_version: Literal["rm0-v1"] | None = None
    sequence: int | None = Field(default=None, strict=True, ge=0,
        description="Session-wide sequence, increasing across frames and lifecycle messages, including resets.")
    session_id: str | None = None
    run_id: str | None = Field(default=None, description="New run identifier on reset; t_s may then return to zero.")
    scene_id: str | None = None
    scene_revision: str | None = None
    motion: ShipMotion | None = Field(default=None, description="Canonical RM0 axes; legacy pose remains unchanged.")
    tug_states: list[MotionTugState] | None = Field(default=None, max_length=64)
    environment: MotionEnvironment | None = None
    line_states: list[MotionLineState] | None = Field(default=None, max_length=512)
    fitting_loads: list[MotionFittingLoad] | None = Field(default=None, max_length=1024)
    fender_states: list[MotionFenderState] | None = Field(default=None, max_length=512)
    forces: MotionForces | None = None
    validity: Validity | None = Field(default=None, description="Absent is unknown, never valid.")
    provenance: MotionProvenance | None = None
    structured_alerts: list[MotionAlert] | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def motion_metadata_is_consistent(self):
        if self.schema_version is not None and self.t_s < 0:
            raise ValueError("RM0 simulation time must be nonnegative")
        if (self.scene_id is None) != (self.scene_revision is None):
            raise ValueError("scene_id and scene_revision must be supplied together")
        if self.environment is not None and self.environment.t_s is not None and self.environment.t_s != self.t_s:
            raise ValueError("environment.t_s must match the frame simulation time")
        _require_qualified_motion(self, require_provenance=self.schema_version is not None)
        if self.schema_version is not None:
            if self.sequence is None or any(not value or not value.strip() for value in (
                self.session_id, self.run_id, self.scene_id, self.scene_revision,
            )):
                raise ValueError("RM0 frames require sequence and nonempty session/run/scene identity")
        for field, keys in (("tug_states", ("tug_id",)), ("line_states", ("line_number",)),
                            ("fitting_loads", ("owner", "fitting_id")), ("fender_states", ("fender_id",))):
            identifiers = [tuple(getattr(item, key) for key in keys) for item in getattr(self, field) or []]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{field} identifiers must be unique")
        return self


class SimSeries(Model):
    job_id: str
    frames: list[SimFrame]


class SimRecording(Model):
    """Bounded display recording. Sequence gaps mean decimation, never missing physics integration steps."""

    schema_version: Literal["rm0-v1"] = "rm0-v1"
    recording_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    scene_revision: str = Field(min_length=1)
    duration_s: float | None = Field(default=None, ge=0, description="Recorded simulation duration, excluding paused wall time.")
    sampling: SimSamplingPolicy
    frames: list[SimFrame] = Field(min_length=1, max_length=10000)
    lifecycle: list[SimLifecycle] = Field(default_factory=list, max_length=1000)
    validity: Validity | None = None
    provenance: MotionProvenance | None = None

    @model_validator(mode="after")
    def ordered_recording(self):
        for frame in self.frames:
            if frame.sequence is None or not frame.run_id or frame.schema_version != self.schema_version:
                raise ValueError("recorded frames need schema_version, sequence and run_id")
            if frame.session_id != self.session_id:
                raise ValueError("recorded frame session_id does not match recording")
            if (frame.scene_id, frame.scene_revision) != (self.scene_id, self.scene_revision):
                raise ValueError("recorded frame scene reference does not match recording")
        for event in self.lifecycle:
            if event.session_id != self.session_id:
                raise ValueError("lifecycle session_id does not match recording")
            if event.scene_id is not None and (event.scene_id, event.scene_revision) != (self.scene_id, self.scene_revision):
                raise ValueError("lifecycle scene reference does not match recording")
        for messages in (self.frames, self.lifecycle):
            if any(current.sequence <= previous.sequence for previous, current in zip(messages, messages[1:])):
                raise ValueError("recording sequences must be strictly increasing")
        messages = sorted([*self.frames, *self.lifecycle], key=lambda message: message.sequence)
        sequences = [message.sequence for message in messages]
        if len(sequences) != len(set(sequences)):
            raise ValueError("frame and lifecycle sequences must be unique within a session")
        times: dict[str, float] = {}
        completed_runs: set[str] = set()
        current_run = None
        for message in messages:
            if isinstance(message, SimLifecycle) and message.state == "reset" and message.run_id == current_run:
                raise ValueError("reset must use a new run_id")
            if message.t_s < 0 or message.t_s < times.get(message.run_id, 0):
                raise ValueError("simulation time must be nonnegative and monotonic within a run")
            if current_run != message.run_id:
                if message.run_id in completed_runs:
                    raise ValueError("a recording cannot return to a previous run after reset")
                if current_run is not None:
                    completed_runs.add(current_run)
                current_run = message.run_id
            times[message.run_id] = message.t_s
        _require_qualified_motion(self)
        return self


class SimSessionCreate(Model):
    wire_omitted_defaults = {"dt_s": None, "duration_s": None, "record_interval_s": None}
    dt_s: float | None = Field(default=None, ge=0.0001, le=1)
    duration_s: float | None = Field(default=None, gt=0, le=7200)
    record_interval_s: float | None = Field(default=None, ge=0.1, description="Simulation-time interval between recorded frames; absent means 1 s.")
    scenario_id: str
    initial_state: ShipState


class SimSessionCreated(Model):
    wire_omitted_defaults = {"validity": None, "scene_url": None, "protocol": None, "recording_url": None}

    session_id: str
    ws_url: str
    validity: Validity | None = None
    scene_url: str | None = Field(default=None, description="Optional immutable SimScene resource; legacy sessions do not expose it.")
    protocol: Literal["rm0-v1"] | None = Field(default=None, description="Present only when the session implements the RM0 stream protocol.")
    recording_url: str | None = Field(default=None, description="Bounded SimRecording resource for this session (live copy, else persisted).")


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


class SimSpeedMessage(Model):
    """Client message: simulated seconds per wall second. The physics step never changes."""

    type: Literal["set_speed"]
    speed: float = Field(gt=0, le=16)


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
