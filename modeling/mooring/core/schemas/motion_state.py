"""Explicit local-frame state evidence; importing a sensor label does not connect hardware."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, field_validator, model_validator

from .common import Model


class _Frozen(Model):
    model_config = ConfigDict(frozen=True)


class MotionMeasuredAcceleration(_Frozen):
    """Measured inertial acceleration expressed in body axes; never inferred force."""

    surge_fps2: float | None = Field(default=None, strict=True, ge=-100, le=100)
    sway_fps2: float | None = Field(default=None, strict=True, ge=-100, le=100)
    yaw_degps2: float | None = Field(default=None, strict=True, ge=-360, le=360,
        description="Counterclockwise yaw angular acceleration.")


class MotionStateInput(_Frozen):
    """Complete planar observation in an explicitly declared berth frame.

    Bounds protect the adapter; they are not vessel operating limits. Velocities
    are relative to ground, expressed in the entity's forward/port body axes.
    """

    entity: Literal["ship", "tug"]
    entity_id: str = Field(strict=True, min_length=1, max_length=120, pattern=r"^\S+$")
    frame: Literal["berth"]
    berth_id: str = Field(strict=True, min_length=1, max_length=120, pattern=r"^\S+$")
    source: Literal["synthetic", "recorded", "sensor"]
    source_name: str | None = Field(default=None, strict=True, min_length=1, max_length=240, pattern=r"\S")
    observed_at_utc: AwareDatetime
    sequence: int = Field(strict=True, ge=0, le=9_007_199_254_740_991,
        description="Strictly increasing per entity; changing source label does not reset it.")
    x_ft: float = Field(strict=True, ge=-1_000_000, le=1_000_000, description="Entity reference point, along the berth face.")
    y_ft: float = Field(strict=True, ge=-1_000_000, le=1_000_000, description="Entity reference point, positive off-pier.")
    heading_true_deg: float = Field(strict=True, ge=0, lt=360, description="Clockwise true heading of the entity's forward axis.")
    surge_fps: float = Field(strict=True, ge=-200, le=200, description="Ground velocity, positive forward in entity axes.")
    sway_fps: float = Field(strict=True, ge=-200, le=200, description="Ground velocity, positive port in entity axes.")
    yaw_degps: float = Field(strict=True, ge=-180, le=180,
        description="Positive counterclockwise about +up; not clockwise compass-heading rate.")
    measured_acceleration: MotionMeasuredAcceleration | None = None
    quality: Literal["good", "suspect", "invalid", "unknown"] | None = None

    @field_validator("observed_at_utc", mode="before")
    @classmethod
    def explicit_datetime(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("observed_at_utc must be an aware ISO timestamp, not an inferred numeric epoch")
        return value


class MotionStatePolicy(_Frozen):
    max_age_s: float = Field(default=30, strict=True, gt=0, le=86400)
    future_tolerance_s: float = Field(default=0, strict=True, ge=0, le=5,
        description="Explicit clock-skew allowance; default rejects future-dated input.")
    allow_suspect: bool = Field(default=False, strict=True)


class MotionStateVector(_Frozen):
    """The model's six-component state. Measured acceleration is intentionally absent."""

    x_ft: float
    y_ft: float
    yaw_rad: float = Field(description="Counterclockwise from berth +x, wrapped to [-pi, pi).")
    surge_fps: float
    sway_fps: float
    yaw_radps: float

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return self.x_ft, self.y_ft, self.yaw_rad, self.surge_fps, self.sway_fps, self.yaw_radps


class MotionStateSnapshot(_Frozen):
    """Frozen acceptance evidence and new run context; no session is mutated by its preparation."""

    schema_version: Literal["motion-state-v1"] = "motion-state-v1"
    snapshot_id: str
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$", description="Canonical supplied observation identity, including source and acceleration evidence.")
    session_id: str = Field(min_length=1, max_length=160)
    previous_run_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    simulation_time_s: float = Field(ge=0, le=7200,
        description="Simulation time retained at reseed; observation wall time stays separate and is never extrapolated.")
    accepted_at_utc: AwareDatetime
    age_s: float = Field(description="Acceptance clock minus observation time; negative only within explicit clock-skew tolerance.")
    input: MotionStateInput
    state: MotionStateVector
    policy: MotionStatePolicy = Field(description="Exact freshness/quality policy under which this input was accepted.")
    qualification: Literal["unqualified"] = "unqualified"
    limitations: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def new_run_context(self):
        if self.previous_run_id == self.run_id:
            raise ValueError("state reseeding must change the run identity")
        return self

    def as_integrator_state(self) -> tuple[float, float, float, float, float, float]:
        return self.state.as_tuple()
