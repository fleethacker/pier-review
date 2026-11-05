"""S7 contract examples, produced by the REAL prediction engine from the recorded NOAA CO-OPS snapshot (2026-11-05 17:11 UTC).

Deterministic: fixed as_of, seed and ids; only result_id and computed_at_utc are pinned for the example."""

from mooring.prediction import engine, presets

EXAMPLE_TIME = presets.AS_OF


def build() -> dict[str, dict]:
    request = presets.approach_request()
    response = engine.predict(request)
    response = response.model_copy(update={"result_id": "res_prediction_example", "computed_at_utc": EXAMPLE_TIME})
    return {"predict_trajectory_request": request.model_dump(mode="json"),
            "predict_trajectory_response": response.model_dump(mode="json")}


PREDICTION_EXAMPLES = build()
