"""Mooring configurations, tug assignments and saved scenarios."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Model, SideTo

LineRole = Literal["bow", "breast", "spring_fwd", "spring_aft", "stern"]


class MooringLine(Model):
    """One mooring line. Lines are numbered forward to aft (NSTM 582-4.2.1)."""

    line_number: int = Field(ge=1)
    role: LineRole | None = Field(
        default=None,
        description="Computed from geometry when omitted. spring_fwd leads forward (stops the ship moving aft).",
    )
    spec_id: str = Field(examples=["NYLON-DB-7IN"])
    parts: Literal[1, 2, 3] = Field(default=1, description="1 = single, 2 = tanker moor, 3 = doubled up.")
    ship_fitting_id: str = Field(examples=["BITT-1S"])
    chock_id: str | None = Field(default=None, description="Defaults to the bitt's paired chock.")
    pier_fitting_id: str = Field(examples=["P12N-B16"])
    pretension_lbf: float | None = Field(default=None, ge=0)
    slack_ft: float | None = Field(default=None, ge=0)


class MooringConfig(Model):
    config_id: str | None = None
    side_to: SideTo
    ship_x_ft: float = Field(description="Berth-frame x of the ship's midships.")
    standoff_ft: float | None = Field(default=None, ge=0, description="Defaults to the berth's camel standoff.")
    lines: list[MooringLine]


class TugAssignment(Model):
    tug_id: str
    push_point_id: str
    mode: Literal["push", "pull", "standby"]
    force_lbf: float = Field(ge=0)
    direction_true_deg: float | None = Field(default=None, ge=0, lt=360)


class EnvSource(Model):
    mode: Literal["live", "replay", "forecast", "scenario", "mock"]
    env_scenario_id: str | None = None
    replay_start_utc: datetime | None = None
    replay_speed: float = Field(default=1.0, gt=0)


class ScenarioCreate(Model):
    """A saved setup: the UI's save file."""

    name: str
    ship_class_id: str
    loading: str = "full_load"
    berth_id: str
    side_to: SideTo
    env_source: EnvSource
    config: MooringConfig | None = None
    tugs: list[TugAssignment] = Field(default_factory=list)


class Scenario(ScenarioCreate):
    scenario_id: str
    created_at_utc: datetime


class ScenarioCreated(Model):
    scenario_id: str
