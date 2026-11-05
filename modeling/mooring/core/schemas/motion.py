"""RM0 display contracts. These types describe supplied values, never compute dynamics.

Berth +y is off-pier and +z is up from MLLW. Ship +x is forward, +y port, +z up;
positive rotations follow the right-hand rule. Unknown quantities remain null.
"""

from typing import Annotated, ClassVar, Literal

from pydantic import AwareDatetime, Field, model_validator

from .common import Model, Severity, Status, Validity
from .environment import EnvironmentMetadata

MotionAvailability = Literal["available", "unavailable", "not_simulated", "unknown"]
MotionDofState = Literal["simulated", "prescribed", "not_simulated", "unknown"]


def _require_qualified_motion(model: Model, *, require_provenance: bool = True) -> None:
    """An aggregate cannot claim qualification that its supplied components lack."""
    validity = getattr(model, "validity", None)
    if validity is not None and validity.state == "invalid":
        return
    is_valid = validity is not None and validity.state == "valid"
    provenance = getattr(model, "provenance", None)
    if is_valid and (require_provenance or provenance is not None):
        if provenance is None or provenance.kind != "qualified":
            raise ValueError("valid motion data needs qualified provenance")

    def visit(value):
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
        elif isinstance(value, Model):
            if hasattr(value, "validity") and hasattr(value, "provenance"):
                child_validity = value.validity
                if child_validity is not None and child_validity.state == "invalid":
                    raise ValueError("motion data containing invalid components must be invalid")
                if is_valid:
                    excluded = getattr(value, "availability", None) in ("unavailable", "not_simulated")
                    if excluded and (child_validity is None or child_validity.state == "unknown"):
                        return
                    if child_validity is None or child_validity.state != "valid":
                        raise ValueError("valid motion data cannot contain unqualified components")
                    if value.provenance is None or value.provenance.kind != "qualified":
                        raise ValueError("valid motion data cannot contain unqualified components")
            for name in type(value).model_fields:
                visit(getattr(value, name))

    for name in type(model).model_fields:
        visit(getattr(model, name))


class MotionProvenance(Model):
    kind: Literal["mock", "estimated", "qualified", "unknown"]
    source: str = Field(min_length=1, description="Producer, source or named synthetic fixture.")
    references: list[str] = Field(default_factory=list, max_length=32)
    notes: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def qualification_needs_evidence(self):
        if self.kind == "qualified" and (not self.references or any(not item.strip() for item in self.references)):
            raise ValueError("qualified provenance needs at least one evidence reference")
        return self


class MotionEvidence(Model):
    """Availability is separate from qualification: an available value may be unqualified."""

    # Include values and observed states, not identifiers, source metadata or reasons.
    measurement_fields: ClassVar[tuple[str, ...]] = ()
    availability: MotionAvailability = "unknown"
    provenance: MotionProvenance | None = None
    validity: Validity | None = Field(default=None, description="Absent means unknown, never valid.")

    @model_validator(mode="after")
    def qualified_values_only(self):
        if self.validity is not None and self.validity.state == "valid":
            if self.availability != "available":
                raise ValueError("valid data must be available")
            if self.provenance is None or self.provenance.kind != "qualified":
                raise ValueError("valid data needs qualified provenance")
        _require_qualified_motion(self)
        return self

    @model_validator(mode="after")
    def status_preserves_validity(self):
        status = getattr(self, "status", None)
        if self.validity is not None and status in ("GREEN", "AMBER", "RED"):
            if self.validity.state == "invalid" and status != "RED":
                raise ValueError("invalid motion data requires RED status")
            if self.validity.state == "limited" and status == "GREEN":
                raise ValueError("limited motion data cannot have GREEN status")
        return self

    @model_validator(mode="after")
    def unavailable_values_are_absent(self):
        if self.availability in ("unavailable", "not_simulated"):
            supplied = [name for name in self.measurement_fields if _has_motion_value(getattr(self, name))]
            if supplied:
                raise ValueError("unavailable or not_simulated motion values must be absent: " + ", ".join(supplied))
        return self


def _has_motion_value(value) -> bool:
    """Zero and known states are data; empty geometry and unknown coordinates are not."""
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return any(_has_motion_value(item) for item in value)
    if isinstance(value, Model):
        names = value.measurement_fields if isinstance(value, MotionEvidence) else type(value).model_fields
        return any(_has_motion_value(getattr(value, name)) for name in names)
    if isinstance(value, str):
        return value not in ("unknown", "not_simulated")
    return True


class BerthPosition(Model):
    x_ft: float | None = None
    y_ft: float | None = Field(default=None, description="Positive off-pier.")
    z_mllw_ft: float | None = Field(default=None, description="Elevation above MLLW; positive upward.")


