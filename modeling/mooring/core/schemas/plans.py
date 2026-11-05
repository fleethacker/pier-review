"""Mooring configurations, tug assignments and saved scenarios."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .common import Model, SideTo

LineRole = Literal["bow", "breast", "spring_fwd", "spring_aft", "stern"]


class MooringLine(Model):
    """One mooring line. Lines are numbered forward to aft (NSTM 582-4.2.1)."""

    wire_omitted_defaults = {"paid_out_unstretched_length_ft": None, "condition": None}

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
    pretension_lbf: float | None = Field(
        default=None, ge=0,
        description="Initial tension. Legacy default when omitted: 2% of effective MBS (0 if slack_ft > 0). "
        "Mutually exclusive with a positive slack_ft: a slack line carries no tension.",
    )
    slack_ft: float | None = Field(
        default=None, ge=0, description="Extra line length beyond the straight-line distance, in feet of stretched length."
    )
    paid_out_unstretched_length_ft: float | None = Field(
        default=None, gt=0,
        description="Unstretched length paid out between fittings. Used directly as the installed rest length by the M4 "
        "equilibrium solver. Cannot be combined with slack_ft or pretension_lbf.",
    )
    condition: Literal["wet", "dry"] | None = Field(
        default=None,
        description="Strength condition for this line (wet applies the spec's wet-strength factor). When omitted the "
        "request's lines_wet applies (legacy).",
    )

    @model_validator(mode="after")
    def _tension_semantics(self):
        if self.pretension_lbf and self.slack_ft:
            raise ValueError("pretension_lbf and slack_ft conflict: a slack line carries no tension; send only one")
        if self.paid_out_unstretched_length_ft is not None and self.slack_ft:
            raise ValueError("paid_out_unstretched_length_ft and slack_ft both define line length; send only one")
        return self


class MooringConfig(Model):
    config_id: str | None = None
    side_to: SideTo
    ship_x_ft: float = Field(description="Berth-frame x of the ship's midships.")
    standoff_ft: float | None = Field(default=None, ge=0, description="Defaults to the berth's camel standoff.")
    lines: list[MooringLine] = Field(description="Lines with unique line_number identifiers; gaps in numbering are permitted.")

    @model_validator(mode="after")
    def _unique_line_numbers(self):
        numbers = [line.line_number for line in self.lines]
        if len(numbers) != len(set(numbers)):
            raise ValueError("line_number must be unique within a mooring configuration")
        return self


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

    @model_validator(mode="after")
    def _mode_fields(self):
        if self.mode == "scenario" and not self.env_scenario_id:
            raise ValueError("mode 'scenario' needs env_scenario_id")
        if self.mode != "scenario" and self.env_scenario_id:
            raise ValueError("env_scenario_id conflicts with mode '%s'; use mode 'scenario'" % self.mode)
        return self


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

    @model_validator(mode="after")
    def _side_agrees(self):
        if self.config is not None and self.config.side_to != self.side_to:
            raise ValueError(f"side_to '{self.side_to}' conflicts with config.side_to '{self.config.side_to}'")
        return self


class Scenario(ScenarioCreate):
    scenario_id: str
    created_at_utc: datetime


class ScenarioCreated(Model):
    scenario_id: str
