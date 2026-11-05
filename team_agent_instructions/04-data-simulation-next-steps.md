# Data and simulation review: next implementation steps

Review date: 5 November 2026. Reviewed baseline: `origin/dev` at
`abf2d4c7e703f6c96e32674ee162070c803d9036`.

This is a source, history and documentation review, not a new provider availability
test or engineering qualification. No application code was changed and no test
suite was rerun for this document. Test files below identify existing evidence and
where new acceptance tests belong; they are not claims of new passing results.

The data work has delivered useful readers, provenance checks and test infrastructure.
The next milestone is an end-to-end, reproducible forecast-to-plan workflow, followed
by runtime simulation outputs that actually satisfy the richer motion contract.
Neither reader availability nor `backend="real"` establishes operational readiness.
Seed assets and surrogate dynamics must continue to produce limited results.

## What is already integrated

All the following remote branch tips were ancestors of the reviewed `dev`, with
zero branch-only commits. Do not merge these branches again or replace newer code
with their older implementations.

| Work | Reviewed branch tip | Delivered capability | Remaining boundary |
| --- | --- | --- | --- |
| DC0 provider plumbing | `ws-a/dc0-provider-plumbing` / `a820492` | Provider infrastructure and replay foundations | Complete source selection and partial availability semantics |
| DC1 CO-OPS | `ws-a/dc1-coops-completion` / `71afe2e` | Observation/prediction parsing and live observation path | Compose future predictions; avoid making one missing component obscure all useful data |
| DC2 NWS | `ws-a/dc2-nws-forecast` / `56c7eb1` | Grid discovery, interval parsing, wind forecast records | Runtime forecast composition and explicit wind averaging limitations |
| DC3 CBOFS | `ws-a/dc3-cbofs-forecast` / `4208f06` | Checked regular-grid current/water-level reader | Acquisition worker, publication provenance, applicable cell/depth coverage |
| DC5 uncertainty | `ws-a/dc5-history-fitting` / `a5be88d` | Hardened fitting/validation infrastructure | Replacement artifact and qualified forecast-error evaluation |
| DC6 ENC | `ws-a/dc6-enc-geometry` / `e94b6d4` | S-57 depth-area/corridor checks | Runtime approach integration and broader hazard/quality coverage |
| DC7 telemetry | `ws-a/dc7-telemetry-arbitration` / `64266a4` | Validated ingest and pure arbitration logic | Explicit, scoped runtime arbitration and field calibration |
| DC8 data requests | `ws-a/dc8-data-requests` / `c0c2aff` | Missing-data documentation | Obtain and qualify operational vessel/berth inputs |

DC4 is a source investigation, not a working wave adapter. The motion work includes
rich schemas and examples, but the berthing runtime still emits legacy frames.
Read the existing [data work instructions](03-data-and-simulation.md) alongside
this review; their requested scope must not be confused with delivered behavior.

## Findings that determine the order of work

1. **Source configuration can silently select synthetic data.** In
   [environment dispatch](../modeling/mooring/environment/__init__.py), modes other
   than `coops` fall through to the mock path. This includes `auto` and misspellings.
   Reject unknown configuration; implement an explicit `auto` policy before using
   that setting. Synthetic data must never repair a failed operational provider.
2. **Installed forecast readers do not provide a composed planning forecast.**
   The configured CO-OPS forecast path is unavailable; NWS and CBOFS are separate
   readers. `/env/forecast` lacks a scenario/as-of selector, while
   [scenario resolution](../modeling/mooring/scenarios.py) rejects forecast/replay
   modes. An explicit environment scenario is currently needed for those workflows.
3. **Partial availability needs an API decision.** The live path requires joined
   wind, current and water-level observations. A missing component can prevent the
   entire snapshot. The existing snapshot schema requires numeric values for all
   components, so returning partial data honestly requires an additive availability
   representation, not zero-filled snapshots.
