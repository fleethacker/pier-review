# Prediction narration (A7)

`GET /api/v1/predictions/{result_id}/brief` explains an immutable S7 modeling result. The agent retrieves the
caller-owned result through the logged Physics toolkit; it does not rerun prediction, calculate clearance, rank
commands or invoke an LLM. Its response retains the result ID, model/input identity, assessment time and input age
at that assessment, validity, assumptions, model warnings and separate explanations for each alternative.

The explanation copies the model's final tick, closest approach and first clearance-threshold breach. Invalid or
unknown validity suppresses trajectory and clearance values. Unchecked hazard types and unsupported shoal/under-keel
coverage remain unavailable. A missing corridor is unavailable; a supplied corridor remains uncalibrated model spread.
Reading an older result does not refresh its observed inputs.

To create a result through the same logged boundary, call `POST /api/v1/physics/tools/predict_trajectory` with
`{"input": <PredictionRequest>}` and then use `output.result_id` for the brief. An existing result can be read through
the `get_prediction` tool. Modeling remains responsible for dynamics, warning decisions and result ownership.

The API is ready for the camera UI to consume. UI narration integration and broader S7 hazard/state/uncertainty
coverage are separate workstreams. `make demo-check` exercises the prediction tool, repeated brief reads and their
immutable citations with explicit mock forcing; it does not claim a calibrated camera or operational acceptance.