class ShipPoint(Model):
    x_ft: float | None = Field(default=None, description="Forward from the ship reference origin.")
    y_ft: float | None = Field(default=None, description="Port from the ship reference origin.")
    z_ft: float | None = Field(default=None, description="Up from the declared reference waterline/loading.")


EmptyBerthPoints = Annotated[list[BerthPosition], Field(max_length=0)]
BerthPolyline = EmptyBerthPoints | Annotated[list[BerthPosition], Field(min_length=2, max_length=32)]
BerthOutline = EmptyBerthPoints | Annotated[list[BerthPosition], Field(min_length=3, max_length=4096)]
ShipHullOutline = (Annotated[list[ShipPoint], Field(max_length=0)]
                   | Annotated[list[ShipPoint], Field(min_length=3, max_length=4096)])


class BerthVelocity(Model):
    x_fps: float | None = None
    y_fps: float | None = None
    z_fps: float | None = None


class BerthAcceleration(Model):
    x_fps2: float | None = None
    y_fps2: float | None = None
    z_fps2: float | None = None


class BerthForce(Model):
    x_lbf: float | None = None
    y_lbf: float | None = None
    z_lbf: float | None = None


class MotionPose(Model):
    x_ft: float | None = Field(default=None, description="Ship origin in berth axes.")
    y_ft: float | None = Field(default=None, description="Ship origin, positive off-pier.")
    heave_mllw_ft: float | None = Field(default=None, description="Absolute ship-origin elevation above MLLW, not a displacement from initial tide.")
    roll_deg: float | None = Field(default=None, description="Right-hand rotation about ship +x.")
    pitch_deg: float | None = Field(default=None, description="Right-hand rotation about ship +y.")
    yaw_deg: float | None = Field(default=None, description="Counterclockwise from berth +x, not a compass bearing; may be unwrapped.")


class MotionVelocity(Model):
    surge_fps: float | None = None
    sway_fps: float | None = Field(default=None, description="Positive toward port; unlike legacy ShipState.v_kt.")
    heave_fps: float | None = None
    roll_degps: float | None = None
    pitch_degps: float | None = None
    yaw_degps: float | None = None


class MotionAcceleration(Model):
    surge_fps2: float | None = None
    sway_fps2: float | None = None
    heave_fps2: float | None = None
    roll_degps2: float | None = None
    pitch_degps2: float | None = None
    yaw_degps2: float | None = None


class MotionDofs(Model):
    surge: MotionDofState = "unknown"
    sway: MotionDofState = "unknown"
    heave: MotionDofState = "unknown"
    roll: MotionDofState = "unknown"
    pitch: MotionDofState = "unknown"
    yaw: MotionDofState = "unknown"


class ShipMotion(MotionEvidence):
    measurement_fields = ("pose", "velocity", "dofs", "acceleration")

    pose: MotionPose
    velocity: MotionVelocity
    dofs: MotionDofs
    acceleration: MotionAcceleration | None = None

    @model_validator(mode="after")
    def vertical_dofs_are_honest(self):
        for axis, position, velocity, acceleration in (
            ("heave", "heave_mllw_ft", "heave_fps", "heave_fps2"),
            ("roll", "roll_deg", "roll_degps", "roll_degps2"),
            ("pitch", "pitch_deg", "pitch_degps", "pitch_degps2"),
        ):
            values = [getattr(self.pose, position), getattr(self.velocity, velocity)]
            if self.acceleration is not None:
                values.append(getattr(self.acceleration, acceleration))
            if getattr(self.dofs, axis) in ("not_simulated", "unknown") and any(value is not None for value in values):
                raise ValueError(f"{axis} values require a simulated or prescribed degree of freedom")
        return self


class MotionTugState(MotionEvidence):
    measurement_fields = ("position", "heading_true_deg", "velocity", "acceleration", "commanded_force",
                          "actual_force", "contact_position", "mode", "contact_state", "capacity_utilization_pct")

    tug_id: str = Field(min_length=1)
    position: BerthPosition | None = None
    heading_true_deg: float | None = Field(default=None, ge=0, lt=360)
    velocity: BerthVelocity | None = None
    acceleration: BerthAcceleration | None = None
    commanded_force: BerthForce | None = Field(default=None, description="Commanded force on the ship, berth axes.")
    actual_force: BerthForce | None = Field(default=None, description="Actual force on the ship, berth axes.")
    push_point_id: str | None = None
    contact_position: BerthPosition | None = None
    mode: Literal["push", "pull", "standby", "unknown"] = "unknown"
    contact_state: Literal["contact", "no_contact", "line_made_up", "unknown"] = "unknown"
    capacity_utilization_pct: float | None = Field(default=None, ge=0, description="Supplied value; may exceed 100.")


