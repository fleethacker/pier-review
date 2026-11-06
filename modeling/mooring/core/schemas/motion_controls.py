"""Opt-in demonstration controls. Every engineering coefficient is supplied explicitly.

These inputs cannot qualify a vessel. ``synthetic`` identifies authored demonstration
assumptions; ``supplied`` identifies caller data without claiming verification.
"""
from typing import Literal

from pydantic import Field, model_validator

from .common import Model, Validity


class ParameterEvidence(Model):
    basis: Literal["synthetic", "supplied"]
    source: str = Field(min_length=1, max_length=500)


class PropulsionSpec(ParameterEvidence):
    max_ahead_thrust_lbf: float = Field(gt=0, description="Per shaft.")
    max_astern_thrust_lbf: float = Field(ge=0, description="Per shaft.")
    shaft_x_ft: float
    shaft_y_ft: float = Field(ge=0, description="Port shaft +y; starboard shaft -y.")
    engine_slew_per_s: float = Field(gt=0)
    rudder_x_ft: float
    rudder_area_ft2: float = Field(ge=0)
    rudder_lift_slope_per_rad: float = Field(ge=0)
    rudder_max_lift_coefficient: float = Field(ge=0)
    rudder_max_force_lbf: float = Field(ge=0)
    rudder_max_deg: float = Field(gt=0, le=45)
    rudder_slew_degps: float = Field(gt=0)
    propwash_fps_at_full_ahead: float = Field(ge=0)
    bow_thruster_x_ft: float
    bow_thruster_max_lbf: float = Field(ge=0)
    stern_thruster_x_ft: float
    stern_thruster_max_lbf: float = Field(ge=0)
    thruster_slew_per_s: float = Field(gt=0)
    water_density_slug_ft3: float = Field(gt=0)


class PayloadItem(Model):
    payload_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    weight_lbf: float = Field(ge=0, le=1e9)
    x_ft: float = Field(ge=-10000, le=10000)
    y_ft: float = Field(ge=-10000, le=10000)
    z_ft: float = Field(ge=-1000, le=1000, description="Ship reference waterline origin, +up.")


class LocalDepthPatch(ParameterEvidence):
    """A supplied constant-depth patch, never an extrapolated berth profile."""
    depth_mllw_ft: float = Field(gt=0)
    uncertainty_ft: float | None = Field(default=None, ge=0)
    x_min_ft: float
    x_max_ft: float
    y_min_ft: float
    y_max_ft: float

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.x_max_ft <= self.x_min_ft or self.y_max_ft <= self.y_min_ft:
            raise ValueError("depth patch needs ordered nonempty bounds")
        return self


class LoadingSpec(ParameterEvidence):
    base_mass_slug: float = Field(gt=0)
    base_izz_slug_ft2: float = Field(gt=0, description="Baseline inertia about baseline CG.")
    base_cg_x_ft: float
    base_cg_y_ft: float
    base_cg_z_ft: float
    base_draft_ft: float = Field(gt=0)
    base_cb_z_ft: float = Field(description="Baseline center of buoyancy, ship reference waterline origin.")
    waterplane_area_ft2: float = Field(gt=0, description="Fixed waterplane centered at the ship origin.")
    waterplane_ixx_ft4: float = Field(gt=0)
    waterplane_iyy_ft4: float = Field(gt=0)
    water_density_slug_ft3: float = Field(gt=0)
    gravity_fps2: float = Field(gt=0)
    added_surge_slug: float = Field(ge=0)
    added_sway_slug: float = Field(ge=0)
    added_yaw_slug_ft2: float = Field(ge=0)
    damping_surge_lbf_per_fps: float = Field(ge=0)
    damping_sway_lbf_per_fps: float = Field(ge=0)
    damping_yaw_ftlbf_per_radps: float = Field(ge=0)
    max_abs_attitude_deg: float = Field(gt=0, le=10, description="Small-angle model validity boundary, not a stability limit.")
    max_sinkage_fraction: float = Field(gt=0, le=0.25, description="Fraction of baseline draft; numerical model boundary.")
    payloads: list[PayloadItem] = Field(default_factory=list, max_length=64)
    local_depth: LocalDepthPatch | None = None

    @model_validator(mode="after")
    def unique_payloads(self):
        if len({p.payload_id for p in self.payloads}) != len(self.payloads):
            raise ValueError("payload identifiers must be unique")
        return self


