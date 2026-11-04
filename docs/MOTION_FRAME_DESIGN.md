# RM0 motion frame contract

RM0 defines an additive display contract and deterministic UI fixtures. It implements no dynamics,
environment provider, session clock, live scene endpoint or trajectory qualification. The current simulator
continues to emit its legacy frames. Producers opt into new fields after their consumers support them.

Dependencies: S00a ([PR #11](https://github.com/DDL-Mike-Snyder/pier-review-ship-parking/pull/11),
`89bdecc`) and S00b ([PR #13](https://github.com/DDL-Mike-Snyder/pier-review-ship-parking/pull/13),
`51267d0`) are merged. This change includes `dev` through `6b35c92` (the DC4 review corrections in PR #21).

## Coordination and ownership

The watched branches are `ws-b/modeling-build-out` (PR #15) and
`ws-e/berthing-sim-and-readiness` (PR #18, stacked on PR #15). Both merged during RM0 development:
PR #18 at `630da7f`, then PR #15 into `dev` at `661da3f`. RM0 incorporates that merged base.

PR #18 adds optional `SimFrame.validity` and diagnostics, command timestamps, sampling controls, and
session limits. RM0 retains those fields and their absent-field behavior, using the same `Validity` type
and combining `wire_omitted_defaults`. PR #15's shared fender and provenance additions are preserved
by keeping motion-specific objects separate. The merged simulator continues emitting S17 frames;
it does not yet populate RM0 fields or serve scenes/lifecycle messages.

| Owner | Responsibility |
| --- | --- |
| RM0 | Field meanings, compatibility, scene/frame/lifecycle/recording schemas and fixtures |
| S15–S17 / PR #18 | Integration, contact, authoritative clock, timed commands and session controls |
| RM1 | Environment evaluated each step and relative-flow coupling |
| RM2 / DC4 | Approved wave sources, ingestion and forcing, with separate wave components |
| RM3 / RM4 | Tug kinematics and the chosen vertical-motion capability |
| RM5 | Scene retrieval, lifecycle transport, recording persistence and reconnect history |
| RM6 / RM7 | Drawing supplied state, controls, and visible validity/provenance badges |

## Compatibility and identity

The legacy `SimFrame` fields (`t_s`, `pose`, `tugs`, `lines`, `fenders`, `alerts`) keep their types and
meanings. RM0 additions default to null and are omitted when inactive, including nested batch serialization.
Existing request examples and hashes remain unchanged. Rich tug, line, fitting and fender state use new fields,
so shared static-analysis types do not acquire motion-specific requirements.

Rich frames carry `schema_version="rm0-v1"`, `session_id`, `run_id`, `sequence`, `scene_id` and `scene_revision`.
`t_s` is simulation time, never arrival time. Sequence numbers increase for the session and are assigned before
display decimation. Gaps can indicate sampling or dropped display frames; they do not measure elapsed physics time.
Reset starts a new `run_id` at `t_s=0` without resetting session sequence. Time cannot go backwards within a run.
Reconnect retains these identities; a newly created session starts a new sequence namespace.
Opting into `rm0-v1` requires all five identity fields and an integer sequence; this is enforced
by both the Python model and public JSON Schema. Legacy frames do not acquire these requirements.
Rich component IDs are unique within their respective lists; fitting identity is `(owner, fitting_id)`.

## Coordinate frames and units

| Data | Frame and units |
| --- | --- |
| Ship horizontal position | Berth `x_ft`, `y_ft`; +y off-pier |
| Ship heave | `heave_mllw_ft`: ship reference waterline origin above MLLW; null if unsimulated |
| Roll / pitch | Degrees about ship +x forward / +y port, right-hand positive |
| Yaw | `yaw_deg`: counterclockwise from berth +x about +z up |
| Ship linear velocity / acceleration | Ship axes: surge forward, sway port, heave up; ft/s and ft/s² |
| Ship angular velocity / acceleration | Ship-axis components, deg/s and deg/s² |
| Tug position / velocity / acceleration | Berth axes, ft / ft/s / ft/s²; height above MLLW when present |
| Frame line endpoints and polylines | Berth axes, height above MLLW |
| Scene hull outline and ship fittings | Ship-local coordinates, origin at midships on reference waterline |
| Force breakdown | Berth vectors in lbf; yaw moment about current ship origin in ft·lbf, +counterclockwise |
| Wind / wave directions | FROM, clockwise true bearing in degrees |
| Current direction | TOWARD, clockwise true bearing in degrees |

For horizontal drawing, rotate ship-local geometry by yaw counterclockwise, then translate by berth position.
Heading is `(berth face bearing - yaw_deg) mod 360`. Do not rotate an already berth-frame force again.
Vertical drawing requires supplied heave/attitude; missing components remain visibly unavailable.

Legacy `pose.v_kt` means **toward the pier**; new `motion.velocity.sway_fps` means **to port**. An adapter
must use heading/side, an explicit frame transform, and a named knots-to-feet-per-second conversion. Direct
copying or unconditional sign inversion is wrong. Legacy `r_degps` has no newly imposed sign convention.
The legacy pose remains a producer-supplied compatibility projection, not a source for inferring missing physics.

Each `motion.dofs` axis is simulated, prescribed, not simulated or unknown. Prescribed fixture motion is not
simulated dynamics. Unsimulated heave/roll/pitch have null pose, velocity and acceleration. A measured zero is
real data; missing is null. NaN and infinity are rejected. Angular body rates are not general Euler-angle rates;
future six-DOF producers must document that transformation instead of assuming equality.

## Rich state, validity and provenance

- Ship: six-component pose/body velocity, per-axis availability, acceleration when available.
- Tugs: berth position, heading, velocity/acceleration vectors, commanded/actual force vectors, push point,
  push/pull/standby mode, contact/made-up state, and supplied capacity utilization.
- Environment: wind/gust/direction, current speed/set and water level, each with source, availability and validity.
  Wave entries distinguish ocean swell, local wind chop, ship wake and tug wake with independent height, period,
  direction, source and availability. Unavailable swell must not hide an available local-chop estimate.
- Lines: ship and pier fitting IDs, tension, slack/taut/overloaded state, world endpoints and drawing polyline.
  Polylines may include supplied intermediate routing points, but model no catenary.
- Fittings/bollards: ship/pier identity, load, capacity and supplied utilization. Missing ratings stay null.
- Fenders: identity, compression and reaction, with validity. Legacy fender results remain usable.
- Forces: wind, current, wave, tug, line and fender contributions. Missing means unavailable, not zero.
- Alerts: legacy strings remain; structured alerts add stable codes, INFO/AMBER/RED severity and affected IDs.

The UI draws supplied geometry and values; it does not infer capacity, compute a new force balance, or decide
that an absent alert has cleared. Environment times have explicit UTC offsets. Frame cadence is not wind
averaging or gust duration. This schema performs no gust, height, unit or datum normalization. Wave ingestion,
spectra and source integration remain RM2/DC4 work; RM0 does not change `EnvironmentSnapshot`.
The approved offshore-source order is recorded in the merged
[DC4 investigation](DC4_WAVE_SOURCE_INVESTIGATION.md); these fixtures use none of those sources.

These optional wave display fields do not define an ingestion or forcing-selection model. Per PR #19,
RM2 must retain unpartitioned sea states explicitly, document partition/coverage and source overlap,
and avoid adding a total spectrum and its partitions together. Do not relabel a total as ocean swell.
Wake height/period are optional: transient arrivals need the event, duration and response representation
that RM2 will define. Unavailable wake is not zero, and surface wake does not authorize propeller wash.

Use [S00 validity](CONTRACT_SEMANTICS.md): absent/unknown means not assessed; limited/invalid need reasons.
Backend, convergence and low utilization do not qualify a result. `MotionProvenance` distinguishes mock,
estimated, qualified and unknown, with source and evidence; qualification requires more than a label.
Frame validity must preserve contributing limitations. Consumers show a frame badge and retain component
limitations, including unavailable vertical and wave data. An invalid descendant requires an invalid
aggregate, even when the aggregate would otherwise be limited or unknown. New fitting/fender status
fields obey the envelope status rule: limited is never GREEN and invalid is RED. The model rejects
contradictions instead of silently rewriting supplied values. The mock examples use AMBER.

All published examples are **MOCK / unqualified**. Authored coordinates, loads and percentages are independent
UI contract values, not integrated dynamics, observations, approved tug behavior or operating recommendations.
The prescribed planar trajectory does not establish force balance or a validated vessel model.

## Static scene and lifecycle

`SimScene` carries immutable scene ID/revision, berth outline/deck datum, fittings, fenders and depth profile,
ship-local hull outline/fittings, and provenance/validity. Geometry is fetched once, not repeated in frames.
Changed assets require a new revision. Consumers verify frame scene identity before drawing.

The optional `SimSessionCreated.scene_url` will identify a scene resource cached by `(scene_id, scene_revision)`.
RM5 owns serving it. For fixture playback, fetch `sim_scene.json` beside the recording. These are published
schemas and files: RM0 does not introduce a live scene route or claim lifecycle messages are already emitted.

`SimLifecycle` represents created, running, paused, reset, ended and error with session/run identity, sequence
and simulation time. S17 owns transitions: pause freezes at a completed step; reset restores initial state and
returns paused; reset messages require `t_s=0` and a new run identifier when prior messages are
available in the recording. Lifecycle sequences are strict integers, matching frame sequences.
Reconnect stays paused until explicit resume. Ended/error tells the UI that advancement stopped.
RM5 owns reliable lifecycle delivery and ordering relative to display frames.

## Sampling, slow clients and recording

Integration steps are independent of display sampling. The intended policy is a bounded latest-frame slot:
replace unread display frames with the newest sample, retaining original sequence/time. Never skip integration,
advance time on incoming messages, or silently alter commands to sustain the display rate. Slow clients see gaps
and fewer frames. CPU overload must be exposed as wall-time lag; it cannot silently change physical time.

Lifecycle/error events need a separate bounded reliable path or explicit resynchronization/error close. They
must not disappear silently with display decimation. Reconnect history requires RM5 retention; without it,
report the gap and current state. Display samples cannot reconstruct physics between samples. Deterministic
physics replay also needs the initial state, full timed command log, parameters and integrator version.

The fixture recording spans 60 simulated seconds at 1 Hz, including both endpoints. This is a display-sampling
choice, not an integration timestep. Visual interpolation must not invent contact, loads, alert clearance or
unmodeled vertical motion. Separate lifecycle fixtures illustrate all six states without implying that a
recorded 1 Hz trajectory contains every possible control transition.

Published UI fixtures: [scene](../contract/examples/modeling/sim_scene.json),
[expanded frame](../contract/examples/modeling/sim_frame.json), and
[60-second recording](../contract/examples/modeling/sim_recording_60s.json). The six
`sim_lifecycle_*.json` examples beside them cover every lifecycle state. The recording contains
61 frames at `t_s=0..60`; each frame occupies one compact JSON line for readable diffs.

## Evidence and performance boundary

Tests cover unchanged legacy serialization, current legacy WS output, finite/null values, qualification and
availability rules, fixture/schema agreement, monotonic sequence/time, scene references and deterministic export.
Run `make contract` then `make test`; regenerated OpenAPI and examples are committed together.

RM0 adds no integration step and qualifies no session count. Its benchmark measures only frame validation and
JSON serialization, records hardware/runtime and p50/p95 latency, and reports scene/frame/recording byte sizes.
S17/RM5 still own physics-step timing, supported integration timestep and measured concurrent-session limits.
A fast serializer is not evidence of real-time dynamics or a Phase 2 gate.

Run `uv run --all-packages python scripts/benchmark_motion_contract.py --output docs/benchmarks/rm0-frame.json`
to reproduce the [schema benchmark artifact](benchmarks/rm0-frame.json). It records the measured
latencies, runtime, hardware and exact published byte sizes; it makes no integration-capacity claim.
