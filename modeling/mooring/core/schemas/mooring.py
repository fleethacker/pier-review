"""Static mooring analysis schemas (module M4) and the NSTM 582 rule registry."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from .common import Envelope, Finding, Model, MooringServiceType, Severity, Status
from .environment import EnvironmentSnapshot
from .plans import LineRole, MooringConfig, TugAssignment


class AnalyzeRequest(Model):
    wire_omitted_defaults = {"installed_at_water_level_mllw_ft": None}

    scenario_id: str | None = Field(default=None, description="Informational; inputs are always taken from the body.")
    ship_class_id: str = Field(examples=["DDG-51-FIIA"])
    loading: str = "full_load"
    berth_id: str = Field(examples=["NAVSTA-NORFOLK-P12-N"])
    config: MooringConfig
    environment: EnvironmentSnapshot
    tugs: list[TugAssignment] = Field(default_factory=list)
    mst: MooringServiceType = Field(default="II", description="Sets the design factor: 3.0 (I, II, IIA) or 2.5 (III).")
    lines_wet: bool = Field(default=True, description="Apply the wet-strength factor (nylon loses 15%).")
    installed_at_water_level_mllw_ft: float | None = Field(
        default=None,
        description="Water level when the lines were installed and pretensioned. Defaults to environment.water_level_mllw_ft "
        "(lines installed at the analysis water level). A different value keeps rest lengths from that state.",
    )


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
    horiz_angle_deg: float = Field(description="Angle from perpendicular to the ship at the solved pose, including yaw; breast lines are under 45.")
    vert_angle_deg: float = Field(description="Solved line angle above horizontal at the assessed water level.")
    breast_efficiency: float = Field(description="cos(horizontal angle): share of tension that holds the ship in.")
    length_ft: float = Field(description="Straight span between lead point and pier fitting at the solved pose; not unstretched paid-out length.")
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
    wire_omitted_defaults = {"energy_ftlbf": None, "pct_rated_energy": None}

    fender_id: str
    reaction_lbf: float
    compression_ft: float
    status: Status
    energy_ftlbf: float | None = Field(default=None, description="Energy absorbed, integral of force over deflection.")
    pct_rated_energy: float | None = Field(default=None, description="Absorbed / rated energy x 100, when a rating exists.")


class MinMargin(Model):
    element_id: str = Field(examples=["line-2"])
    pct_wll: float = Field(description="Highest utilization in the plan (lines and fittings).")


class AnalyzeResult(Model):
    wire_omitted_defaults = {"resolved_config": None}
    resolved_config: MooringConfig | None = Field(default=None,
        description="Configuration with modeled unstretched spans and wet/dry conditions explicit for reproducible rechecks. Not rope-cutting lengths, a handling instruction or approval.")
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
    wire_omitted_defaults = {**AnalyzeRequest.wire_omitted_defaults, **AnalyzeRequest.wire_omitted_defaults, "max_search_kt": 100.0, "sampling_step_kt": 5.0, "tolerance_kt": 0.25}

    step_deg: int = Field(default=15, ge=5, le=90)
    max_search_kt: float = Field(default=100.0, ge=10, le=200, description="Highest wind speed searched. No failure up to here is reported as such, not as unlimited.")
    sampling_step_kt: float = Field(default=5.0, gt=0, le=20, description="Coarse scan interval; failures narrower than this can be missed.")
    tolerance_kt: float = Field(default=0.25, gt=0, le=5, description="Bisection tolerance once a crossing is bracketed.")


LimitOutcome = Literal["limit_found", "fails_at_zero_wind", "no_failure_in_range", "undetermined", "invalid_inputs"]


class LimitEnvelopePoint(Model):
    wire_omitted_defaults = {"outcome": None, "bracket_kt": None, "search_max_kt": None, "undetermined_at_kt": None, "nonmonotone_in_bracket": None, "limit_gust_kt": None, "advisory_gust_kt": None}

    wind_rel_deg: float
    limit_wind_kt: float | None = Field(
        description="Highest wind speed verified within limits (conservative end of the bracket). None unless outcome is "
        "'limit_found' or 'fails_at_zero_wind' (then 0).")
    limit_gust_kt: float | None = Field(default=None, description="Corresponding gust at limit_wind_kt under the request's held gust/sustained ratio; not a breaking limit.")
    advisory_gust_kt: float | None = Field(default=None, description="Application advisory at 80% of the computed gust limit; not a physical failure threshold.")
    first_failure_element: str | None
    failure_mode: Literal["WLL", "MBS", "fitting", "fender", "none"]
    outcome: LimitOutcome | None = Field(default=None, description="Absent on legacy responses.")
    bracket_kt: list[float] | None = Field(default=None, description="[highest OK speed, lowest failing speed] after refinement.")
    search_max_kt: float | None = None
    undetermined_at_kt: float | None = Field(default=None, description="Speed where the solve failed before any capacity failure was found.")
    nonmonotone_in_bracket: bool | None = Field(default=None, description="True if samples inside the bracket were not monotone.")


class LimitEnvelopeResult(Model):
    points: list[LimitEnvelopePoint]
    worst: LimitEnvelopePoint


class LimitEnvelopeResponse(Envelope[LimitEnvelopeResult]):
    pass


class TendingInput(Model):
    """An explicit tending action applied to a line's installed rest length from `at_utc` onward."""

    at_utc: datetime
    line_number: int = Field(ge=1)
    action: Literal["slack", "heave"] = Field(description="slack lengthens the rest length, heave shortens it.")
    amount_ft: float = Field(gt=0)


