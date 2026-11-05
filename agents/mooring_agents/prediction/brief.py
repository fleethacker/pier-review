"""Deterministic narration that preserves S7's warnings and unknown coverage."""

from mooring.core.schemas.prediction import PredictionResponse

from .schemas import PredictionAlternativeBrief, PredictionBrief


def explain(prediction: PredictionResponse) -> PredictionBrief:
    """Describe supplied model fields without estimating clearance, risk or a safer command."""
    result = prediction.result
    state = prediction.validity.state if prediction.validity else "unknown"
    usable = state in ("valid", "limited")
    unavailable = [kind for kind in ("pier", "fender", "coastline", "vessel") if kind not in result.hazards_checked]
    # S7's current contract has no shoal/under-keel assessment. Do not imply complete hazard coverage.
    unavailable.append("shoal/under-keel clearance")
    summary = (
        f"Prediction {prediction.result_id} uses the {result.engine} engine. "
        f"Status {prediction.status}; validity {state}. "
        f"Assessed at {result.as_of_utc.isoformat()}, with input age {result.input_age_s} s at that time. "
        "This is a saved assessment, not a refreshed live observation. "
        f"Hazard coverage unavailable: {', '.join(unavailable)}."
    )
    if prediction.validity:
        summary += " " + " ".join(reason.message for reason in prediction.validity.reasons)
    alternatives = []
    for alternative in result.alternatives:
        final = alternative.ticks[-1] if usable and alternative.ticks else None
        breach = alternative.first_breach if usable else None
        closest = alternative.closest_approach if usable else None
        corridor = usable and bool(alternative.corridor)
        if not usable:
            text = "Trajectory and clearance values are unavailable because validity is invalid or unknown."
        elif final:
            text = (f"At {final.t_s} s the model places the ship at {final.position.lat}, {final.position.lon}, "
                    f"heading {final.heading_true_deg} degrees true, speed over ground {final.sog_kt} kt.")
        else:
            text = "No trajectory ticks were supplied by the model."
        if breach is not None:
            text += (f" Model reports the first clearance-threshold breach at {breach.t_s} s for "
                     f"{breach.kind} {breach.element_id}, clearance {breach.clearance_ft} ft.")
        elif usable:
            text += (" No breach is reported for the checked hazards; this is not an all-clear indication."
                     if result.hazards_checked else " No hazard types were checked; clearance is unknown.")
        uncertainty = ("Corridor is model sample spread, not calibrated collision probability."
                       if corridor else "Trajectory uncertainty is unavailable; no calibrated collision probability is established.")
        alternatives.append(PredictionAlternativeBrief(
            alt_id=alternative.alt_id, label=alternative.label, explanation=text,
            final_tick=final, first_breach=breach, closest_approach=closest,
            corridor_available=corridor, uncertainty_note=uncertainty, cites=[prediction.result_id],
        ))
    return PredictionBrief(
        prediction_result_id=prediction.result_id, model=prediction.model, model_version=prediction.model_version,
        inputs_hash=prediction.inputs_hash, computed_at_utc=prediction.computed_at_utc,
        as_of_utc=result.as_of_utc, input_age_s=result.input_age_s, status=prediction.status,
        validity=prediction.validity, manifest=prediction.manifest, summary=summary,
        hazards_checked=result.hazards_checked, hazards_unavailable=unavailable, alternatives=alternatives,
        warnings=prediction.warnings, assumptions=prediction.assumptions, cites=[prediction.result_id],
    )
