"""Bounded, session-state berthing prediction. This contract never asserts an all-clear."""

import math
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from .common import Model, Severity, Validity
from .dynamics import SimEvent, SimLineEventMessage, SimTugCommandMessage, SimulationTransition
from .motion import MotionPose, MotionVelocity
from .motion_controls import SimHelmCommandMessage, SimLineControlMessage, SimLoadingCommandMessage, SimTugMotionCommandMessage


MotionPredictionCommand = Annotated[
    SimHelmCommandMessage | SimTugCommandMessage | SimLineEventMessage
    | SimLineControlMessage | SimLoadingCommandMessage | SimTugMotionCommandMessage,
    Field(discriminator="type"),
]


class MotionPredictionRequest(Model):
    horizon_s: float = Field(default=60, ge=0.0001, le=120,
        description="At least the berthing integrator's minimum resolvable step; at most two minutes.")
    sample_interval_s: float = Field(default=1, ge=0.25, le=120,
        description="Display sampling only; the live model's integration step is preserved.")
    what_if_commands: list[MotionPredictionCommand] = Field(default_factory=list, max_length=32,
        description="Absolute simulation t_s, between snapshot time and requested horizon; omitted means snapshot time. "
                    "Applied after already scheduled commands at the same time, on the prediction clone only.")

    @model_validator(mode="after")
    def bounded_output(self):
        if math.ceil(self.horizon_s / self.sample_interval_s) + 1 > 481:
            raise ValueError("at most 481 prediction path points")
        return self


class MotionPredictionSource(Model):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    sequence: int = Field(ge=0, strict=True,
        description="Session sequence captured atomically with the model; t_s is authoritative if physics advanced since the last display.")
    scene_id: str = Field(min_length=1)
    scene_revision: str = Field(min_length=1)
    t_s: float = Field(ge=0)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$",
        description="Immutable content identity of the complete model snapshot, including queued commands and actuator state.")
    command_sequence: int = Field(ge=0)
    forcing_revision: str | None


class MotionPredictionPoint(Model):
    x_ft: float
    y_ft: float


class MotionPredictionPose(Model):
    t_s: float = Field(ge=0, description="Absolute simulation time, never arrival or wall-clock time.")
    elapsed_s: float = Field(ge=0)
    pose: MotionPose
    velocity: MotionVelocity
    footprint: list[MotionPredictionPoint] = Field(min_length=4, max_length=4,
        description="LOA × beam rectangle in berth axes, matching the parallel-side contact envelope; unqualified hull geometry.")
    pier_clearance_ft: float | None = Field(ge=0,
        description="Minimum sampled/swept clearance since the preceding display tick; initial point checks the initial hull.")
    fender_clearance_ft: float | None = Field(ge=0)


class MotionPredictionWarning(Model):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    severity: Severity
    message: str
    t_s: float | None = Field(default=None, ge=0)
    element_id: str | None = None


class MotionPredictionUncertainty(Model):
    availability: Literal["unavailable"] = "unavailable"
    corridor: None = None
    reason: str = "No calibrated trajectory uncertainty model is available; deterministic footprints are not a safe corridor."


class MotionPredictionWork(Model):
    integration_steps: int = Field(ge=0)
    commands_applied: int = Field(ge=0)
    work_limit: int = Field(ge=1)
    integration_dt_s: float = Field(gt=0)
    runtime_limit_s: float = Field(gt=0)


class MotionPredictionResponse(Model):
    schema_version: Literal["motion-prediction-v1"] = "motion-prediction-v1"
    prediction_id: str
    source: MotionPredictionSource
    engine: Literal["berthing"] = "berthing"
    requested_horizon_s: float = Field(gt=0)
    horizon_s: float = Field(ge=0, description="Actual completed horizon; a truncated prediction never covers the missing tail.")
    complete: bool
    path: list[MotionPredictionPose] = Field(min_length=1, max_length=481)
    transitions: list[SimulationTransition] = Field(max_length=512)
    events: list[SimEvent] = Field(max_length=256)
    warnings: list[MotionPredictionWarning] = Field(max_length=128)
    hazards_checked: list[str]
    hazards_unchecked: list[str]
    uncertainty: MotionPredictionUncertainty = Field(default_factory=MotionPredictionUncertainty)
    validity: Validity
    status: Literal["AMBER", "RED"]
    work: MotionPredictionWork

    @model_validator(mode="after")
    def honest_result(self):
        if self.validity.state not in ("limited", "invalid"):
            raise ValueError("session prediction is always limited or invalid")
        if self.validity.state == "invalid" and self.status != "RED":
            raise ValueError("invalid prediction requires RED status")
        if self.path[0].t_s != self.source.t_s or self.path[0].elapsed_s != 0:
            raise ValueError("prediction must begin at its source snapshot")
        if any(b.t_s <= a.t_s for a, b in zip(self.path, self.path[1:])):
            raise ValueError("prediction times must increase")
        if any(not math.isclose(p.t_s-self.source.t_s, p.elapsed_s, abs_tol=1e-8) for p in self.path):
            raise ValueError("elapsed time must be relative to the source snapshot")
        if not math.isclose(self.path[-1].elapsed_s, self.horizon_s, abs_tol=1e-8):
            raise ValueError("last path point must report the completed horizon")
        if self.horizon_s > self.requested_horizon_s+1e-8:
            raise ValueError("completed horizon cannot exceed requested horizon")
        if self.complete and not math.isclose(self.horizon_s, self.requested_horizon_s, abs_tol=1e-8):
            raise ValueError("complete prediction must cover its requested horizon")
        return self
