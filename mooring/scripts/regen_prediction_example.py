"""Regenerate the stored S7 example from the real engine (run after deliberate physics/engine changes, then `make contract`)."""
import json

from mooring.prediction_examples import EXAMPLE_DIR, generate

out = generate()
(EXAMPLE_DIR / "request.json").write_text(json.dumps(out["predict_trajectory_request"], indent=2) + "\n")
(EXAMPLE_DIR / "response.json").write_text(json.dumps(out["predict_trajectory_response"], indent=2) + "\n")
print("wrote", EXAMPLE_DIR)