class TideSweepRequest(AnalyzeRequest):
    wire_omitted_defaults = {**AnalyzeRequest.wire_omitted_defaults, "tending": [], "water_level_forecast": None}

    from_utc: datetime
    to_utc: datetime
    step_min: int = Field(default=30, ge=5, le=180)
    tending: list[TendingInput] = Field(default_factory=list, description="Explicit tending applied in time order. Nothing is retensioned silently.")
    water_level_forecast: list[EnvironmentSnapshot] | None = Field(default=None, min_length=2, max_length=2000,
        description="Optional supplied snapshots covering the whole sweep; only MLLW water levels vary. Linear interpolation is explicitly limited. Absent uses a labeled synthetic training tide.")

    @model_validator(mode="after")
    def time_coverage(self):
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.from_utc, self.to_utc)):
            raise ValueError("Tide sweep times require explicit timezones")
        if not self.from_utc < self.to_utc <= self.from_utc + timedelta(hours=120):
            raise ValueError("Tide sweep duration must be positive and no longer than 120 hours")
        for action in self.tending:
            if action.at_utc.tzinfo is None or not self.from_utc <= action.at_utc <= self.to_utc:
                raise ValueError("Tending timestamps must lie within the sweep and include a timezone")
        if self.water_level_forecast is not None:
            times = [sample.valid_at_utc for sample in self.water_level_forecast]
            if any(t.tzinfo is None or t.utcoffset() is None for t in times):
                raise ValueError("Water-level sample times require explicit timezones")
            if any(b <= a for a, b in zip(times, times[1:])):
                raise ValueError("Water-level sample times must be strictly increasing")
            if times[0] > self.from_utc or times[-1] < self.to_utc:
                raise ValueError("Water-level samples must cover the entire sweep; no extrapolation")
        return self



class LineTension(Model):
    line_number: int
    tension_lbf: float


class TideStep(Model):
    wire_omitted_defaults = {"valid": None, "max_pct_wll": None}

    valid_at_utc: datetime
    water_level_mllw_ft: float
    lines: list[LineTension]
    valid: bool | None = Field(default=None, description="False when this step's equilibrium solve failed; lines is then empty.")
    max_pct_wll: float | None = None


class TendingAction(Model):
    at_utc: datetime
    line_number: int
    action: Literal["slack", "heave"]
    amount_ft: float


class LineExtreme(Model):
    line_number: int
    max_tension_lbf: float
    max_at_utc: datetime
    max_pct_wll: float
    min_tension_lbf: float
    min_at_utc: datetime


class TideSweepResult(Model):
    steps: list[TideStep]
    tending: list[TendingAction] = Field(description="Recommended actions (not applied) to restore each line's installed tension, at time_resolution_min resolution.")
    time_resolution_min: float | None = Field(default=None, description="Internal evaluation interval; extremes between reported steps are captured at this resolution.")
    line_extremes: list[LineExtreme] | None = None
    applied_tending: list[TendingAction] | None = Field(default=None, description="The explicit tending inputs that were applied.")


class TideSweepResponse(Envelope[TideSweepResult]):
    pass


class Rule(Model):
    wire_omitted_defaults = {"coverage": None, "applicability": None}

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
