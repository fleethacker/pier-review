"""Configuration optimizer and line sequence schemas (module M7)."""

from typing import Literal

from pydantic import Field, model_validator

from .common import Envelope, Model, MooringServiceType, SideTo
from .environment import EnvironmentSnapshot
from .plans import MooringConfig, MooringLine, TugAssignment
from .refdata import LineInventoryItem


class RecommendRequest(Model):
    wire_omitted_defaults = {"max_evaluations": 1500, "neighbors_per_line": 3, "tide_levels_ft": [0.0], "tugs": [], "design_basis": None, "standoff_ft": None}

    ship_class_id: str = Field(examples=["DDG-51-FIIA"])
    loading: str = "full_load"
    berth_id: str
    side_to: SideTo
    ship_x_ft: float | None = Field(default=None, description="Defaults to the middle of the berth face.")
    design_mst: MooringServiceType = "II"
    design_basis: Literal["mst_and_forecast", "forecast_only"] | None = Field(default=None,
        description="Absent means mst_and_forecast. forecast_only checks supplied conditions, not MST design compliance. Strength factors still use design_mst.")
    tugs: list[TugAssignment] = Field(default_factory=list, max_length=12,
        description="Fixed holding assistance evaluated in every case; not an autonomous tug schedule.")
    standoff_ft: float | None = Field(default=None, ge=0)
    forecast_env: list[EnvironmentSnapshot] = Field(
        default_factory=list, description="Extra conditions to check besides the MST design condition."
    )
    available_lines: list[LineInventoryItem] = Field(default_factory=list, description="Defaults to the ship's outfit.")
    locked_lines: list[MooringLine] = Field(default_factory=list)
    excluded_fitting_ids: list[str] = Field(default_factory=list)
    max_candidates: int = Field(default=3, ge=1, le=10)
    max_evaluations: int = Field(default=1500, ge=1, le=20000, description="Search budget in candidate evaluations. Exceeding the space is exhaustive; otherwise the search is bounded and says so.")
    neighbors_per_line: int = Field(default=3, ge=1, le=6, description="Pier fittings considered per line, nearest first.")
    tide_levels_ft: list[float] = Field(default_factory=lambda: [0.0], min_length=1, max_length=5, description="Water levels (MLLW) every case is evaluated at; lines are installed at the first.")


    @model_validator(mode="after")
    def forecast_basis_requires_conditions(self):
        if self.design_basis == "forecast_only" and not self.forecast_env:
            raise ValueError("forecast_only requires forecast_env")
        return self


class Candidate(Model):
    wire_omitted_defaults = {"feasible": None, "worst_case": None, "cases_evaluated": None, "tugs": []}

    config: MooringConfig
    min_margin_pct_wll: float = Field(description="Highest utilization over every evaluated case (lower is better).")
    limit_wind_kt_worst: float | None
    line_count: int
    analysis_result_id: str
    why: list[str]
    tugs: list[TugAssignment] = Field(default_factory=list, description="Holding assistance used in every candidate evaluation.")
    feasible: bool | None = Field(default=None, description="True when every case solved and stayed within every line, fitting and fender limit.")
    worst_case: str | None = None
    cases_evaluated: int | None = None


class SearchDiagnostics(Model):
    strategy: Literal["exhaustive", "bounded_descent", "none"]
    complete: bool = Field(description="True only when the whole candidate space was evaluated.")
    space_size: int
    evaluated: int
    budget: int
    feasible_found: int
    notes: list[str] = Field(default_factory=list)


class RecommendResult(Model):
    wire_omitted_defaults = {"cases": None, "search": None}

    candidates: list[Candidate]
    design_environment: EnvironmentSnapshot
    cases: list[str] | None = Field(default=None, description="Every environment case each candidate was evaluated against.")
    search: SearchDiagnostics | None = None


class RecommendResponse(Envelope[RecommendResult]):
    pass


class SequenceRequest(Model):
    ship_class_id: str
    berth_id: str
    config: MooringConfig
    environment: EnvironmentSnapshot
    tug_plan_result_id: str | None = None
    line_handling_crews: int = Field(default=6, ge=1)


SequenceAction = Literal["pass", "secure_pier", "hold", "take_to_power", "double_up", "tend"]


class SequenceStep(Model):
    step: int
    line_number: int | None
    action: SequenceAction
    station: Literal["forecastle", "waist", "fantail", "bridge", "pier"]
    crews: int
    trigger: str
    caution: str | None = None
    reference: str
    depends_on: list[int] = Field(default_factory=list, description="Step numbers that must complete first.")
    duration_min: float | None = Field(default=None, ge=0, description="Planning estimate, unreviewed.")
    tug_ids: list[str] = Field(default_factory=list, description="Tugs this step relies on.")
    state_ok: bool | None = Field(default=None, description="Static equilibrium with the lines fast after this step (null when not evaluated).")
    state_max_pct: float | None = Field(default=None, description="Highest utilization of that intermediate state.")
    state_note: str | None = None


class SequenceIssue(Model):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    severity: Literal["AMBER", "RED"]
    step: int | None = None
    line_number: int | None = None
    message: str


class SequenceResult(Model):
    steps: list[SequenceStep]
    crews_required: int
    issues: list[SequenceIssue] = Field(default_factory=list)
    review_status: Literal["draft_unreviewed", "reviewed"] = Field(
        default="draft_unreviewed", description="Generated sequences are drafts until a deck officer or pilot reviews them.")
    timing_assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    total_duration_min: float | None = Field(default=None, description="Critical-path estimate from the unreviewed durations.")


class SequenceValidateRequest(SequenceRequest):
    steps: list[SequenceStep] = Field(min_length=1, description="A proposed sequence to check, in execution order.")


class SequenceResponse(Envelope[SequenceResult]):
    pass
