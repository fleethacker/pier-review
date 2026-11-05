# S7 trajectory prediction (the "backup camera")

Ownership: **Snyder M-SIM** owns service/state/engine semantics; **Snyder M-PLAN** independent benchmarks; **Kori** U8; **Cruz** D8 sources; **Bixler** A7 narration and integrated acceptance. Initial implementation merged in #14; remaining gates are in [execution ownership](MASTER_PLAN.md#execution-ownership).

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

## Honesty rules (tests: `modeling/tests/test_s7_honesty.py`)
- Hazard coverage: no layer checked gives `HAZARD_COVERAGE_UNKNOWN` (no breach reported is not an all-clear); otherwise
  `HAZARD_COVERAGE_INCOMPLETE` names the unchecked kinds. A supplied other-vessel path shorter than the horizon is disclosed
  (`OTHER_VESSEL_PATH_SHORT`; the vessel is held at its first/last fix, not predicted).
- Swept hull: clearance uses the convex hull of consecutive footprints (central path checked at most 2 s apart, samples
  5 s), plus the initial footprint, so contact between output ticks or an overlap at t = 0 is reported (`SWEPT_HULL_CHECK`).
  Other vessels are swept over the same interval, which is conservative.
- Uncertainty is `UNCERTAINTY_UNAVAILABLE` (null corridor, spread and probability), never a zero-width corridor, when
  samples = 0, samples = 1, or there is no spread source (no state uncertainty and no wind/current).
- The engine works on a deep copy of the request and writes nothing to sessions, missions, scenarios or jobs.
- Bounds: horizon <= 900 s, ticks <= 900, <= 4 alternatives, <= 64 samples, <= 16 other vessels; non-finite or
  |speed| > 60 kt is a 422.

## S7b: time-varying forcing and engine handoff
- Request (additive, omitted on the wire when default): `forcing` (S2 `ForcingSpec`) and `engine` (`transit` default).
  Absent `forcing` = `fixed_environment`, exactly the old behavior and wire shape.
- With `forcing`, `mooring/prediction/forced.py` drives the unchanged S6 `Vessel` from the SAME
  `berthing.forcing.ForcingSeries.at(t)` (base = `environment`, or calm if null). t = 0 is `as_of_utc`; the series is
  sampled once per integration step (zero-order hold, not RK4 stage times). Uncertainty samples apply the same wind/current
  perturbation to the series value at every step. `vessel_relative_wind` has no extra effect (transit applies apparent wind).
- Response `result.forcing_basis`: `kind` (`fixed_environment` | `time_varying`), `revision` (frc-...), `synthetic`,
  `series_kind`, `coverage` (prediction-relative s), `requested_horizon_s`, `horizon_s`, `truncated`. Omitted on the wire for
  fixed_environment (absent = fixed). Validity adds `FORCING_TIME_VARYING`, `FORCING_SYNTHETIC` or
  `FORCING_SUPPLIED_UNVERIFIED`, `FORCING_HORIZON_TRUNCATED`.
- Coverage policy (never extrapolated): series not covering t = 0 is 422 `FORCING_UNCOVERED`; horizon beyond coverage is 422
  with `on_uncovered: stop`, or truncated to the last whole tick inside coverage with `invalidate` (reason
  `FORCING_HORIZON_TRUNCATED`; under one tick is 422). Generated series (steady/ramp/gusts) are defined over the horizon.
- Engine handoff is explicit only: `engine: "berthing"` returns 501 `ENGINE_UNSUPPORTED` (no validated frame, unit, state
  and parameter mapping or operating domain). The engine is never chosen from proximity to a pier.

## Not done
Berthing engine (S1-S3) and handoff; coastline; S10 uncertainty; sway/yaw-rate initial conditions; hull-pier contact is not simulated
(the path passes through it; clearance is 0 from contact on). Decision support for a demonstrator, not navigational guidance.
