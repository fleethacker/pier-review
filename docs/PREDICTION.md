# S7 trajectory prediction (the "backup camera")

`POST /api/v1/predict/trajectory` predicts a vessel's path over the next minutes from its observed state. It runs the
existing S6 transit simulator (`mooring.transit.simulator.run`) forward; there is no separate dynamics model.
`GET /api/v1/predict/presets` returns two demonstration requests built from the recorded NOAA CO-OPS window
(`mooring/prediction/fixtures/noaa_live`, 2026-11-05 17:11 UTC).

## How it works (`mooring/prediction/engine.py`)
- The state maps to a one-vessel `TransitRequest`: start position, heading and speed (`max(surge, 0)`); a waypoint 20 nm
  ahead so the autopilot is irrelevant; scripted helm at t=0 holding the observed rudder and engine order; tug commands at
  t=0 for observed tug forces (`tug_assisted`, no auto assist). What-ifs add their helm/tug commands (times from start).
- `hold` is always first. Each alternative is simulated independently.
- Footprints are a parametric planform (catalog LOA and beam, pointed bow) centred on the reported position.
- Hazards: pier face from the berth origin along the face bearing for the face length; fenders as segments offset by their
  standoff on the water side; other vessels by footprint distance at the nearest path fix time. Coastline is not checked
  (`COASTLINE_NOT_CHECKED`); `hazards_checked` lists only what ran.
- Corridor (samples > 0): seeded perturbations of start position/heading/speed (supplied one-sigma) and of wind
  (15 % / 10 deg) and current (20 % / 15 deg). The corridor is the outline of the union of hull footprints of the central
  `percentile` share of samples (those closest to the median track) plus the central track. Breach probability is the sample
  share with clearance below the minimum. This is an illustrative spread, not the S10 model (`UNCERTAINTY_ILLUSTRATIVE`).
  Samples run at dt = max(dt_s, 1.0 s) to bound runtime.

## Validity
Always `limited`: inherits the transit reasons, plus `INPUT_AGE`, `STALE_INPUT` (> 300 s), `PREDICTION_START_APPROXIMATED`
(only forward surge is supported at start; the rudder starts at 0 and slews to the observed angle; thrust starts near
resistance), `COASTLINE_NOT_CHECKED`. Status RED if the held commands breach, else AMBER.

## Not done
Berthing engine (S1-S3); coastline; S10 uncertainty; sway/yaw-rate initial conditions; hull-pier contact is not simulated
(the path passes through it; clearance is 0 from contact on). Decision support for a demonstrator, not navigational guidance.
