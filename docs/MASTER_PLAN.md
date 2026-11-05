# Master plan: remaining build

**This is the single planning document for the rest of the build.** It replaces the overnight agent instructions, the
overnight logs' "next steps" and "tomorrow" sections, the expanded modeling plan and the release review's deferred list
(all now in [docs/archive/2026-11-05-overnight/](archive/2026-11-05-overnight/)). If a priority or assignment here
conflicts with another document, this one wins. Detailed packet specifications stay where they are (see [Document map](#document-map)).

Written 5 November 2026 against `dev` at `e0e0fcf` (PR #106). The repo now lives at
[fleethacker/pier-review](https://github.com/fleethacker/pier-review); its default branch is `main`, so **always open PRs
with `--base dev`**.

## North star: a backup camera for ships

A car's backup camera draws the path the car will take given its steering angle, updated as you turn the wheel. **We are
building that for a ship.** From the ship's *current* position, heading and speed, the commands in force (rudder, engine,
tugs, lines) and the *current* conditions in the water (wind and gusts, current, tide, waves where available), predict and
draw where the ship will be over the next minutes: its path, its hull footprint along that path, how uncertain that is,
and when it would touch a pier, fender, shoal or another vessel. Refresh it continuously as conditions and commands
change, and let the crew try "what if" commands (more rudder, a tug push, engine astern) before acting.

Every workstream builds toward that view. Ask of each change: *does it make the prediction more correct, more honest
about its limits, faster to refresh, or easier to read?*

| Piece | Role in the backup camera |
| --- | --- |
| Live inputs (Cruz: D1, D2, D8) | The starting state (own-ship position, heading, speed) and the forcing (wind, current, tide) with source, age and basis. Stale or missing input must show on the camera, never be filled in. |
| Prediction engines (Snyder: S1–S3, S6, **S7**) | S6 port-transit dynamics predict in open water and the approach; S1–S3 berthing dynamics predict near the pier with lines, fenders and tugs; S2 makes forcing change over the horizon. S7 must define trajectory uncertainty; the existing S10 static-load sampler alone is not a calibrated trajectory corridor. **S7 is the prediction service itself.** |
| The camera view (Kori: U8) | Predicted path and hull footprints drawn over the live ship, an uncertainty corridor, time ticks, clearance and contact warnings, and what-if controls. |
| Explanation and warnings (Bixler: A7) | Agents explain the prediction in plain words, warn when the corridor approaches a hazard, and cite the prediction result. |
| Storyboarding (S5) | After the mission, compare the recorded track with what was predicted at each moment: the evidence that the camera is right, and where it is not. |
| Static planning (forecast plan, Intake → Planner → Safety sheet) | Still needed: it answers "is this mooring plan safe for the conditions ahead"; the camera answers "where is the ship going right now". |

**Honesty applies to the camera most of all.** Predictions from surrogate dynamics, assumed propulsion or stale inputs are
labeled on the view itself (validity, provenance, input age). The camera is decision support for a demonstrator, never
navigational guidance, and must not look more certain than it is.

## Who is who

| Name | Workstream | Item prefixes | Section |
| --- | --- | --- | --- |
| **Snyder** | Modeling: simulation runtime and physics (Claude session + GPT session) | S, P | [§4](#4-snyder-modeling-claude-session--gpt-session) |
| **Kori** | UI | U | [§5](#5-kori-ui) |
| **Cruz** | Data connections | D | [§6](#6-cruz-data-connections) |
| **Bixler** | Agents, integration, release, and any odd jobs not owned by someone else | A | [§7](#7-bixler-agents-integration-release-and-odd-jobs) |

If you are an AI agent working for one of these people: read this whole file, then work **only** on your person's
items and files, in priority order, following [§8](#8-coordination-rules) and [§10](#10-parallelizing-with-sub-agents-sonnet-55-and-gpt).

| | |
| --- | --- |
| **Build ends** | _fill in: date, time, timezone_ |
| **Feature freeze** | build end minus 3 hours |
| **Demo rehearsal** | build end minus 2 hours, on the hosting target, from a clean checkout of `main` |
| **Plan owner** | Bixler (integration lead) keeps the [status board](#status-board) current |

## 1. Where we are

**Build-start baseline** (historical evidence: 1,736 Python tests, 227 UI tests, contract/typecheck/lint/build green,
scoped `make demo-check` 24/24; use the current PR/CI evidence for newer counts):

- Phase 1 chain on real modeling: four named demo cases (`GET /api/v1/demo/docking-cases`: supported AMBER/limited,
  overloaded RED, invalid depth RED/invalid, underconstrained), Intake → Planner (SSE) → independent Safety review →
  Safety Sheet (HTML; PDF with native libraries) → approvals → print. Intake report ID flows to the Planner.
- Advance planning ≥24 h ahead from **supplied** forecast series (`POST /mooring/forecast-plan`), seeded training
  scenarios (`POST /data-simulation/forecast`), tide sweep, risk timeline, gust warnings.
- Berth from an image: deterministic catalog draft, optional guarded LLM/detector extraction, confirmation registers a
  selectable berth.
- UI: Cesium 2D/3D workspace, motion view (SVG plan + Cesium map mode) for recordings and live sessions, data-source and
  capability panel, seed-data banner, units toggle, berth-image review.
- LLM providers: none (default), OpenAI, Anthropic. Everything runs offline with no key.

**Modeling integration update, 5 November:** P1 immutable forecast resolution (#4), P2 explicit forecast reassessment
(#8), and the initial P3 independent dynamics benchmarks (#5) are merged into `dev`. S1 (#6) review fixes await
integration and CI. S5/S6 (#10) merged at `355bec8` into `dev` at `ed12e31`, but all 16 independent review findings
remain open; this is not review approval. See the [PR #10 review](https://github.com/fleethacker/pier-review/pull/10#issuecomment-6663809986).
S7/U8/D8/A7 below are planned work, not implemented prediction capability. Composed public forecasts and vessel
qualification remain open.

**Not done** (this plan's scope):

| Gap | Why it matters for the demo |
| --- | --- |
| Live simulator still emits **legacy frames**; no runtime scene or recording routes; no speed control | Live motion view shows tugs, lines and environment as "unavailable"; only the authored fixture looks rich |
| Simulation environment frozen at session start; surrogate vessel; no tug kinematics; no tide heave | Motion is not driven by changing wind/current/tide |
| Unknown `MOORING_ENV_SOURCE` values (including `auto`) silently fall through to **mock** | Honesty bug: synthetic data can masquerade as configured live data |
| One missing component (often stale cb0402 current) fails the whole live snapshot | Live mode is often 503 |
| NWS, CO-OPS predictions and CBOFS are separate readers; **no composed public forecast** | Advance planning only works with supplied/synthetic series |
| Explicit Intake and independent Safety-review **selection in the UI**; full four-case browser chain | Release review's top open UI items |
| Waves: source approved (NDBC 44099 / GFS-Wave), no adapter | No real sea state anywhere |
| Uncertainty artifact still 364 days, unqualified; telemetry arbitration unwired; approach/UKC still mock | Lower priority; label honestly |
| 13 dev-dependency audit findings (Vitest, Tinypool, Vite, minimatch) | Test-tool upgrade, not a production exposure |
| Hosting/auth: local-demo auth, single process | Fine for a demo; document the boundary |

Overnight data/simulation agent produced no commits, so **every data and simulation packet below starts from the state
described in [the data/simulation review](archive/2026-11-05-overnight/instructions/04-data-simulation-next-steps.md)**,
which remains the detailed spec for packets D1–D6 and S1–S3.

## 2. Definition of done for the build

Demo-ready means all of the following, on `main`, from a clean checkout, offline and with no LLM key (live sources are a bonus):

1. `make install && make test && make contract-check` green; UI typecheck/lint/test/build green; CI green on `main`.
2. `./app.sh` serves the UI on :8888 with both services proxied (HTTP, SSE, WS), locally **and** on the hosting target.
3. **Planning story:** pick berth → place ship → Intake → Planner → explicit independent Safety review → sheet → approve →
   print, for the supported case, with the RED, invalid and underconstrained cases shown honestly. Explicit Intake and
   review selection in the UI.
4. **Advance planning story:** choose an arrival ≥24 h ahead plus holding duration, see forecast coverage and provenance,
   get alternatives and the selected line configuration, carry it into Planner/Safety. Uses the composed public forecast
   when available, else a labeled recorded or synthetic series.
5. **Motion story:** start a session; ship, tugs, lines, fenders and environment move live in 2D and 3D from **rm0-v1 frames**,
   forcing changes over simulation time (tide, gusts, current), tug and line commands work, pause/resume/reset/speed and
   recording playback work. Every synthetic component is badged.
6. **Data honesty:** each environment component shows source, state (live/replay/prediction/mock/unavailable), age and
   basis; misconfiguration fails loudly; missing is never zero.
7. **Backup-camera story (S7/U8):** from a live or explicitly labeled replayed/synthetic ship state and conditions,
   the UI draws the predicted path and hull footprints, refreshes at least once per second, and updates for what-if
   commands. It shows model-generated warnings, validity, input age and hazard coverage. A supported uncertainty
   corridor is shown with its basis; the minimum deterministic demo explicitly shows uncertainty as unavailable.
   Missing hazard geometry cannot produce an all-clear indication.
8. `make demo-check` covers 3–5 and 7 end to end and passes; `frontend/DEMO.md` has the final 5-minute script; README and status
   docs are truthful.

**Cut order if time runs short** (cut from the bottom): approach/ENC (D6) → telemetry (D5b) → uncertainty refit (D5a) →
waves (D4, S4) → tug kinematics and heel (S3) → composed public forecast (D2: fall back to recorded/synthetic series,
labeled) → sim-time forcing (S2). Never cut: items 1–3, rm0 live frames (S1), source-selection honesty (D1), the
backup-camera story (item 7, at least without the uncertainty corridor), item 8.

## 3. Team and ownership

Four people (see [Who is who](#who-is-who)). Ownership is by **files**, so parallel work rarely conflicts. Cross-boundary edits: small, additive, and
announced to the owner in the PR description.

| Person | Workstream | Owns (write access by default) |
| --- | --- | --- |
| **Snyder** (modeling lead; Claude session + GPT session) | **M**: simulation runtime and modeling physics | `modeling/mooring/berthing/`, `mechanics/`, `loads/`, `moored/`, `tugs/`, `rules/`, `data_simulation/`, `modeling/modeling_api/{sim_sessions.py,ws.py}`, routers `berthing.py`, `moored.py`, `loads.py`, schemas `motion.py`, `dynamics.py`, `forecast_planning.py`, `planning.py`, `mooring.py`, `risk.py` |
| **Kori** | **U**: UI | `frontend/`, `frontend/DEMO.md` |
| **Cruz** | **D**: data connections | `modeling/mooring/environment/`, `telemetry/`, `approach/`, `core/forecast_provenance.py`, routers `env.py`, `telemetry.py`, `approach.py`, schemas `environment.py`, `telemetry.py`, data `scripts/` (`fit_uncertainty.py`, `record_provider_fixture.py`, `smoke_coops.py`), `docs/DATA_SOURCES.md`, `docs/DC*.md` |
| **Bixler** | **A**: agents, integration, release, odd jobs | `agents/`, `scripts/demo_check*.py`, `Makefile`, `app.sh`, `.github/`, `contract/README.md`, `README.md`, this plan, `docs/DEPLOYMENT_READINESS.md`, refdata/qualification (`refdata/`, `qualification.py`, `routers/{refdata,qualification,system}.py`) |

Shared, single-writer-at-a-time: `modeling/modeling_api/main.py`, `core/schemas/__init__.py`, `common.py`,
`scenarios.py`, `contract/` (generated; see [§8](#8-coordination-rules)).

## 4. Snyder: modeling (Claude session + GPT session)

Snyder runs two coding sessions at once. Split them by **file ownership**, not by task type, so they never edit the same
file, and use each as the other's independent reviewer.

| Session | Lane | Files (exclusive) |
| --- | --- | --- |
| **Claude (M-SIM)** | S1 → S7 interface/minimum deterministic camera → S2 → S7 changing-forcing extension → S3; S5/S6 review fixes remain open and gate their use in the camera | `berthing/`, `sim_sessions.py`, `ws.py`, `routers/berthing.py`, `schemas/motion.py`, `schemas/dynamics.py`; `missions/`, `transit/`, `routers/{missions,transit}.py`, `schemas/{missions,transit}.py`; coordinate additive prediction route/schema with shared-file owners |
| **GPT (M-PLAN)** | Static modeling and the forecast consumer side: P1 → P2 → S4 → P3, then benchmarks for S1–S3 | `moored/`, `loads/`, `mechanics/`, `tugs/`, `rules/`, `data_simulation/`, `routers/{moored,loads}.py`, `schemas/{forecast_planning,planning,mooring,risk}.py` |

Rules for the two sessions:

- Each session works in its own worktree and branch (`ws-e/<item>` for Claude, `ws-b/<item>` for GPT), from the current `dev`.
- **Cross-review:** every PR from one session is reviewed by the other before merge, with the prompt "find correctness bugs;
  do not restate the author's intent". GPT also writes the **independent analytical benchmarks** for Claude's dynamics
  (S1–S3), because a benchmark written by the same session that wrote the code is weak evidence.
- Only one session at a time runs `make contract`. Convention: the session that merges first regenerates; the other merges
  `dev` and reruns `make contract` before its own PR.
- Snyder resolves design disagreements between the two sessions; neither session overrides the other's files.

### M-SIM (Claude session)

**S1 (P0). Publish live rm0-v1 frames, scene and recordings.** Spec: data/simulation review packet 3,
[MOTION_FRAME_DESIGN.md](MOTION_FRAME_DESIGN.md). Populate identity (session, run, sequence, scene id/revision), six-component
pose with unsimulated DOFs flagged, tug state, line endpoints/polylines with fitting IDs, fitting loads, fender compression,
force breakdown and environment-at-t from actual simulator state; absent means unavailable, never zero. Add
`GET` scene route, bounded persisted recordings (list/fetch/replay), lifecycle messages, reconnect-from-sequence, and a
speed control that scales scheduler wall time, not the physics step. Mind the frame conventions (berth +y off-pier, ship
sway +port, legacy `v_kt` toward-pier). **Publish the interface early**: a draft PR with the route list and one real
captured frame within the first 2 hours so Kori can wire it. Acceptance: real HTTP/WS output validates against the
motion schemas; reset/reconnect/slow-client/flood tests; batch/WS equivalence and energy/convergence checks still pass.

**S2 (P1). Simulation-time forcing.** Packet 4. Forcing resolved at integration-stage time from an immutable series
(steady, ramp, seeded gusts, recorded replay, forecast), identical in batch and interactive. Vessel-relative wind and
current without double-counting damping; water level updates depth and line geometry without changing paid-out lengths.
Uncovered forcing stops or invalidates per a documented policy. Synthetic series come from `data_simulation/` (GPT lane)
or Cruz's series contract; use fixtures until those land.

**S5 (P0, added 5 Nov). Mission storyboarding.** After a mission, rebuild the ship's path from its recorded lat/lon
fixes and tie timestamped images and reports to positions on that path. Ingest tracks (JSON, CSV, GPX, NMEA RMC/GGA),
images (timestamp and position from EXIF, with a supplied camera clock offset and UTC offset, or an explicit timestamp)
and reports (timestamp, text, optional reported position). Locate every event on the track by time with an explicit
method: exact fix, interpolated between fixes, in a gap longer than the allowed interpolation span, or before/after the
track; never extrapolate. Compare the interpolated position with EXIF/reported positions and report the discrepancy.
Outputs: storyboard (time-ordered events with positions, distance along track, speed), decimated track, GeoJSON export.
Naive timestamps are rejected unless an offset is supplied; duplicates and out-of-order fixes are reported, not hidden.
UI: a storyboard view (track on the map, event markers, timeline scrubber that moves the ship along the path, image and
report panels). Acceptance: parser fixtures for each format, interpolation/gap/extrapolation tests, EXIF timezone and
clock-offset tests, round-trip GeoJSON, bounded upload sizes, ownership checks.

**S6 (P0, added 5 Nov). Port transit simulation: own thrust and tug-assisted, multiple ships.** Simulate ships entering
or leaving port along lat/lon routes under their own propulsion, or with tugs. 3-DOF maneuvering (surge, sway, yaw) in a
local tangent plane tied to lat/lon; hull forces from published main-dimension regressions (Clarke et al. 1983 linear
derivatives, Mumford wetted surface), propeller thrust with engine lag, rudder with rate limit and propeller wash,
apparent wind through the existing UFC loads, current as moving water. Line-of-sight autopilot with leg speeds and an
arrival slowdown; tugs by timed commands or an automatic low-speed turning/braking assist within bollard pull and slew.
Several vessels on one clock (no ship–ship interaction, stated). Propulsion data are explicit labeled assumptions (no
ship speed/power in reference data). Validity always limited with reasons (surrogate maneuvering, assumed propulsion,
deep water: no squat/bank/UKC, tug kinematics not modeled). Simulated tracks use the S5 fix format so they replay in the
storyboard. Acceptance: analytic and sanity benchmarks (steady speed, zero-rudder straight line, turning-circle
symmetry and range, rudder step response, drift with current, pure tug sway force, deceleration), multi-vessel
independence, determinism, inbound and outbound Norfolk presets that reach their final waypoint.

**S3 (P2). Tug geometry and vertical motion.** Packet 5. Tugs bound to permitted push points, capacity and slew; moments from
contact geometry; tug positions only where a kinematic model exists. Tide-following heave first; quasi-static heel only
with supported loading/stability inputs (else "not simulated"). No invented GM or hydrodynamic coefficients.

**S7 (P0, added 5 Nov). Trajectory prediction service: the backup camera.** M-SIM owns the service and contract;
M-PLAN supplies independent trajectory/contact benchmarks. Publish additive schemas and fixtures first for U8/A7/D8.
Given an explicit engine and immutable state snapshot, predict the next N seconds (default 300, maximum 900) under
held commands and bounded what-if alternatives. Return states at fixed time ticks, hull footprints, input/model/forcing
revisions and timestamps, validity, hazard coverage and model-computed contact/clearance warnings. The snapshot must
preserve required hidden state (actuator lag/slew, pending commands, active lines and paid-out lengths), not just the
displayed pose/velocity. Clone it per alternative; prediction never advances or mutates the live session.

Deliver in gates: **S7a** is the deterministic single-engine camera using reviewed S1 or, after the open PR #10 findings
are fixed and independently re-reviewed, S6, with an explicit fixed-environment basis. Recorded/synthetic initial states are acceptable, labeled, until
D8 supplies live state. **S7b** adds S2's changing forcing and a documented engine handoff with tested frames, units,
state/parameter mapping and supported operating domain; never switch engines silently by proximity to a pier.
**S7c** adds trajectory uncertainty when its input-error and temporal sampling model are specified. Seeded ensemble
envelopes remain unqualified model spread, not a measured collision probability; missing uncertainty is unavailable,
never a zero-width confidence claim. Same-model seeded coverage tests prove consistency, not real-world calibration.

API: `POST /predict/trajectory` plus an optional prediction reference/summary in S1 frames. Contract-first limits cover
horizon, samples, alternatives, queued work and deadlines. Run prediction in a bounded worker independent of the
physics ticker; cancel/supersede obsolete requests, publish latest-only, and preserve owner isolation. The ≤300 ms
five-minute/single-alternative latency and ≥1 Hz refresh are targets to measure on a named demo-machine workload,
including concurrent live sessions. If missed, report pending/stale/unavailable explicitly; do not silently coarsen
physics or block the live clock to meet the target. Agree the bounded-job response with U8 before implementation.

S7 owns all hazard decisions; agents only narrate its cited warnings. Check continuous swept hull/geometry between
output samples, including an initial overlap. Shoal warnings require chart depth/datum, tide, draft and supported
under-keel assumptions; other-vessel warnings require time-aligned trajectories. Missing or stale layers are unknown
coverage, never evidence of clearance. Reject unsupported state/forcing coverage; label any explicit constant-forcing
assumption. Acceptance: clone leaves live state/clock unchanged, alternatives are independent, same inputs reproduce
the full simulator, concurrent load respects bounds, and hand-built crossing/overlap/missing-layer cases are correct.

### M-PLAN (GPT session)

**P1 (P0). Forecast-plan consumer of the composed forecast.** Packet 2, modeling side. One canonical resolver binding
source/scenario, as-of and horizon used by forecast-plan, Intake, Planner and Safety; reject uncovered arrivals (≥24 h plus
docking and holding); freeze revision with a content hash; same manifest reproduces result hashes. Build against Cruz's
interface and fixtures; until D2 lands, use supplied series.

**P2 (P1). Demo-relevant static gaps.** Changed forecast revision triggers explicit reassessment (not mutation); sequence
draft checks on real plans; anything in the [capability ledger](MODELING_BUILDOUT_STATUS.md) that produces a confusing
result in the four demo cases. Keep wind-duration conversions beyond the sourced range `limited`.

**S4 (P2). Wave forcing surrogate.** Packet 6, modeling side, after D4's schema: seeded synthetic wave response for
visualization, labeled unqualified; zero-wave input reproduces the no-wave trajectory; no double counting of total sea and
partitions. Coordinate the frame fields with M-SIM.

**P3 (continuous). Independent benchmarks for S1–S3:** single tug at a known point (force and yaw moment), tide cycle
heave, still-air relative-velocity case, timestep convergence, batch/interactive/replay equivalence. Commit as tests.

## 5. Kori: UI

Read [MODELING_UI_RECOMMENDATIONS.md](MODELING_UI_RECOMMENDATIONS.md) (backend capabilities with wire details) first.

| ID | Pri | Work | Depends on |
| --- | --- | --- | --- |
| U1 | P0 | **Explicit Intake and independent Safety-review selection** in the planning flow; show the review identity on the sheet; four-case choice with initial vs final outcome shown separately | none (backend done) |
| U2 | P0 | **Live motion on rm0-v1**: consume S1's scene route, rich frames, lifecycle, recordings list/playback, speed control (enable the disabled control), reconnect-from-sequence; draw tugs/lines/fittings/forces/env from live frames | S1 interface (draft PR) |
| U3 | P1 | **Per-component environment availability** (wind/current/tide/forecast/waves): source, state, age, basis; misconfiguration error state | D1 interface |
| U4 | P1 | **Advance-planning panel**: as-of, arrival ≥24 h, holding duration, coverage and provenance preview, alternatives table, apply `selected_config` (keep paid-out lengths and installation tide), "recheck required" on changed inputs | P1/D2 for public data; works now with supplied series |
| U5 | P1 | Simulation-time display (sim time vs wall time, forcing revision) and training-scenario controls (seed, source, persistent "training" label) | S2 |
| U6 | P2 | Upgrade test toolchain to clear the 13 dev-dependency findings (Vitest/Tinypool/Vite); compatibility-tested, no `npm audit fix --force` | none |
| U8 | P0 | **Backup-camera overlay** (north star): predicted path, hull footprints at time ticks, uncertainty corridor, contact/clearance warnings and what-if controls (rudder, engine, tug push) drawn over the live ship in the motion view and the transit view; refresh ≥1 Hz from S7 (`POST /predict/trajectory` or the session frame `prediction` field); validity and input age on the overlay. Build against S7 fixtures first | S7 interface |
| U7 | P2 | Cesium-scene motion view with roll/pitch and water surface when frames supply them; accessibility pass (contrast, screen reader); profile React path at 10 Hz | S3 |

Kori also owns `frontend/DEMO.md` and the UI half of `make demo-check` (browser steps for U1, U2, U4).

## 6. Cruz: data connections

Detailed acceptance for D1–D6: [data/simulation review](archive/2026-11-05-overnight/instructions/04-data-simulation-next-steps.md)
packets 1, 2, 6, 7 and 8.

| ID | Pri | Work |
| --- | --- | --- |
| D1 | P0 | **Explicit source selection and component availability** (packet 1). Reject unknown modes at startup; implement `auto` only with a documented policy (live → recorded replay labeled `replay` → explicit failure; mock only when explicitly configured). Additive per-component availability response; agree the shape with Kori and Snyder in a contract-only PR first. Separate the synthetic `replay_sample.json` from a small **recorded real** replay package with provenance. |
| D2 | P0 | **Composed public forecast** (packet 2, acquisition side). NWS wind + CO-OPS tide/current predictions (+ CBOFS where its cell/depth is applicable), each component keeping source and basis; CBOFS in a separate acquisition process with a total deadline; frozen revision with manifest. Publish the series contract and fixtures **early** so P1 and U4 can build against them. Fallback rung: CO-OPS predictions only, wind `unavailable`. |
| D3 | P1 | Recorded-real demo package: a short window of real CO-OPS (and NWS, if archived) data with provenance, served as `replay`, used by the offline demo and `make demo-check`. |
| D4 | P2 | Waves (packet 6): NDBC 44099 ingestion preserving total vs partition vs spectrum; GFS-Wave if reachable, else forecast `unavailable`; wake `unavailable`. Feeds S4. |
| D5 | P3 | (a) Uncertainty refit ≥365 days with time/event holdout, still unqualified unless the policy is met. (b) Opt-in telemetry arbitration into env (packet 7). |
| D8 | P1 | **Live own-ship state for the backup camera:** position, heading, COG/SOG from GPS/NMEA/AIS through the existing telemetry ingest (D5b promoted for this purpose), with age and quality, exposed as the starting state for S7; plus replay of a recorded track (the S5 fix format) as a stand-in feed for demos. Never extrapolate a stale fix silently. |
| D6 | P3 | ENC → approach/UKC (packet 8) only if everything above is done; otherwise approach stays labeled mock. |

Tests never hit the network; live checks stay opt-in (`make smoke-live`).

## 7. Bixler: agents, integration, release and odd jobs

Bixler also picks up any task that has no owner in this plan (tooling, CI breakage, dependency upgrades outside
`frontend/`, demo materials, unblocking someone), and reassigns work if an owner falls behind.

| ID | Pri | Work |
| --- | --- | --- |
| A0 | P0 | **Finish the remote cut-over** (history is already imported to `fleethacker/pier-review`): set the GitHub default branch to `dev` (or keep `main` and make sure everyone uses `--base dev`); confirm CI runs for PRs/pushes to `dev` and `main`; branch protection if available; update README/CONTRIBUTING URLs from `DDL-Mike-Snyder/pier-review-ship-parking`. Tell everyone to re-clone or `git remote set-url origin https://github.com/fleethacker/pier-review.git`. |
| A1 | P0 | **`make demo-check` to the definition of done**: full four-case Intake → Planner → review → sheet chain, advance-planning story, live rm0 motion story (S1), data-honesty checks (D1). Run it on every merge to `dev`; post failures to the owner. |
| A2 | P0 | **Hosting**: `app.sh` on the actual demo target (Domino), WebSocket/SSE through the proxy, PDF libraries or documented HTML fallback, Mapbox token as an app env variable; rehearse from a clean checkout of `main`. |
| A3 | P1 | Agents consume the composed forecast: Intake/Planner/Safety bind to the forecast revision from P1; changed revision → explicit reassessment; Safety watch follows the same source. |
| A4 | P1 | Release management: merge `dev` → `main` by PR with a merge commit at each milestone (§9), release notes with the qualification limits, tag. |
| A5 | P2 | Vision: optional real image extraction path checked with a fixture image and fake LLM; keep the no-LLM path honest. |
| A7 | P1 | **Backup-camera narration and warnings:** an agent tool for immutable S7 predictions; explain the path, uncertainty basis and S7-computed warnings with cited result IDs. Never compute clearance or downgrade unknown coverage in the LLM. Include the camera in the demo script and `make demo-check` (definition of done item 7). |
| A6 | P2 | Docs truthfulness pass: README status, `MODELING_BUILDOUT_STATUS.md`, `DEPLOYMENT_READINESS.md`, `frontend/PLAN.md`, `DEMO.md`; presentation narrative and screenshots. |

## 8. Coordination rules

- **Git:** branch from current `dev` on `fleethacker/pier-review` and open PRs with `gh pr create --base dev`; one item per PR; `<area>/<item-id>-<short-name>` with areas
  `ws-e` (M-SIM), `ws-b` (M-PLAN), `ui`, `ws-a` (data), `agents`, `fix`, `docs`; put the item ID (S1, U2, D1…) in the PR
  title. Never force-push or push directly to `dev`/`main`. One approval (another person, or Snyder's other session for his
  PRs) and green CI before merge. Merge `dev` into your branch at least every 2 hours.
- **Contract:** schema changes are additive, then `make contract`; never hand-edit `contract/`. A conflict in `contract/`
  is resolved by taking either side and rerunning `make contract`. UI regenerates types (`npm run types`) after merging.
  **Interface first:** publish a contract-only PR with example fixtures before the implementation when another person
  consumes it (S1, D1, D2, P1).
- **Status:** post a two-line update in the team channel at each merge (what landed, what is next, any blocker). Bixler
  updates the status board below at least every 2 hours.
- **Blocked for more than 30 minutes** on another person: build against fixtures or a labeled stub and say so in the PR;
  do not wait.
- **Honesty rules (do not bend):** no fabricated data on provider failure; seed/synthetic/limited labels stay visible; no
  deleting/skipping/weakening tests to go green; agents never compute physics; no secrets in the repo; everything demos
  offline with `AGENTS_LLM_PROVIDER=none`.

## 9. Sequence

Times are relative to the start of work after the remote move (**T0**). Adjust to the build end.

| When | Milestone | Who |
| --- | --- | --- |
| T0 + 1 h | Default branch/CI confirmed on the new remote, everyone re-cloned (A0). Contract-only PRs opened for S1 (frames/scene/recording routes) and D1 (availability shape) | Bixler, Snyder (Claude), Cruz |
| T0 + 3 h | U1 merged; S1 live frames merged; D1 merged; demo-check extended to the planning chain | Kori, Snyder, Cruz, Bixler |
| T0 + 5 h | U2 live rm0 motion in the UI; D2 series contract + fixtures published; P1 resolver against fixtures. **Release to `main` #1** | Kori, Cruz, Snyder (GPT), Bixler |
| T0 + 6 h (integration recorded) | S5 storyboarding and S6 port transit merged in #10; 16 independent findings remain open. Fix and re-review before treating either feature as accepted. | Snyder (Claude; independent review) |
| After reviewed S1, before declaring the build complete | S7a contract/fixtures → U8 deterministic camera and A7 cited warnings → integration gate for definition-of-done item 7. Use labeled replay/synthetic state until D8 lands; S6 remains gated on closure and independent re-review of the PR #10 findings. A milestone release before this gate is not completion of the build. | Snyder (M-SIM service; M-PLAN benchmarks), Kori, Bixler; Cruz supplies D8 |
| T0 + 8 h | S2 sim-time forcing; D2 composed forecast; U3/U4; A3 agents on forecast revision. **Release to `main` #2** | all |
| After S2/D8 interfaces | S7b changing forcing/live state and explicit engine handoff; S7c uncertainty only with its declared sampling model and evidence. Retain unavailable labels for unimplemented parts. | Snyder, Cruz, Kori, Bixler |
| Then | P2 items: S3, S4/D4, U5–U7, D5, A5. Release after each green milestone | all |
| Freeze (end − 3 h) | Features stop. Only fixes, docs, demo-check | all |
| End − 2 h | Rehearsal on the hosting target from clean `main`; fix only what breaks the demo | Bixler leads |
| End | Final release to `main`, tag, notes | Bixler |

## 10. Parallelizing with sub-agents (Sonnet 5.5 and GPT)

Time is short, so every person should fan work out to sub-agents **inside** their workstream. The person (or Snyder's
session) stays the **coordinator**: plans, writes the briefs, integrates, reviews and owns the merge. Sub-agents do bounded
pieces.

### What to fan out, and what not to

| Fan out (independent, verifiable) | Keep with the coordinator |
| --- | --- |
| Tests for an agreed interface (fixtures, edge cases, regression tests) | Contract and schema design; `make contract` |
| Independent implementations on **disjoint files** (e.g. NWS parser vs CBOFS worker vs replay package) | Anything touching a shared file (`main.py`, schema `__init__`, `contract/`) |
| UI components against fixed fixtures (one panel each) | Merge conflict resolution and the final integration |
| Codebase searches, impact analysis ("every caller of X") | Decisions about physics conventions, labels and honesty policy |
| Independent review of a diff; independent analytical benchmark | Accepting a sub-agent's claim without running the tests yourself |
| Docs updates for a merged feature | Release to `main` |

Rule of thumb: if two sub-agents would edit the same file, or one needs the other's output, they are **not** parallel;
run them in sequence or give one of them a fixture.

### Claude Code (Sonnet 5.5 sub-agents)

- Spawn with the Agent tool, `model: "sonnet"`, and `isolation: "worktree"` for anything that edits files, so each
  sub-agent has its own git worktree and branch. Read-only searches can use the Explore agent without isolation.
- Launch independent sub-agents **in one message** so they run concurrently; 3–5 at a time is a good ceiling per coordinator.
- The coordinator merges each sub-agent's branch into its own item branch, runs the full checks, and opens the PR. Sub-agents
  do not open PRs into `dev` and never push to `dev` or `main`.
- For larger fan-outs (more than 5 pieces, or review-then-verify pipelines), ask Claude to "use a workflow".
- Use a fresh sub-agent (not the author) for review, and give it the diff, not the author's conclusions.

### GPT (Codex or parallel GPT sessions)

- Run each GPT sub-task in its **own worktree and branch** (`git worktree add ../psp-<item>-<n> -b <branch>/<n> <base>`),
  one task per agent, with the same brief template below. Codex-style cloud tasks work the same way: one branch per task.
- Merge results into the coordinator's item branch locally and run the full checks before opening the PR.
- Snyder: use GPT sub-agents for the M-PLAN lane and for benchmarks/reviews of the Claude lane; use Sonnet sub-agents inside
  the M-SIM lane. Do not let a GPT sub-agent and a Claude sub-agent edit the same files.

### Brief template (copy into every sub-agent prompt)

```text
Goal: <one sentence, the outcome, not the steps>.
Repo: pier-review-ship-parking, base branch <item branch>, your worktree/branch <name>.
Read first: docs/MASTER_PLAN.md §8 (rules), <the 2–4 files or docs that matter>.
Scope: you may edit ONLY <files/dirs>. Do not touch contract/, main.py or other owners' files.
Interface you must honor: <schema/endpoint/fixture path>.
Already decided / ruled out: <conventions, units, labels, approaches rejected>.
Done means: <tests to add/pass>, `uv run --all-packages pytest -q <paths>` (or `npm test`, `npm run typecheck`) green.
Honesty: never fabricate data, never weaken or skip tests, missing is not zero, keep synthetic/limited labels.
Report back: files changed, test commands and counts, anything you could not do and why. Commit to your branch; do not open PRs.
```

### Suggested fan-outs per workstream

| Lane | Parallel sub-agents (disjoint) |
| --- | --- |
| M-SIM S1 (Snyder, Claude) | (1) frame population in `berthing/` from simulator state; (2) scene + recording routes and storage; (3) lifecycle/reconnect/speed in `sim_sessions.py`/`ws.py`; (4) contract-consumer and flood/slow-client tests. Coordinator owns `schemas/motion.py`. |
| M-PLAN (Snyder, GPT) | (1) canonical forecast resolver; (2) reassessment on revision change; (3) analytical benchmarks for S1–S3; (4) wave surrogate statistics tests |
| U (Kori) | One sub-agent per panel (U1 Intake/review selection, U2 motion live adapter, U3 availability panel, U4 advance-planning panel), each against fixtures; one for demo-check browser steps |
| D (Cruz) | (1) source-mode validation + `auto` policy; (2) availability response; (3) NWS + CO-OPS composition; (4) CBOFS acquisition process; (5) recorded-real replay package; (6) NDBC 44099 parser |
| A (Bixler) | (1) demo-check planning chain; (2) demo-check motion/data checks; (3) hosting/app.sh rehearsal; (4) agents forecast-revision binding; (5) docs truthfulness pass |

## Status board

Bixler updates this table; everyone else posts in the team channel.

| Item | Owner | State | PR | Notes |
| --- | --- | --- | --- | --- |
| A0 remote cut-over | Bixler | local cut-over docs complete; protection pending admin | | GitHub checked 5 Nov: default `main`, `dev`/`main` unprotected; explicit `--base dev`; CI triggers both branches |
| S1 rm0 live frames | Snyder (Claude; GPT review/fixes) | review fixes await integration and CI | #6 | Rich frames, scene, lifecycle/speed/reconnect, bounded workers and saved recordings/index; synthetic vessel dynamics |
| S5 mission storyboarding | Snyder (Claude) | merged; review findings open | #10 | Part of the 16 unresolved [independent findings](https://github.com/fleethacker/pier-review/pull/10#issuecomment-6663809986); not approved clean. Demo: [DEMO_MISSIONS_TRANSIT.md](DEMO_MISSIONS_TRANSIT.md) |
| S6 port transit simulation | Snyder (Claude) | merged; review findings open | #10 | Same unresolved review as S5; surrogate/limited; camera use awaits fixes and independent re-review |
| S7 trajectory prediction | Snyder (Claude service; GPT independent benchmarks) | planned; contract first after S1 | #11 plan only | S7a is deterministic and single-engine; S7b/S7c depend on S2, data/uncertainty support; no prediction endpoint exists yet |
| P1 forecast resolver | Snyder (GPT) | merged | #4 | Immutable supplied/scenario resolution, hashes and coverage gates; public composition still depends on D2 |
| P2 forecast recheck | Snyder (GPT) | merged | #8 | Explicit reassessment on revision change; historical results remain immutable |
| P3 independent dynamics benchmarks | Snyder (GPT) | initial benchmarks merged; continuous | #5 | Analytic tug/damping/convergence/acceleration/energy checks; extend for S2/S3/S7 |
| U1 Intake/review selection | Kori | not started | | |
| U2 live rm0 motion | Kori | blocked on S1 interface | | build on fixtures meanwhile |
| U8 backup-camera overlay | Kori | planned; build against S7 fixtures | | Follow S7a interface; never imply clearance for missing geometry/uncertainty |
| D1 source selection | Cruz | not started | | |
| D2 composed forecast | Cruz | not started | | |
| D8 own-ship state | Cruz | planned | | Publish state/age/quality contract for S7; recorded/synthetic demo fallback must be labeled; AIS ingest remains unsupported until implemented |
| A1 demo-check | Bixler | merged (baseline); full gate pending | #7 | Four API chains, synthetic advance planning, legacy WS; CI job added; readiness profile fails uncovered S1/D1/A3/browser gates |
| A2 hosting | Bixler | local launcher/browser rehearsal passed; target deferred | | Node >=22.17, startup health, installer/service cleanup, HTML fallback; Bixler requested local tests instead of Domino |
| A3 forecast binding | Bixler | consumer integration pending; P1 available | | Carry the merged resolver manifest through Intake/Planner/Safety; automatic public revision lookup still depends on D2 |
| A7 prediction narration | Bixler | planned; depends on S7 result contract | | Cite code-owned warnings and immutable prediction IDs; add the item 7 demo gate |
| A4 release | Bixler | draft notes/procedure prepared; unreleased | | [Release draft](RELEASE_NOTES.md); milestone dependencies, review, CI and clean-main target gate remain |
| A5 vision | Bixler | implemented locally | | Fixture-image/fake-LLM HTTP flow; empty/duplicate/oversized proposal fallback; no-LLM catalog labels preserved |
| A6 docs | Bixler | integration truthfulness pass | | README, contribution/release/hosting docs and UI/modeling status distinguish baseline evidence from full acceptance |

The following is historical rehearsal evidence from `agents/a0-bixler-integration`, originally based on `282c046`
and since merged by #7. It does not establish completion of the new camera or remaining browser/data gates.
The CI job retains logs and failure ownership in its run summary.

Local validation: **1,769 Python tests and 227 UI tests passed**; contract/typecheck/lint/build, Bash syntax and
ShellCheck passed. The actual `app.sh` rehearsal passed **27 API/browser checks**, including REST/SSE/WS and the
printed review ID. Readiness correctly failed six explicitly uncovered build requirements. See
[local rehearsal evidence and screenshots](LOCAL_REHEARSAL.md); this is not release or Domino evidence.

A3's next implementation should consume P1's logged resolver response, retain `forecast_manifest` through Intake,
Planner, review and sheet, and compare `revision`, `content_hash` and `binding_hash` before explicit reassessment.
No duplicate resolver or provisional public schema was introduced. Safety watch also needs a D2-supported way to
look up a newer source revision; a caller-declared `source_id` for supplied samples cannot provide that itself.

## Document map

| Purpose | Document |
| --- | --- |
| **Priorities, owners, sequence** | this file |
| Product roadmap and module list | [PLAN.md](PLAN.md) |
| Packet definitions S00–S21 (implementation authority for modeling packet scope) | [MODELING_EXECUTION_PLAN.md](MODELING_EXECUTION_PLAN.md) |
| What is implemented per packet, evidence and blockers | [MODELING_BUILDOUT_STATUS.md](MODELING_BUILDOUT_STATUS.md) |
| Detailed specs for the data and simulation packets | [archived data/simulation review](archive/2026-11-05-overnight/instructions/04-data-simulation-next-steps.md) |
| Backend capabilities for the UI, with wire details | [MODELING_UI_RECOMMENDATIONS.md](MODELING_UI_RECOMMENDATIONS.md) |
| Motion frames, scene, recordings | [MOTION_FRAME_DESIGN.md](MOTION_FRAME_DESIGN.md), [BERTHING_SIMULATION.md](BERTHING_SIMULATION.md) |
| Forecast planning ≥24 h | [FORECAST_DOCKING.md](FORECAST_DOCKING.md) |
| Data sources and source notes | [DATA_SOURCES.md](DATA_SOURCES.md), `DC2`–`DC7` notes, [DC4 waves](DC4_WAVE_SOURCE_INVESTIGATION.md), [wind basis](WIND_BASIS_REVIEW.md), [current direction](NOAA_CURRENT_DIRECTION_REVIEW.md) |
| Inputs only humans can supply | [DATA_REQUESTS.md](DATA_REQUESTS.md) |
| Deployment and security boundary | [DEPLOYMENT_READINESS.md](DEPLOYMENT_READINESS.md) |
| Contract semantics | [CONTRACT_SEMANTICS.md](CONTRACT_SEMANTICS.md), [contract/README.md](../contract/README.md) |
| UI plan and demo script | [frontend/PLAN.md](../frontend/PLAN.md), [frontend/DEMO.md](../frontend/DEMO.md) |
| Overnight history (logs, release review, old instructions) | [archive/2026-11-05-overnight/](archive/2026-11-05-overnight/) |