4. **CBOFS cannot simply be called from a request worker.** Its native NetCDF reader
   requires the main thread. Its HTTP timeout is not a total acquisition deadline.
   Caller-supplied issue time is checked but does not establish actual publication
   time. A separate acquisition process and provenance verification are needed.
5. **Simulation contracts outpace the producer.** Rich motion schemas are registered
   in OpenAPI, but the runtime does not populate their scene identity, sequence,
   geometry and force fields. There are no corresponding runtime scene/recording
   routes. Contract examples are not integration evidence.
6. **The simulation environment is frozen at creation.** The shared integrator is
   real, but forcing uses one snapshot, fixed water level and surrogate dynamics.
   Vessel-relative flow, changing tide, waves and actual tug trajectories are not
   supplied by the existence of the integrator.

## Target integration

Keep acquisition outside physics and freeze the inputs to each calculation:

```text
NOAA / recorded observations / explicit synthetic scenarios
    -> acquisition, normalization and component availability
    -> immutable series + source/issue/retrieval/depth/datum manifest
       -> forecast-plan -> Intake -> Planner -> independent Safety -> crew review
       -> simulation-time forcing -> shared integrator -> frames + recording
```

These are two different uses of a common input series. Forecast planning performs
sampled static mooring checks; it does not approve the docking maneuver, contact
loads or under-keel clearance. A simulation is not a substitute for the planning
checks. Preserve canonical scenario identity, forecast revision and selected line
configuration across both uses.

## Ordered implementation packets

### 1. P0 — Explicit source selection and component availability

Owner: data/platform; modeling and UI review the additive contract.

Start with [environment dispatch](../modeling/mooring/environment/__init__.py),
[live acquisition](../modeling/mooring/environment/live.py),
[environment schemas](../modeling/mooring/core/schemas/environment.py) and
[environment routes](../modeling/modeling_api/routers/env.py).

- Validate configuration against supported modes. Define explicit operational,
  recorded-replay and synthetic behavior, including whether startup or the request
  fails for unusable configuration. Do not advertise `auto` before it works.
- Retain the complete-snapshot contract. Propose an additive availability response
  for independently available components; agree its shape with consumers before
  implementation. Reuse existing component provenance fields.
- Track freshness, issue/retrieval/valid times, averaging basis, station/grid cell,
  current depth/bin and vertical datum per component. Missing is not zero.
- Do not silently substitute predictions for observations or a nearby depth/cell
  for the requested one. Make any permitted alternative explicit and applicable.
- Distinguish the synthetic `replay_sample.json` fixture from actual recorded
  observations. Build a small public-data replay package with provenance if needed;
  parser fixtures alone do not provide that package.

Acceptance: misspelled mode fails explicitly; each single-component outage is
represented honestly; stale observation never becomes a fresh forecast; replay
outside coverage fails; no provider failure silently produces mock values. Tests
use injected clocks and local fixtures, including malformed/partial responses.

### 2. P0 — Reproducible forecast coverage through docking and holding

Owner: data acquisition plus modeling API; agents own consumer binding. Depends on
packet 1. This is the first complete user-visible milestone.

Read [NWS notes](../docs/DC2_NWS_FORECAST.md),
[CBOFS notes](../docs/DC3_CBOFS_FORECAST.md) and
[forecast docking design](../docs/FORECAST_DOCKING.md). Reuse
[forecast planning](../modeling/mooring/moored/forecast_planning.py) and
[forecast provenance](../modeling/mooring/core/forecast_provenance.py).

- Compose NWS wind with applicable tide/current predictions or CBOFS output.
  Preserve each source and basis rather than calling the mixture one observation.
  Missing NWS gusts and unknown averaging duration stay explicit; do not invent a
  gust factor to satisfy the load model.
- Acquire CBOFS in a dedicated process whose main thread owns NetCDF access. Bound
  total elapsed acquisition, retries, memory and artifact size; close datasets.
  Serve decoded cached artifacts to API workers. Verify actual product publication
  and availability at the requested as-of time.