class MotionControlsConfig(Model):
    propulsion: PropulsionSpec
    loading: LoadingSpec
    tug_standoff_ft: float | None = Field(default=None, gt=0,
        description="Explicit synthetic rigid attachment stand-off; absent leaves tug kinematics unavailable.")
    tug_slew_s: float | None = Field(default=None, gt=0,
        description="Explicit synthetic tug force ramp time; absent retains legacy demonstration ramp.")


class HelmOrder(Model):
    """Positive rudder means bow to starboard in ahead flow; thrusters are +port."""
    port_throttle: float = Field(ge=-1, le=1)
    starboard_throttle: float = Field(ge=-1, le=1)
    rudder_deg: float = Field(ge=-45, le=45)
    bow_thruster: float = Field(ge=-1, le=1)
    stern_thruster: float = Field(ge=-1, le=1)


class SimHelmCommandMessage(HelmOrder):
    wire_omitted_defaults = {"t_s": None}
    type: Literal["helm_command"]
    t_s: float | None = Field(default=None, ge=0)


class SimLoadingCommandMessage(Model):
    """Replace payload inventory at rest; changing mass during motion is unsupported."""
    wire_omitted_defaults = {"t_s": None}
    type: Literal["loading_command"]
    t_s: float | None = Field(default=None, ge=0)
    payloads: list[PayloadItem] = Field(max_length=64)

    @model_validator(mode="after")
    def unique_payloads(self):
        if len({p.payload_id for p in self.payloads}) != len(self.payloads):
            raise ValueError("payload identifiers must be unique")
        return self


class SimLineControlMessage(Model):
    wire_omitted_defaults = {"t_s": None, "attached": None, "paid_out_length_ft": None}
    type: Literal["line_control"]
    t_s: float | None = Field(default=None, ge=0)
    line_number: int
    attached: bool | None = None
    paid_out_length_ft: float | None = Field(default=None, gt=0, le=10000)

    @model_validator(mode="after")
    def has_change(self):
        if self.attached is None and self.paid_out_length_ft is None:
            raise ValueError("line_control needs attachment or paid-out length")
        return self


class MotionActuatorForce(Model):
    """Application position and force in berth axes; moment about ship origin."""
    actuator_id: Literal["port_engine", "starboard_engine", "rudder", "bow_thruster", "stern_thruster"]
    x_ft: float
    y_ft: float
    x_lbf: float
    y_lbf: float
    yaw_moment_ftlbf: float


class MotionControlState(Model):
    basis: Literal["synthetic", "supplied"]
    source: str
    commanded: HelmOrder
    actual: HelmOrder
    port_thrust_lbf: float
    starboard_thrust_lbf: float
    rudder_force_lbf: float
    bow_thruster_force_lbf: float
    stern_thruster_force_lbf: float
    surge_force_lbf: float
    sway_force_lbf: float
    yaw_moment_ftlbf: float
    actuators: list[MotionActuatorForce] = Field(default_factory=list)
    validity: Validity


class MotionLoadingState(Model):
    basis: Literal["synthetic", "supplied"]
    source: str
    payloads: list[PayloadItem]
    total_mass_slug: float
    total_weight_lbf: float
    cg_x_ft: float
    cg_y_ft: float
    cg_z_ft: float
    izz_cg_slug_ft2: float
    izz_origin_slug_ft2: float
    sinkage_ft: float
    mean_draft_ft: float
    draft_fwd_ft: float
    draft_aft_ft: float
    maximum_draft_ft: float
    roll_deg: float
    pitch_deg: float
    gm_transverse_ft: float
    gm_longitudinal_ft: float
    local_depth_mllw_ft: float | None
    depth_uncertainty_ft: float | None
    under_keel_ft: float | None
    under_keel_lower_ft: float | None
    validity: Validity


class MotionLineControlState(Model):
    line_number: int
    attached: bool
    paid_out_length_ft: float
    geometric_length_ft: float
    extension_ft: float
    tension_lbf: float | None
