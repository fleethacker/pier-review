"""S8 / R7: bounded line-sequence search request and result (additive; not yet exported from schemas/__init__)."""

from typing import Literal

from pydantic import Field

from .common import Model
from .planning import SequenceIssue, SequenceRequest, SequenceStep


class SequenceSearchRequest(SequenceRequest):
    must_precede: list[tuple[int, int]] = Field(default_factory=list,
        description="Handling constraints (a, b): line a is passed and secured before line b. Caller-supplied; none are invented.")
    first_line: int | None = Field(default=None, description="Optional constraint: this line is handled first.")
    max_candidates: int = Field(default=8, ge=1, le=60, description="Upper bound on orderings evaluated with the static solver.")
    max_proposals: int = Field(default=3, ge=1, le=10)


class SequenceConstraintCheck(Model):
    code: str
    satisfied: bool | None = Field(description="null when not evaluated.")
    message: str


class SequenceProposal(Model):
    rank: int
    line_order: list[int]
    outcome: Literal["feasible_static", "indeterminate", "infeasible"]
    is_default_order: bool
    steps: list[SequenceStep]
    issues: list[SequenceIssue]
    constraints: list[SequenceConstraintCheck]
    intermediate_states_evaluated: int
    intermediate_states_indeterminate: int
    worst_state_pct: float | None = None
    total_duration_min: float | None = None
    validity_state: Literal["limited", "invalid"]
    review_status: Literal["draft_unreviewed", "reviewed"] = "draft_unreviewed"


class SequenceSearchBounds(Model):
    max_candidates: int
    candidate_space: int = Field(description="Number of orderings of the configured lines (n!).")
    evaluated: int
    admissible_candidates: int | None = Field(default=None, description="Orderings meeting the caller constraints; null when the space was not fully enumerated.")
    truncated: bool = Field(description="True when admissible orderings remained unevaluated because of max_candidates or the enumeration guard.")


class SequenceSearchResult(Model):
    outcome: Literal["feasible_found", "indeterminate_only", "no_feasible_order", "budget_limited", "unsupported"]
    proposals: list[SequenceProposal]
    bounds: SequenceSearchBounds
    default_order: list[int]
    default_order_outcome: Literal["feasible_static", "indeterminate", "infeasible", "not_evaluated"]
    tie_breaks: list[str]
    limitations: list[str]
    review_status: Literal["draft_unreviewed", "reviewed"] = "draft_unreviewed"
