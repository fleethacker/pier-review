"""Prediction narration contract; numerical claims remain modeling-owned."""

from datetime import datetime

from pydantic import Field

from mooring.core.schemas import Finding, Model, ResultManifest, Status, Validity
from mooring.core.schemas.prediction import HazardApproach, HazardKind, PredictedTick


class PredictionAlternativeBrief(Model):
    alt_id: str
    label: str
    explanation: str
    final_tick: PredictedTick | None = None
    first_breach: HazardApproach | None = None
    closest_approach: HazardApproach | None = None
    corridor_available: bool
    uncertainty_note: str
    cites: list[str]


class PredictionBrief(Model):
    prediction_result_id: str
    model: str
    model_version: str
    inputs_hash: str
    computed_at_utc: datetime
    as_of_utc: datetime
    input_age_s: float = Field(ge=0, description="Age at the model's assessment time, not age when this brief is read.")
    status: Status
    validity: Validity | None
    manifest: ResultManifest | None
    summary: str
    hazards_checked: list[HazardKind]
    hazards_unavailable: list[str]
    alternatives: list[PredictionAlternativeBrief]
    warnings: list[Finding]
    assumptions: list[str]
    cites: list[str]
    disclaimer: str = "Decision support for a demonstrator; not navigational guidance."