- Validate requested current depth and wet-cell coverage. Prior recorded probes
  found missing Pier 12 subsurface values; surface or adjacent-cell availability
  does not authorize substitution. That is historical evidence, not a fresh probe.
- Freeze one revision with content hash and component provenance. Define an
  additive request contract binding source/scenario, as-of and horizon. Use one
  canonical resolver in all consumers; never repeat the current point for a ramp
  or replay series.
- Cover arrival at least 24 hours ahead **plus the complete docking/holding period**.
  Default 48-hour data may not cover the requested operation. Reject uncovered
  candidates; do not extrapolate. Preserve existing maximum-gap checks and the
  explicit short-lead reassessment option.
- Carry the same snapshot manifest, owned Intake report and selected configuration
  through Planner and Safety. Preserve paid-out line lengths, wet/dry properties
  and installation tide. A changed forecast revision triggers explicit reassessment,
  not mutation of an already reviewed result.

Acceptance: a fixture-driven operation beginning at +24 hours completes through
the requested holding end; gaps, future-issued products, missing depth, missing
gust basis and insufficient horizon are handled explicitly. Same manifest and
configuration reproduce result hashes. Independent agent/UI consumers identify
the same revision. Extend `test_dc2_nws.py`, `test_dc3_cbofs.py`,
`test_forecast_docking.py` and supplied-tide/mock-coverage tests as appropriate.

### 3. P1 — Produce the motion contract before adding more physics

Owner: simulation/API; coordinate contract consumption with the UI colleague.
Can proceed alongside packet 2 once interface ownership is agreed.

Read [motion design](../docs/MOTION_FRAME_DESIGN.md),
[berthing simulator](../modeling/mooring/berthing/simulator.py),
[session scheduler](../modeling/modeling_api/sim_sessions.py) and
[berthing routes](../modeling/modeling_api/routers/berthing.py).

- Populate existing motion fields from actual simulator state: immutable scene
  identity/revision, session/run identity, sequence, geometry and available forces.
  Mark absent DOFs and tug positions unavailable; do not fabricate zeros or motion.
- Add owned scene retrieval and bounded persisted recordings. Specify restart,
  reset, disconnect/reconnect and recording-gap semantics. Keep sequence monotonic
  across reset and give a reset a new run identity.
- Keep the latest-frame display policy separate from recording completeness.
  A slow socket cannot stall integration or silently claim a complete recording.
- If playback/simulation speed control is added, scale scheduler wall time, not
  physics step size. Preserve command ordering and rejection of past commands.
- Convert frames deliberately: berth +y is off-pier; ship sway is +port; legacy
  `v_kt` is toward-pier. Their relationship depends on vessel side. Do not rotate
  ship-frame load vectors twice.

Acceptance: actual HTTP/WS outputs validate against motion schemas; UI receives
resolvable scene identity; reset/reconnect/slow-client/flood tests preserve physics
and isolation. Existing batch/WS equivalence, contact energy, timestep convergence
and equilibrium consistency checks remain. Extend `test_s17_simulation.py` and
motion contract tests; schema/example tests alone are insufficient.

### 4. P1 — Drive the shared integrator from simulation-time environment

Owner: modeling mechanics/berthing, with data-provided immutable series.
Depends on packet 2's series contract; synthetic fixtures can unblock development.

- Resolve forcing at integration-stage simulation time, not request arrival time.
  Specify interpolation and align steps with command/forecast discontinuities.
  Batch and interactive modes must use the identical forcing implementation.
- Apply water level consistently to actual water depth and line geometry without
  changing installed paid-out lengths. Tide does not change vessel mass or draft.
- Define vessel-relative current and wind in the correct frames; establish how
  drag and existing damping interact so resistance is not counted twice.
- Stop or invalidate on uncovered forcing according to a documented policy;
  retain validity history, event log and forcing revision in persisted results.