class MotionEnvironmentComponent(MotionEvidence):
    metadata: EnvironmentMetadata | None = None


class MotionWind(MotionEnvironmentComponent):
    measurement_fields = ("speed_kt", "gust_kt", "from_true_deg")
    speed_kt: float | None = Field(default=None, ge=0)
    gust_kt: float | None = Field(default=None, ge=0)
    from_true_deg: float | None = Field(default=None, ge=0, lt=360)


class MotionCurrent(MotionEnvironmentComponent):
    measurement_fields = ("speed_kt", "set_true_deg")
    speed_kt: float | None = Field(default=None, ge=0)
    set_true_deg: float | None = Field(default=None, ge=0, lt=360)


class MotionWaterLevel(MotionEnvironmentComponent):
    measurement_fields = ("level_mllw_ft",)
    level_mllw_ft: float | None = None


class MotionWaveComponent(MotionEnvironmentComponent):
    """One wave/wake source; never an aggregate of unlike mechanisms."""

    measurement_fields = ("height_ft", "period_s", "from_true_deg")
    height_ft: float | None = Field(default=None, ge=0)
    height_basis: Literal["significant", "crest_to_trough", "amplitude", "unknown"] = "unknown"
    period_s: float | None = Field(default=None, gt=0)
    period_basis: Literal["peak", "mean", "regular", "unknown"] = "unknown"
    from_true_deg: float | None = Field(default=None, ge=0, lt=360)


class MotionWaves(Model):
    ocean_swell: MotionWaveComponent | None = None
    local_chop: MotionWaveComponent | None = None
    ship_wake: MotionWaveComponent | None = None
    tug_wake: MotionWaveComponent | None = None


class MotionEnvironment(Model):
    t_s: float | None = Field(default=None, ge=0, description="Simulation time at which these forcing values apply.")
    valid_at_utc: AwareDatetime | None = Field(default=None, description="Absolute valid time if the run has a UTC epoch.")
    wind: MotionWind | None = None
    current: MotionCurrent | None = None
    water: MotionWaterLevel | None = None
    waves: MotionWaves | None = None


class MotionLineState(MotionEvidence):
    measurement_fields = ("tension_lbf", "status", "ship_end", "pier_end", "polyline")

    line_number: int = Field(ge=1)
    tension_lbf: float | None = Field(default=None, ge=0)
    status: Literal["slack", "taut", "overloaded", "unknown"] = "unknown"
    ship_fitting_id: str | None = None
    pier_fitting_id: str | None = None
    ship_end: BerthPosition | None = None
    pier_end: BerthPosition | None = None
    polyline: BerthPolyline | None = Field(default=None,
        description="Ship-to-pier straight segments through any chocks; no inferred catenary or sag. Empty means no geometry supplied.")

    @model_validator(mode="after")
    def endpoints_match_polyline(self):
        if self.polyline:
            if self.ship_end is not None and self.polyline[0] != self.ship_end:
                raise ValueError("polyline must start at ship_end")
            if self.pier_end is not None and self.polyline[-1] != self.pier_end:
                raise ValueError("polyline must end at pier_end")
        return self


class MotionFittingLoad(MotionEvidence):
    measurement_fields = ("load_lbf", "capacity_lbf", "utilization_pct", "force", "status")

    fitting_id: str = Field(min_length=1)
    owner: Literal["ship", "pier"]
    load_lbf: float | None = Field(default=None, ge=0)
    capacity_lbf: float | None = Field(default=None, gt=0)
    utilization_pct: float | None = Field(default=None, ge=0)
    force: BerthForce | None = None
    status: Status | None = None


class MotionFenderState(MotionEvidence):
    measurement_fields = ("compression_ft", "reaction_lbf", "force", "status")

    fender_id: str = Field(min_length=1)
    compression_ft: float | None = Field(default=None, ge=0)
    reaction_lbf: float | None = Field(default=None, ge=0)
    force: BerthForce | None = None
    status: Status | None = None


class MotionWrench(MotionEvidence):
    measurement_fields = ("force", "yaw_moment_ftlbf")

    force: BerthForce | None = None
    yaw_moment_ftlbf: float | None = Field(default=None,
        description="Moment about the instantaneous ship origin; positive counterclockwise viewed from above.")


class MotionWaveForces(Model):
    ocean_swell: MotionWrench | None = None
    local_chop: MotionWrench | None = None
    ship_wake: MotionWrench | None = None
    tug_wake: MotionWrench | None = None


class MotionForces(Model):
    """Forces on the ship in berth axes; all moments use the same instantaneous ship origin."""

    wind: MotionWrench | None = None
    current: MotionWrench | None = None
    waves: MotionWaveForces | None = None
    tugs: MotionWrench | None = None
    lines: MotionWrench | None = None
    fenders: MotionWrench | None = None


