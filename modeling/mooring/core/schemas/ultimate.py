"""P6/R6: modeled ultimate-load gust threshold contract.

The ultimate capacity basis is an explicit INPUT. This repository holds no sourced ultimate-capacity or material-law
data, so without a basis the result is `unavailable`; no capacity, breaking strength multiple or square-root design
factor is ever invented. Reaching a modeled ultimate capacity is not a validated prediction of physical rupture.
"""

from typing import Literal

from pydantic import Field, model_validator

from .common import Envelope, Model
from .mooring import AnalyzeRequest

EvidenceStatus = Literal["sourced", "synthetic_test_fixture"]


class LineUltimateCapacity(Model):
    line_number: int
    ultimate_capacity_lbf: float = Field(gt=0, description="Effective ultimate tension of the installed line (all parts), with wet/condition/termination factors already applied and cited in `factors`.")
    material_law_max_strain: float = Field(gt=0, description="Largest strain for which the load-elongation law is supported. Beyond it the search stops as indeterminate.")
    factors: str = Field(min_length=1, description="Wet, condition and termination factors applied, as sourced.")


class UltimateCapacityBasis(Model):
    basis_id: str
    evidence_status: EvidenceStatus
    citation: str = Field(min_length=1, description="Source of the capacity and material-law range.")
    wind_basis: str = Field(min_length=1, description="Wind averaging duration and reference height the supplied gust speed is stated on.")
    capacity_uncertainty: str | None = Field(default=None, description="Stated uncertainty of the capacity; informational, not applied to the threshold.")
    lines: list[LineUltimateCapacity] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self):
        nums = [c.line_number for c in self.lines]
        if len(set(nums)) != len(nums):
            raise ValueError("duplicate line_number in capacity basis")
        return self


class UltimateGustRequest(AnalyzeRequest):
    wire_omitted_defaults = {**AnalyzeRequest.wire_omitted_defaults, "capacity_basis": None}

    capacity_basis: UltimateCapacityBasis | None = Field(default=None, description="Required for a threshold; absent -> outcome 'unavailable'.")
    step_deg: int = Field(default=30, ge=5, le=90)
    max_search_kt: float = Field(default=150.0, ge=10, le=300, description="Search ceiling; no stop below it is indeterminate, never 'unlimited'.")
    sampling_step_kt: float = Field(default=5.0, ge=0.1, le=20)
    tolerance_kt: float = Field(default=0.25, gt=0, le=5)


DirectionOutcome = Literal[
    "threshold_found", "ultimate_at_zero_wind", "indeterminate_component_failed_first", "indeterminate_material_range",
    "indeterminate_nonconvergence", "indeterminate_search_ceiling"]


class UltimateDirectionResult(Model):
    wind_rel_deg: float
    wind_from_true_deg: float
    outcome: DirectionOutcome
    threshold_wind_kt: float | None = Field(default=None, description="Highest verified speed below modeled ultimate capacity; 0 at zero-wind failure; None unless a threshold was found.")
    threshold_gust_kt: float | None = Field(default=None, description="threshold_wind_kt times the request's held gust/sustained ratio.")
    bracket_kt: list[float] | None = None
    governing_line: str | None = None
    governing_utilization_of_ultimate: float | None = Field(default=None, description="Tension / ultimate capacity of the governing line at the upper bracket end.")
    wll_crossing_bracket_kt: list[float] | None = Field(default=None, description="Coarse wind-speed interval of the first WLL crossing (a warning, not a stop); None if none before the stop.")
    stop_kt: float | None = Field(default=None, description="Speed at which a non-ultimate stop or nonconvergence occurred.")
    stop_elements: list[str] = Field(default_factory=list)
    nonmonotone_in_bracket: bool | None = None
    reason: str | None = None


class UltimateGustResult(Model):
    outcome: Literal["threshold_found", "unavailable", "indeterminate"]
    reasons: list[str] = Field(default_factory=list)
    basis_id: str | None = None
    evidence_status: EvidenceStatus | None = None
    citation: str | None = None
    wind_basis: str | None = None
    complete: bool = Field(default=False, description="True only if every searched direction produced a threshold; otherwise the governing value is the lowest found, not a proven minimum.")
    governing: UltimateDirectionResult | None = None
    assessed: UltimateDirectionResult | None = Field(default=None, description="Search along the request's own wind direction.")
    assessed_gust_kt: float | None = None
    assessed_gust_margin_kt: float | None = Field(default=None, description="Assessed-direction threshold gust minus the request gust; negative means the modeled ultimate is exceeded.")
    directions: list[UltimateDirectionResult] = Field(default_factory=list)
    validated_rupture_prediction: Literal[False] = Field(default=False, description="Always false: a physical breaking claim needs its own validation evidence.")


class UltimateGustResponse(Envelope[UltimateGustResult]):
    pass