- Keep all arbitrary mass/inertia/damping and added-mass assumptions labeled
  surrogate and vessel-unqualified. Do not promote them by fitting a plausible
  animation. Source coefficients or retain a qualification blocker.

Acceptance: time-varying tide/current fixture produces identical batch/WS paths;
network rate cannot change forcing time; known relative-flow/frame cases agree;
constant forcing preserves existing checks; gaps and invalid depths are visible.
Place reusable synthetic generators in
[data_simulation](../modeling/mooring/data_simulation/README.md), with explicit
seed, UTC anchor and `not_a_forecast` provenance.

### 5. P1/P2 — Tug geometry and bounded vertical motion

Owner: dynamics, then UI consumption. Depends on packet 3.

Current force application uses catalog-based push-point placement and demonstration
slew behavior, not a qualified operational tug assignment or maneuver model.
Bind selected available tugs to actual permitted push/tow points, capacity and
slew limits. Compute moments from application geometry and expose the resulting
forces. Represent tug positions only when their kinematic model exists.

Start vertical motion with explicitly prescribed tide-following elevation. Add
quasi-static heel only with supported loading/stability inputs; do not invent GM,
roll/pitch response or hydrodynamic coefficients. Missing coefficients remain
blockers. Test force/moment signs, placement, assignment isolation, saturation,
slew and DOF-status semantics. Keep training motion distinct from qualified vessel
response. A useful animation does not establish a safe docking envelope.

### 6. P2 — Wave inputs and defensible local applicability

Owner: data for acquisition; modeling for response and applicability.
Read [wave source investigation](../docs/DC4_WAVE_SOURCE_INVESTIGATION.md).

- Implement the documented NDBC 44099 observation / GFS-Wave forecast path, with
  44014 as an independent check where applicable. CBOFS is not a wave source.
- Preserve height/period/direction definitions, source coordinates and times.
  Do not double-count total sea, partitions and spectra.
- Treat offshore-to-berth applicability as an explicit engineering gap. Do not
  invent harbor attenuation or local fetch coefficients. A sourced, bounded
  exposure method for one berth is more useful initially than a fine wave mesh.
- Put seeded training seas/wakes in `data_simulation`; disclose response limits.
  Unavailable wakes/waves are not measured zero. Live AIS/wake acquisition is a
  separate availability/licensing and modeling decision.

Acceptance: parser/unit/direction tests, uncovered horizon behavior and manifest
provenance; explicit zero-wave forcing preserves the no-wave trajectory. Validate
synthetic statistics separately from physical vessel-response qualification.

### 7. P2 — Uncertainty refit and opt-in telemetry integration

These are separate deliverables; neither should block the basic forecast workflow.

**Uncertainty:** the served `coops-8638614-2025.json` artifact still declares 364
days and unqualified status. Improved fitter code does not replace that artifact.
Refit only with documented coverage and independent event/time holdouts. Keep
storm/hurricane omissions, missing current periods and station applicability
visible. Forecast uncertainty needs residuals matched by issue time and lead time;
observational variability alone does not qualify forecast probabilities. Record
model ID and training/evaluation domains; adding another year is not sufficient
qualification. Start at `environment/uncertainty.py`, `scripts/fit_uncertainty.py`
and `test_s10_uncertainty.py`.

**Telemetry:** ingest and arbitration exist, but arbitration is not wired into the
environment service. See [telemetry support](../docs/DC7_TELEMETRY_SUPPORT.md).
Build candidates from actual freshness, quality, calibration and qualification;
do not rely on permissive candidate defaults. Scope by principal/vessel, preserve
explicit scenario/manual choices, and distinguish true/apparent wind correctly.
Fresh observations must not replace future forecasts. Disagreements should prompt
reassessment without rewriting reviewed plans. Test expiry, invalid calibration,
out-of-order/future timestamps, cross-vessel isolation and fallback provenance.

### 8. P3 — Connect ENC evidence to approach/UKC with honest limits

Owner: data/approach. Read [ENC qualification](../docs/DC6_ENC_QUALIFICATION.md).