class MotionAlert(Model):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    severity: Severity
    message: str = Field(min_length=1)
    element_ids: list[str] = Field(default_factory=list, max_length=128)


class MotionSceneShipFitting(MotionEvidence):
    measurement_fields = ("position", "capacity_lbf")

    fitting_id: str = Field(min_length=1)
    position: ShipPoint
    kind: str | None = None
    capacity_lbf: float | None = Field(default=None, gt=0)


class MotionScenePierFitting(MotionEvidence):
    measurement_fields = ("position", "capacity_lbf")

    fitting_id: str = Field(min_length=1)
    position: BerthPosition
    kind: str | None = None
    capacity_lbf: float | None = Field(default=None, gt=0)


class MotionSceneFender(MotionEvidence):
    measurement_fields = ("position", "length_ft", "standoff_ft")

    fender_id: str = Field(min_length=1)
    position: BerthPosition
    length_ft: float | None = Field(default=None, gt=0)
    standoff_ft: float | None = Field(default=None, ge=0)


class MotionSceneDepth(MotionEvidence):
    measurement_fields = ("position", "depth_mllw_ft")

    position: BerthPosition
    depth_mllw_ft: float | None = Field(default=None, ge=0)


class SimScene(MotionEvidence):
    """Static scene fetched once. Producers publish a new revision whenever scene content changes."""

    measurement_fields = ("face_bearing_true_deg", "deck_height_mllw_ft", "berth_outline", "ship_hull_outline",
                          "ship_fittings", "pier_fittings", "fenders", "depth_profile")

    schema_version: Literal["rm0-v1"] = "rm0-v1"
    scene_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    berth_id: str = Field(min_length=1)
    ship_class_id: str = Field(min_length=1)
    loading: str = Field(min_length=1)
    face_bearing_true_deg: float | None = Field(default=None, ge=0, lt=360)
    deck_height_mllw_ft: float | None = Field(default=None, description="Fixed pier-deck elevation above MLLW.")
    ship_reference: str = Field(default="midships at the reference waterline",
                               description="Origin used by ship geometry and frame motion.")
    berth_outline: BerthOutline | None = None
    ship_hull_outline: ShipHullOutline | None = None
    ship_fittings: list[MotionSceneShipFitting] | None = Field(default=None, max_length=512)
    pier_fittings: list[MotionScenePierFitting] | None = Field(default=None, max_length=512)
    fenders: list[MotionSceneFender] | None = Field(default=None, max_length=512)
    depth_profile: list[MotionSceneDepth] | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def unique_scene_ids(self):
        for field, identifier in (("ship_fittings", "fitting_id"), ("pier_fittings", "fitting_id"),
                                  ("fenders", "fender_id")):
            values = getattr(self, field) or []
            ids = [getattr(value, identifier) for value in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{field} identifiers must be unique")
        return self


class SimSamplingPolicy(Model):
    physics_dt_s: float | None = Field(default=None, gt=0, description="Integrator step if fixed; rendering never controls it.")
    display_interval_s: float | None = Field(default=None, gt=0)
    max_pending_frames: int | None = Field(default=None, ge=1)
    slow_client_policy: Literal["drop_display_frames"] = "drop_display_frames"
    description: str = "Keep the newest display frame; never skip or slow physics. Sequence gaps disclose dropped frames."


class SimLifecycle(Model):
    """Server lifecycle metadata for the rm0-v1 session stream."""

    wire_omitted_defaults = {"speed": None}

    type: Literal["session_lifecycle"] = "session_lifecycle"
    schema_version: Literal["rm0-v1"] = "rm0-v1"
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1, description="Changes on reset; sequence remains monotonic for the session.")
    sequence: int = Field(ge=0, strict=True)
    t_s: float = Field(ge=0)
    state: Literal["created", "running", "paused", "reset", "ended", "error"]
    scene_id: str | None = None
    scene_revision: str | None = None
    message: str | None = None
    validity: Validity | None = None
    provenance: MotionProvenance | None = None
    speed: float | None = Field(default=None, gt=0, description="Current simulated seconds per wall second.")

    @model_validator(mode="after")
    def error_needs_message(self):
        if self.state == "reset" and self.t_s != 0:
            raise ValueError("reset lifecycle messages must start at simulation time zero")
        if self.state == "error" and (not self.message or not self.message.strip()):
            raise ValueError("error lifecycle messages need an explanation")
        if (self.scene_id is None) != (self.scene_revision is None):
            raise ValueError("scene_id and scene_revision must be supplied together")
        _require_qualified_motion(self)
        return self
