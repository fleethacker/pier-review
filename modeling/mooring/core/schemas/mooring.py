"""Static mooring analysis schemas (module M4) and the NSTM 582 rule registry."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Envelope, Finding, Model, MooringServiceType, Severity, Status
from .environment import EnvironmentSnapshot
from .plans import LineRole, MooringConfig, TugAssignment


class AnalyzeRequest(Model):
    scenario_id: str | None = Field(default=None, description="Informational; inputs are always taken from the body.")
    ship_class_id: str = Field(examples=["DDG-51-FIIA"])
    loading: str = "full_load"
    berth_id: str = Field(examples=["NAVSTA-NORFOLK-P12-N"])
    config: MooringConfig
    environment: EnvironmentSnapshot
    tugs: list[TugAssignment] = Field(default_factory=list)
    mst: MooringServiceType = Field(default="II", description="Sets the design factor: 3.0 (I, II, IIA) or 2.5 (III).")
    lines_wet: bool = Field(default=True, description="Apply the wet-strength factor (nylon loses 15%).")


class Offset(Model):
    surge_ft: float
    sway_ft: float = Field(description="Positive = away from the pier.")
    yaw_deg: float


class LineResult(Model):
    line_number: int
    role: LineRole
    tension_lbf: float
    pct_mbs: float
    pct_wll: float
    horiz_angle_deg: float = Field(description="Angle from perpendicular to the ship; breast lines are under 45.")
    vert_angle_deg: float
    breast_efficiency: float = Field(description="cos(horizontal angle): share of tension that holds the ship in.")
    length_ft: float
    status: Status


class PierFittingResult(Model):
    fitting_id: str
    load_lbf: float
    capacity_lbf: float
    pct: float
    lines: list[int]
    status: Status


class ShipFittingResult(Model):
    fitting_id: str
    load_lbf: float
    swl_lbf: float | None
    pct: float | None
    lines: list[int]
    status: Status


class FenderResult(Model):
    fender_id: str
    reaction_lbf: float
    compression_ft: float
    status: Status


class MinMargin(Model):
    element_id: str = Field(examples=["line-2"])
    pct_wll: float = Field(description="Highest utilization in the plan (lines and fittings).")


class AnalyzeResult(Model):
    offset: Offset
    lines: list[LineResult]
    pier_fittings: list[PierFittingResult]
    ship_fittings: list[ShipFittingResult]
    fenders: list[FenderResult]
    min_margin: MinMargin
    findings: list[Finding]


class AnalyzeResponse(Envelope[AnalyzeResult]):
    pass


class LimitEnvelopeRequest(AnalyzeRequest):
    step_deg: int = Field(default=15, ge=5, le=90)


class LimitEnvelopePoint(Model):
    wind_rel_deg: float
    limit_wind_kt: float | None = Field(description="None when wind from this direction loads only the fenders.")
    first_failure_element: str | None
    failure_mode: Literal["WLL", "MBS", "fitting", "none"]


class LimitEnvelopeResult(Model):
    points: list[LimitEnvelopePoint]
    worst: LimitEnvelopePoint


class LimitEnvelopeResponse(Envelope[LimitEnvelopeResult]):
    pass


class TideSweepRequest(AnalyzeRequest):
    from_utc: datetime
    to_utc: datetime
    step_min: int = Field(default=30, ge=5, le=180)


class LineTension(Model):
    line_number: int
    tension_lbf: float


class TideStep(Model):
    valid_at_utc: datetime
    water_level_mllw_ft: float
    lines: list[LineTension]


class TendingAction(Model):
    at_utc: datetime
    line_number: int
    action: Literal["slack", "heave"]
    amount_ft: float


class TideSweepResult(Model):
    steps: list[TideStep]
    tending: list[TendingAction]


class TideSweepResponse(Envelope[TideSweepResult]):
    pass


class Rule(Model):
    rule_id: str
    title: str
    severity: Severity = Field(description="Highest severity the rule can raise.")
    reference: str
    applies_to: Literal["line", "pier_fitting", "ship_fitting", "plan", "environment", "sequence", "berthing"]
    implemented: bool = Field(description="False while the check exists only as registry metadata.")
    coverage: Literal["implemented", "partial", "unsupported"] | None = Field(
        default=None, description="Audit of how much of the cited requirement the code checks (S01)."
    )
    applicability: str | None = Field(default=None, description="Where the rule is meant to apply; limits of the check.")
    source_verified: bool = Field(
        default=False, description="True only after the paragraph/table was checked against the edition in hand."
    )