The reader checks supported datum/units and corridor coverage using depth areas;
the runtime approach package is still mock. Depth areas alone do not cover
soundings, wrecks, obstructions, survey quality or current notices. Validate chart
currency and add required hazard coverage before treating a corridor as navigable.
Keep static draft, datum-consistent tide and sourced dynamic clearance components
separate. Do not infer safe passage from a passing DEPARE test. Extend
`test_dc6_enc.py` and add runtime consumer tests when this integration is taken up.

## UI coordination while the colleague merges

Do not modify or merge UI branches as part of these packets without coordination.
Use `ui/frontend-updates` as the relevant UI work; ignore `frontend-exercise`.
Rebase the proposed interfaces on the colleague's merged `dev` before implementation.

Offer the UI owner these capabilities, with generated contracts/examples:

| Capability | Backend prerequisite | UI recommendation |
| --- | --- | --- |
| Component availability | Packet 1 | Show wind/current/tide independently, including missing/stale/source/basis |
| +24-hour operation planning | Packet 2 | Select arrival and holding duration; show coverage and revision before running |
| Line-plan continuity | Packet 2 | Retain selected configuration/installation tide through Intake, Planner and Safety |
| Motion viewer | Packet 3 | Resolve scene; show unavailable DOFs; handle reset, reconnect and recording gaps |
| Environmental evolution | Packet 4 | Display simulation time and forcing revision separately from wall time |
| Training scenarios | Packets 4–6 | Explicit seed/source controls and persistent training labels |
| Qualification limits | All packets | Show blockers independently of backend label; invalid cannot be green |

Assign one owner per shared schema/router change. Publish small contract PRs first,
then consumer PRs; avoid concurrent edits to the same generated contract. Report
exact branch/commit and examples through agreed team channels rather than assuming
that another agent is monitoring a worktree. No automatic merging into a colleague's
active branch is needed.

## Engineering inputs needed before crew operational reliance

Prioritize one vessel/loading condition at one berth. Obtain reviewed line inventory
and properties, fitting capacities/coordinates, fender curves, tug availability and
ratings, vessel wind geometry/loading/stability, bathymetry/datum, applicable current
profiles and local exposure. Record source, date, applicability and reviewer.

Define docking/holding limits and operational procedures with the responsible
operators. Validate representative static and maneuver cases against independent
evidence, including adverse conditions and missing-data cases. Maintain separate
software acceptance and engineering qualification records. Neither public forecast
availability nor passing tests closes these input and validation gaps.

## Execution and completion checklist

The next agent should start with **packet 1**, then deliver **packet 2** as the first
end-to-end milestone. Read `README.md`, `CONTRIBUTING.md`, `contract/README.md`,
`modeling/README.md`, the existing team instructions and the linked designs first.
Use an isolated worktree from current `origin/dev`; keep PRs small and do not push
directly to `dev` or `main`.

- Keep acquisition out of physics; agents use PhysicsToolkit rather than importing
  modeling internals. Preserve shared-capability/phase import boundaries.
- Add optional wire fields to `wire_omitted_defaults`; regenerate with `make contract`
  rather than editing contract artifacts. Coordinate generated UI types with their owner.
- Use deterministic fixture tests, injected clocks and seeded scenario generation.
  Live probes are opt-in acquisition evidence, not CI dependencies.
- Run focused tests and `make test` for implementation PRs; report pass/skip/xfail
  counts, compatibility evidence and remaining blockers. Do not weaken validity gates.
- Demonstrate one frozen public-data forecast revision and one clearly synthetic
  training scenario through their respective consumer paths. Include failure cases,
  not only a successful animation or parser response.
- Update capability/readiness documentation according to delivered runtime behavior.
  Mark reader-only, runtime-connected, tested and engineering-qualified separately.

Completion of these packets would substantially improve integration and planning
usefulness. Operational reliance still requires the vessel/berth evidence and
responsible review described above.
