# Master plan: remaining build

**This is the single planning document for the rest of the build.** It replaces the overnight agent instructions, the
overnight logs' "next steps" and "tomorrow" sections, the expanded modeling plan and the release review's deferred list
(all now in [docs/archive/2026-11-05-overnight/](archive/2026-11-05-overnight/)). If a priority or assignment here
conflicts with another document, this one wins. Detailed packet specifications stay where they are (see [Document map](#document-map)).

Originally written 5 November 2026 against `dev` at `e0e0fcf` (legacy PR #106).
**Status reconciled 5 November 2026, 13:06 EST**, against `dev` at `3ababad` (PR #18); PR #13 remains open.
This is a documentation reconciliation, not a new test run or release approval. Use the `dev` version; `main` is
the release branch and does not yet contain this plan. The repo now lives at
[fleethacker/pier-review](https://github.com/fleethacker/pier-review); its default branch is `main`, so **always open PRs
with `--base dev`**.

**Requirements audit update, 5 November 2026:** [§11](#11-requirements-audit-remediation-prompts) contains the
implementation prompts for the requirements reviewed at `851ae24`, checked against the audit baseline at `91ac18a`.
Only the fielding-brief files changed between those commits; that item is excluded from this follow-up.
The original build snapshot is historical; use §11 alongside the camera plan for the new gaps, owners,
dependencies and acceptance criteria. This update adds planned work, not completed implementation.

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
| **Snyder — Mike Snyder** (`DDL-Mike-Snyder`) | Modeling: simulation runtime and physics (Claude session + GPT session) | S, P | [§4](#4-snyder-modeling-claude-session--gpt-session) |
| **Kori — Michael Kori** (`DDL-Michael-Kori`) | UI | U | [§5](#5-kori-ui) |
| **Cruz — Jimmy Cruz** (`MineSweeperKing-IT`) | Data connections | D | [§6](#6-cruz-data-connections) |
| **Bixler** (`michaelabix`) | Agents, integration, release, and any odd jobs not owned by someone else | A | [§7](#7-bixler-agents-integration-release-and-odd-jobs) |

If you are an AI agent working for one of these people: read this whole file, then work **only** on your person's
items and files, in priority order, following [§8](#8-coordination-rules) and [§10](#10-parallelizing-with-sub-agents-sonnet-55-and-gpt).

| | |
| --- | --- |
| **Build ends** | Not scheduled; Bixler records the agreed date/time/timezone before setting freeze or rehearsal |
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

**Current integration:** P1 forecast resolution (#4), P2 rechecks (#8), initial P3 benchmarks (#5), S1 rich runtime
frames/recordings (#6), and the agents/demo baseline (#7) are merged. S5/S6 landed in #10; #14 added S6 fixes plus the
initial transit-based S7 prediction endpoint and U8 camera overlay. The original S5/S6 review is not closed as a whole;
see the [finding disposition](MODELING_BUILDOUT_STATUS.md#pr-10-review-disposition). Kori's U1–U7 UI landed in #18.
#12 added R1–R9 specifications; #16 added the camera demo script. Merged implementation is not physical qualification.

**Implemented on PR #22 (Snyder lane), merged to `dev` via PR #22 (not yet cross-reviewed):** S2 forcing, S3 wiring, S4 surrogate, P5 horsepower
plan, P6 ultimate gust (basis-required), S8 sequence search and the P3 S2/S3 benchmarks, with regenerated contract. Details and
limits are in the [integration status](#integration-status) rows and the
[capability ledger](MODELING_BUILDOUT_STATUS.md#snyder-lane-additions-pr-22). Merged is not qualified: all of it is synthetic and
unqualified, and it adds no sourced ultimate capacity, GM, roll/pitch or tug-position physics.

**Implemented on a branch, not integrated:** Cruz's D1–D4 providers, composition, replay and waves are in open
[PR #13](https://github.com/fleethacker/pier-review/pull/13), with a separate reviewer completing it. Do not duplicate
that implementation or claim its endpoints are on `dev` before merge. Its existing reviewer owns that review/merge;
Cruz publishes the final contract and limitations afterward.

| Remaining work | Lead and dependency |
| --- | --- |
| Close remaining S5/S6 findings with independent evidence | Snyder backend/physics; Kori UI; [finding ledger](MODELING_BUILDOUT_STATUS.md#pr-10-review-disposition) |
| S2/S3 cross-review and merge (PR #22); S7 state fidelity, berthing engine, hazard coverage and uncertainty gates | Snyder; S2/S3 implemented on #22 pending review; S7 engine/forcing handoff, D2/D8 as they land; retain current camera limits |
| D1–D4 review/merge and U3/U4 integration with final provider contracts | Cruz and existing #13 reviewer; Kori/Bixler integration |
| A3 common forecast revision through Intake, Planner, Safety and watch | Bixler; P1/P2 exist, public revision discovery needs D2 |
| D8 own-ship state; D5 refit/telemetry; D6 charts/UKC | Cruz; source/age/quality contracts and physical evidence required |
| R1–R9 requirements remediation | Named leads and reviewers in [execution ownership](#execution-ownership) and [§11](#11-requirements-audit-remediation-prompts) |
| Combined UI/API/camera acceptance, actual hosting rehearsal and deliberate release | Bixler; Kori browser, Snyder modeling and Cruz source evidence |

The [archived data/simulation review](archive/2026-11-05-overnight/instructions/04-data-simulation-next-steps.md)
remains the detailed packet specification. Its baseline and old next steps are historical. Legacy S00–S21 in the
modeling execution plan are different IDs from this plan's S1–S8: legacy S17 is the runtime extended by current S1.

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

Requirements-audit closure has the additional acceptance criteria in [§11](#11-requirements-audit-remediation-prompts).
Track software completion and engineering/source qualification separately; a passing baseline demonstration does not
close an uncovered requirement.

**Cut order if time runs short** (cut from the bottom): approach/ENC (D6) → telemetry (D5b) → uncertainty refit (D5a) →
waves (D4, S4) → tug kinematics and heel (S3) → composed public forecast (D2: fall back to recorded/synthetic series,
labeled) → sim-time forcing (S2). Never cut: items 1–3, rm0 live frames (S1), source-selection honesty (D1), the
backup-camera story (item 7, at least without the uncertainty corridor), item 8.

## 3. Team and ownership

Four people (see [Who is who](#who-is-who)). Ownership is by **files**, so parallel work rarely conflicts. Cross-boundary edits: small, additive, and
announced to the owner in the PR description.

| Person | Workstream | Owns (write access by default) |
| --- | --- | --- |
| **Snyder** (modeling lead; Claude session + GPT session) | **M**: simulation runtime and modeling physics | `modeling/mooring/berthing/`, `mechanics/`, `loads/`, `moored/`, `tugs/`, `rules/`, `data_simulation/`, `missions/`, `transit/`, `prediction/`, `modeling/modeling_api/{sim_sessions.py,ws.py}`, routers `berthing.py`, `moored.py`, `loads.py`, `missions.py`, `transit.py`, `prediction.py`, schemas `missions.py`, `transit.py`, `prediction.py`, `motion.py`, `dynamics.py`, `forecast_planning.py`, `planning.py`, `mooring.py`, `risk.py` |
| **Kori** | **U**: UI | `frontend/`, `frontend/DEMO.md` |
| **Cruz** | **D**: data connections | `modeling/mooring/environment/`, `telemetry/`, `approach/`, `core/forecast_provenance.py`, routers `env.py`, `telemetry.py`, `approach.py`, schemas `environment.py`, `telemetry.py`, data `scripts/` (`fit_uncertainty.py`, `record_provider_fixture.py`, `smoke_coops.py`), `docs/DATA_SOURCES.md`, `docs/DC*.md` |
| **Bixler** | **A**: agents, integration, release, odd jobs | `agents/`, `scripts/demo_check*.py`, `Makefile`, `app.sh`, `.github/`, `contract/README.md`, `README.md`, this plan, `docs/DEPLOYMENT_READINESS.md`, refdata/qualification (`refdata/`, `qualification.py`, `templates.py`, `routers/{refdata,qualification,system}.py`) |

Shared, single-writer-at-a-time: `modeling/modeling_api/main.py`, `core/schemas/__init__.py`, `common.py`,
`scenarios.py`, `contract/` (generated; see [§8](#8-coordination-rules)).

### Execution ownership

This is the handoff for remaining work. **Lead** owns delivery and status; collaborators own their existing files;
**reviewer** is the next independent review assignment, not evidence of an approval already given. Snyder's M-SIM
and M-PLAN sessions cross-review; an author must not approve their own change. If the named reviewer contributes
implementation, choose another non-author reviewer under §8. Source/engineering qualification still requires the
specific evidence and competent review named by the packet.

Before starting, claim the item in its PR and link it from the status board. Reuse existing open PRs; coordinate
shared files before editing. Supporting plans inherit these assignments rather than establishing another queue.

| Work to execute | Lead | Collaborators | Independent reviewer | Dependency / next deliverable |
| --- | --- | --- | --- | --- |
| S5/S6 backend findings | Snyder M-SIM | Cruz for coastline/source evidence; Kori for UI behavior | Snyder M-PLAN | [Finding ledger](MODELING_BUILDOUT_STATUS.md#pr-10-review-disposition); fixes and per-finding closure |
| S5 UI findings 12–16 | Kori | Snyder for authoritative track/location API | Bixler; Snyder for geometry semantics | Existing mission API; race, playback/geometry and authenticated-media regressions |
| S2; S7 forcing/state/engine extensions | Snyder M-SIM | Snyder M-PLAN, Cruz, Kori | Snyder M-PLAN | Merged S1/P1; D2/D8 when available; state fidelity and immutable forcing before broader camera claims |
| S3 tug geometry/vertical motion | Snyder M-SIM | Cruz for inputs; Kori for supplied DOFs | Snyder M-PLAN | S2/geometry and supported physical data; explicit unavailable DOFs |
| S4 wave surrogate | Snyder M-PLAN | Cruz, Snyder M-SIM | Snyder M-SIM | D4 schema after #13; seeded synthetic response with no total/partition double counting |
| P3 independent benchmarks | Snyder M-PLAN | Snyder M-SIM; Cruz for source fixtures | Snyder M-SIM | Extend with each S2/S3/S7 or R-packet change; independent analytical evidence |
| P4 / R4 NSTM/directional limits | Snyder M-PLAN | Bixler evidence intake | Snyder M-SIM | Authorized edition and applicable ratings; rule/evidence inventory first |
| P5 / R5 tug optimization | Snyder M-PLAN | Bixler, Kori | Snyder M-SIM | Objective/placement contract and sourced fleet inputs; publish consumer fixtures |
| P6 / R6 ultimate gusts | Snyder M-PLAN | Bixler, Kori | Snyder M-SIM | Supported material/capacity law and wind basis; no invented breaking threshold |
| P7 / R8 bollard strain | Snyder M-PLAN | Bixler data intake; Kori display | Snyder M-SIM plus required structural reviewer | P4 loads, approved geometry/material/foundation data and structural specification |
| S8 / R7 sequence search | Snyder M-SIM | Snyder M-PLAN, Kori, Bixler | Snyder M-PLAN | Handling constraints and intermediate states; P5 contract for new tug fields |
| U1–U7 assembled acceptance | Kori | Bixler, Snyder, Cruz | Bixler | #18 merged; verify combined browser/API behavior and final #13 contract; conditional displays do not implement S2/S3 |
| U8 camera extensions | Kori | Snyder, Cruz, Bixler | Bixler; Snyder for prediction semantics | Initial overlay merged; follow supported S7/D8 state, warnings and uncertainty |
| U9 / R2 canvas editing | Kori | Snyder for pose/line semantics | Bixler | Existing contracts; two-axis placement and fitting-to-fitting drag proof |
| U9 / R3 class capability display | Kori | Bixler, Snyder | Bixler | A8 capability contract; missing fittings remain unsupported |
| U10 / R6 gust display | Kori | Snyder, Bixler | Bixler | P6/A9 results; distinct working-load and ultimate-load warnings |
| U11 / R7 sequence display | Kori | Snyder, Bixler | Bixler | Existing step fields first, then S8 results; preserve draft/review state |
| U12 / R8 strain display | Kori | Snyder, Bixler | Bixler | P7 reviewed result contract; show unavailable reasons until supported |
| U13 / R1 sheet layout UI | Kori | Bixler, Snyder | Snyder M-PLAN | A11 immutable layout/version fixture; never capture a subsequently edited canvas |
| D1–D4 integration | Cruz | Kori, Snyder, Bixler | Snyder's separately assigned #13 reviewer | Finish #13; publish final source/forecast/wave contracts and remaining limitations |
| D8 own-ship state / promoted D5b subset | Cruz | Snyder, Kori | Snyder M-PLAN | State/age/quality interface and recorded/live distinction; no silent stale extrapolation |
| D5a uncertainty refit | Cruz | Snyder M-PLAN | Snyder M-SIM | At least 365 usable days and event holdout; fitted does not mean qualified |
| D5b remaining telemetry arbitration | Cruz | Snyder, Kori | Snyder M-PLAN | Opt-in source policy and provenance; share D8 interface rather than duplicate it |
| D6 ENC/approach/UKC | Cruz | Snyder, Kori | Snyder M-PLAN | Source/edition/datum/coverage and supported squat; mock remains until replaced |
| A0 repository controls | Bixler | Repository administrator; all teammates | Snyder | Confirm protection and documented `dev` integration workflow |
| A1 combined acceptance | Bixler | Kori browser; Snyder modeling; Cruz sources | Snyder; Kori for browser evidence | Reconcile #18 and final #13, include S7 camera; retain uncovered gates |
| A2 target hosting | Bixler | Kori, Snyder | Kori | Actual target and clean checkout; HTTP/SSE/WS and HTML/PDF evidence |
| A3 forecast agent binding | Bixler | Snyder, Cruz, Kori | Snyder M-PLAN | P1/P2 available; supplied/scenario manifest now, D2 for public revision lookup |
| A4 release | Bixler | All workstream owners | Snyder; Kori for browser gate | Combined acceptance/target evidence; deliberate `dev` → `main` PR and tag |
| A5 real-provider vision rehearsal | Bixler | Kori | Snyder | Guarded paths already merged; provider/fixture/target evidence without weakening fallback |
| A6 plan/status maintenance | Bixler | All workstream owners | Snyder | Update at each merge; retain historical test counts with their revisions |
| A7 camera narration | Bixler | Snyder, Kori | Snyder M-PLAN | Existing S7 result contract; cite immutable IDs and code-owned warnings |
| A8 / R3 class inputs | Bixler | Snyder, Kori | Snyder M-PLAN | Approved class fitting data and capability gates; importer is not qualification |
| A9 / R6 Safety integration | Bixler | Snyder, Kori | Snyder M-PLAN | P6 threshold contract; preserve assessed forecast/configuration and existing WLL checks |
| A10 / R9 acceptance evidence | Bixler | Kori, Snyder, Cruz | Snyder; Kori for browser checks | Integrate R1–R8 incrementally; do not count unavailable capability as complete |
| A11 / R1 sheet layout backend | Bixler | Kori, Snyder | Snyder M-PLAN | Frozen plan/review/geometry contract and reproducible renderer before U13 |

## 4. Snyder: modeling (Claude session + GPT session)

Snyder runs two coding sessions at once. Split them by **file ownership**, not by task type, so they never edit the same
file, and use each as the other's independent reviewer.

| Session | Lane | Files (exclusive) |
| --- | --- | --- |
| **Claude (M-SIM)** | Close S5/S6 findings; extend merged S1/S7 with S2 → S7 state/forcing/engine gates → S3; S8 follows its handling-constraint contract | `berthing/`, `sim_sessions.py`, `ws.py`, `routers/berthing.py`, `schemas/motion.py`, `schemas/dynamics.py`; `missions/`, `transit/`, `routers/{missions,transit}.py`, `schemas/{missions,transit}.py`; `prediction/`, `routers/prediction.py`, `schemas/prediction.py`; coordinate shared schema exports/contract generation |
| **GPT (M-PLAN)** | P1/P2 merged; P3 continuous benchmarks; P4/P6 evidence and contracts, then P5; S4 after D4, P7 after structural evidence | `moored/`, `loads/`, `mechanics/`, `tugs/`, `rules/`, `data_simulation/`, `routers/{moored,loads}.py`, `schemas/{forecast_planning,planning,mooring,risk}.py` |

Rules for the two sessions:

- Each session works in its own worktree and branch (`ws-e/<item>` for Claude, `ws-b/<item>` for GPT), from the current `dev`.
- **Cross-review:** every PR from one session is reviewed by the other before merge, with the prompt "find correctness bugs;
  do not restate the author's intent". GPT also writes the **independent analytical benchmarks** for Claude's dynamics
  (S1–S3), because a benchmark written by the same session that wrote the code is weak evidence.
- Only one session at a time runs `make contract`. Convention: the session that merges first regenerates; the other merges
  `dev` and reruns `make contract` before its own PR.
- Snyder resolves design disagreements between the two sessions; neither session overrides the other's files.

### M-SIM (Claude session)

The text below defines acceptance scope. S1 is merged; S5/S6 and initial S7/U8 are implemented with remaining
review/capability limits. Start from [execution ownership](#execution-ownership), not a duplicate implementation.

**S1 (P0). Publish live rm0-v1 frames, scene and recordings.** Spec: data/simulation review packet 3,
[MOTION_FRAME_DESIGN.md](MOTION_FRAME_DESIGN.md). Populate identity (session, run, sequence, scene id/revision), six-component
pose with unsimulated DOFs flagged, tug state, line endpoints/polylines with fitting IDs, fitting loads, fender compression,
force breakdown and environment-at-t from actual simulator state; absent means unavailable, never zero. Add
`GET` scene route, bounded persisted recordings (list/fetch/replay), lifecycle messages, reconnect-from-sequence, and a
speed control that scales scheduler wall time, not the physics step. Mind the frame conventions (berth +y off-pier, ship
sway +port, legacy `v_kt` toward-pier). The interface and captured examples are now published by #6; retain contract-first coordination for extensions. Acceptance: real HTTP/WS output validates against the
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
are fixed and independently re-reviewed, S6, with an explicit fixed-environment basis. The initial #14 service uses S6 with documented state approximations; it does not close all S7 acceptance gates. Recorded/synthetic initial states are acceptable, labeled, until
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

**S8 (P1). Constraint-based line sequence proposals.** [Prompt R7](#r7-line-sequences-s8u11). Replace the fixed default
ordering with a bounded search over supported handling constraints and intermediate static states. Coordinate the
`berthing/sequence.py` writer with S1–S3 and P2; Kori owns the sequence display (U11).

### M-PLAN (GPT session)

P1/P2 and initial P3 tests are merged. Extend those implementations; P4–P7 and S4 retain their dependencies.

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

Requirements-audit additions to the M-PLAN lane:

| ID | Pri | Work | Depends on |
| --- | --- | --- | --- |
| P4 | P0 | [R4: NSTM rule evidence and directional fitting utilization](#r4-nstm-and-directional-fitting-limits-p4) | Authorized source/edition and rating applicability for verified claims |
| P5 | P1 | [R5: minimize fleet horsepower and report placement feasibility](#r5-tug-horsepower-and-placement-p5) | Agreed optimization objective/result contract; sourced fleet and push-point inputs for qualification |
| P6 | P0 | [R6: modeled ultimate-load gust thresholds](#r6-ultimate-load-gust-assessment-p6a9u10) | Supported material/capacity law and wind basis; A9/U10 consume the result |
| P7 | P2 | [R8: structural bollard strain capability](#r8-structural-bollard-strain-p7u12) | Structural model specification and approved geometry/material/foundation data; P4 result loads |

P3 supplies independent checks for these packets as well. Reserve shared solver/schema files sequentially; the new
packets do not change S1–S3's ownership or turn physical qualification into a software-only gate.

## 5. Kori: UI

Read [MODELING_UI_RECOMMENDATIONS.md](MODELING_UI_RECOMMENDATIONS.md) (backend capabilities with wire details) first.

| ID | Pri | Work | Depends on |
| --- | --- | --- | --- |
| U1 | P0 | **Explicit Intake and independent Safety-review selection** in the planning flow; show the review identity on the sheet; four-case choice with initial vs final outcome shown separately | none (backend done) |
| U2 | P0 | **Live motion on rm0-v1**: consume S1's scene route, rich frames, lifecycle, recordings list/playback, speed control (enable the disabled control), reconnect-from-sequence; draw tugs/lines/fittings/forces/env from live frames | S1 merged (#6); combined UI/API acceptance |
| U3 | P1 | **Per-component environment availability** (wind/current/tide/forecast/waves): source, state, age, basis; misconfiguration error state | D1 in open #13; preserve unavailable/error states |
| U4 | P1 | **Advance-planning panel**: as-of, arrival ≥24 h, holding duration, coverage and provenance preview, alternatives table, apply `selected_config` (keep paid-out lengths and installation tide), "recheck required" on changed inputs | P1/P2 merged; D2 in open #13; supplied series available |
| U5 | P1 | Simulation-time display (sim time vs wall time, forcing revision) and training-scenario controls (seed, source, persistent "training" label) | S2 |
| U6 | P2 | Upgrade test toolchain to clear the 13 dev-dependency findings (Vitest/Tinypool/Vite); compatibility-tested, no `npm audit fix --force` | none |
| U8 | P0 | **Backup-camera overlay** (north star): predicted path, hull footprints at time ticks, uncertainty corridor, contact/clearance warnings and what-if controls (rudder, engine, tug push) drawn over the live ship in the motion view and the transit view; refresh ≥1 Hz from S7 (`POST /predict/trajectory` or the session frame `prediction` field); validity and input age on the overlay. Build against S7 fixtures first | Initial S7 merged (#14); extensions follow S7/D8 |
| U7 | P2 | Cesium-scene motion view with roll/pitch and water surface when frames supply them; accessibility pass (contrast, screen reader); profile React path at 10 Hz | S3 |
| U13 | P0 | [R1: display and print the layout frozen with the reviewed sheet](#r1-reviewed-sheet-layout-a11u13) | A11 layout contract and immutable fixture |
| U9 | P1 | [R2: two-axis ship placement and fitting-to-fitting line drag](#r2-two-dimensional-canvas-editing-u9); [R3: class capability display](#r3-additional-ship-class-support-a8u9) | Existing pose fields; A8 class capability contract |
| U10 | P0 | [R6: distinct working-load and ultimate-load gust warnings](#r6-ultimate-load-gust-assessment-p6a9u10) | P6/A9 contracts; labeled fixtures until available |
| U11 | P1 | [R7: sequence feasibility, draft/review state and step issues](#r7-line-sequences-s8u11) | Existing sequence fields first; S8 additions after contract publication |
| U12 | P2 | [R8: structural strain results and unavailable reasons](#r8-structural-bollard-strain-p7u12) | P7's reviewed result contract |

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
| A11 | P0 | [R1: immutable graphical layout in the Safety Sheet](#r1-reviewed-sheet-layout-a11u13); coordinate the sheet/layout contract with U13. |
| A8 | P1 | [R3: additional ship-class fitting data and capability gates](#r3-additional-ship-class-support-a8u9); track approved input requests and distinguish importer completion from class qualification. |
| A9 | P0 | [R6: Safety review/watch consume modeled ultimate-load thresholds](#r6-ultimate-load-gust-assessment-p6a9u10); preserve assessed source/revision and existing working-load warnings. |
| A10 | P1 | [R9: local requirements acceptance and evidence](#r9-requirements-acceptance-and-evidence-a10); integrate R1–R8, with Snyder's independent modeling benchmarks and Kori's browser checks. |

## 8. Coordination rules

- **Git:** branch from current `dev` on `fleethacker/pier-review` and open PRs with `gh pr create --base dev`; one item per PR; `<area>/<item-id>-<short-name>` with areas
  `ws-e` (M-SIM), `ws-b` (M-PLAN), `ui`, `ws-a` (data), `agents`, `fix`, `docs`; put the item ID (S1, U2, D1…) in the PR
  title. Never force-push or push directly to `dev`/`main`. One approval (another person, or Snyder's other session for his
  PRs) and green CI before merge. Merge `dev` into your branch at least every 2 hours.
  Use unsigned commits (`git -c commit.gpgsign=false commit ...`).
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

The original T0 schedule is superseded by this dependency order. Bixler records agreed freeze/rehearsal dates;
elapsed time or a merged demonstration is not a release gate.

| Order / gate | Next deliverable | Lead; collaborators |
| --- | --- | --- |
| Now: integration and correctness | Finish existing #13 review; close S5/S6 findings; rehearse #18 against S1/P1/P2/S7, then D1/D2 contracts | Cruz + existing #13 reviewer; Snyder/Kori for findings; Bixler for assembled acceptance |
| Now, independent packets | A11/U13 sheet-layout contract; U9 canvas editing; A8 class-data intake; P4 rule/rating evidence; P6 ultimate-load specification; A10 incremental acceptance | Bixler, Kori and Snyder per [execution ownership](#execution-ownership) |
| On existing S1/P1 interfaces | S2 forcing/state and P3 benchmarks; A3 agent revision binding against supplied/scenario fixtures | Snyder M-SIM/M-PLAN; Bixler; Cruz supplies public series |
| On existing S7 interface | A7 cited narration, remaining U8 integration and D8 own-ship state | Bixler, Kori, Cruz; Snyder owns prediction semantics |
| After required source/contracts | S7 extensions, S3/S4, P5/P6 consumers and S8; P7 after structural specification/data | Named packet leads; unavailable/unqualified output remains where evidence is missing |
| Milestone release | Combined modeling/UI/source/agent evidence, demo checks, actual target rehearsal, reviewed `dev` → `main` PR, notes and tag | Bixler; all owners supply evidence |
| Freeze/rehearsal | Features stop before agreed rehearsal; fixes/docs only thereafter; clean `main` on actual target | Bixler coordinates; owners resolve their failures |

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
Repo: fleethacker/pier-review, base branch <item branch>, your worktree/branch <name>.
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
| M-SIM S2/S7 (Snyder, Claude) | Stage-time forcing adapter; immutable state/engine snapshot; hazard/state regressions; coordinator owns shared schemas and integration. Do not rebuild merged S1. |
| M-PLAN (Snyder, GPT) | P4 source/evidence inventory; P6 specification; P3 independent benchmarks; S4 statistics after D4. Reserve shared solver files before implementation. |
| U (Kori) | U9 canvas; U13 against frozen A11 fixtures; U10 against P6 fixtures; U11 sequence display; separate combined U1–U7 browser acceptance. |
| D (Cruz) | Finish the existing #13 review first; D8 state adapter and provenance checks; D5 refit data/holdout audit; D6 only after higher-priority sources. No duplicate provider implementation. |
| A (Bixler) | A3 manifest propagation; A7 cited camera narration; A11 immutable sheet layout; A8 input intake; A1/A10 acceptance and A6 status updates. |

## 11. Requirements audit remediation prompts

**Scope and baseline.** These prompts address the partial requirements identified in the `851ae24` audit and still
present at `91ac18a`. The fielding brief is excluded. Audit evidence: **1,921 Python tests, 227 frontend tests**,
typecheck/lint/build and contract checks passed; the local API/browser baseline passed **27 checks with 6 readiness
checks skipped**. Those are audit results, not evidence that the new work below is complete.

Keep the already implemented mock wind/ebb/flood data, displacement, berth depth/tide inputs, wind/current vectors,
line configurations and static lateral-force calculations as regression requirements. Reference-position depth,
absent wave/wake loads and static rather than maneuvering assessments remain explicit model limits; full bathymetric
clearance, waves and transient maneuvering belong to their existing modeling/data packets. Do not expand this work
into autonomous vessel control. Automatic planning remains subject to independent review.

R1–R9 are stable cross-workstream tracking labels; the A/P/S/U IDs below retain file ownership.
To avoid collisions with the camera/storyboard tasks, R1 uses **A11/U13** and R7 uses **S8/U11**.
A7 remains camera narration, U8 remains the camera overlay, and S5 remains mission storyboarding. Every packet is **planned**.
The source dependencies in R3, R4, R6 and R8 must remain open until evidence arrives: an importer, an unavailable
result, a synthetic fixture or an honest label alone does not satisfy the corresponding missing capability.

| Packet | Gap to close | Implementation owners | Dependency / order |
| --- | --- | --- | --- |
| R1 | Safety Sheet has no immutable plan-bound graphic | A11 Bixler; U13 Kori | Publish layout snapshot contract, then renderer/UI |
| R2 | Ship drag is along-pier only; line editing is click-based | U9 Kori | Existing pose/line contract; coordinate shared UI files with R1/R3 |
| R3 | CG-47, LHD-1 and CVN-68 lack fitting layouts | A8 Bixler; U9 Kori | Approved class-specific inputs; software support can precede receipt |
| R4 | NSTM references unverified; fitting checks nominal-only | P4 Snyder; Bixler qualification handoff | Source edition and approved directional-rating method |
| R5 | Tug recommendations do not minimize horsepower | P5 Snyder; agent/UI handoff | Define objective and publish additive allocation contract |
| R6 | No defensible gust-to-breaking threshold or warning | P6 Snyder; A9 Bixler; U10 Kori | Supported ultimate-load model/evidence, then warning consumers |
| R7 | Fixed line order; incomplete sequence status display | S8 Snyder; U11 Kori; Bixler planner handoff | Handling constraints; R5 contract for new tug fields |
| R8 | Bollard structural strain is not calculated | P7 Snyder; U12 Kori; Bixler data/qualification handoff | R4 loads plus structural specification and approved asset data |
| R9 | No acceptance gate covering all audited requirements | A10 Bixler; Kori browser steps; P3 independent checks | Add checks as R1–R8 land; retain unresolved source blockers |

Start R1's contract, R2, R3's data intake and R4's evidence inventory independently. Reserve M-PLAN's shared solver
and schema files before implementing R4/R5/R6/R8. Publish P5/P6 result fixtures before agent/UI consumers; R7 can
start with existing tug contracts. Integrate R9 continuously. These priorities supplement the existing build gates;
they do not remove S1/D1 readiness requirements or permit a skipped requirement to count as complete.

### Shared execution prompt

Copy this with the selected packet's prompt. For a multi-owner packet, take only the named owner's slice; separate
contract, modeling, agent and UI PRs when ownership differs.

```text
Repo: fleethacker/pier-review. Start a new item branch from current dev; use unsigned commits.
Read all of docs/MASTER_PLAN.md, especially sections 3, 8, 10 and this packet. Recheck current code before editing.
Implement only the assigned packet/owner slice, preserving other owners' files. Agree additive interfaces and
labeled fixtures first. One coordinator generates contract/ with make contract; Kori regenerates frontend types
with npm run types. Never hand-edit generated contracts or types.
Use real modeling results in agents; agents must not calculate physics. Keep units, coordinate conventions,
source/forecast revisions, installation tide, paid-out lengths and validity through every consumer.
Never invent engineering inputs, source verification, approvals or qualification. Use docs/DATA_REQUESTS.md for
missing evidence; keep software completion separate from source and physical validation. Preserve offline/no-LLM
operation and synthetic labels. Do not weaken or skip existing assertions to make new behavior pass.
Run focused tests for changed behavior, then applicable Python/contract and frontend checks (npm commands run from
frontend/packages/web). Report exact commands, results, remaining dependencies and acceptance criteria not met.
Follow section 8 for PRs against dev and review; do not merge, publish operational approval, or mark a requirement
closed without its specified evidence.
```

### R1. Reviewed sheet layout (A11/U13)

```text
Goal: Every new supported Safety Sheet includes a reproducible graphic of the reviewed plan with its rationale
and margins, in the UI, printable HTML and PDF.
Read first: agents/mooring_agents/safety/{schemas.py,sheet.py}, planner/agent.py;
frontend/packages/web/src/apps/mooring/{agent.ts,agent.test.ts,panels/Overlay.tsx}.
Scope: A11 owns agents/, persistence and tests; U13 owns frontend consumption. Agree layout metadata and fixtures first.

Freeze the geometry/reference revisions used by the assessment, not just mutable catalog IDs. Bind the snapshot
to sheet/version, plan, review and analysis IDs. Render a deterministic, self-contained vector plan without a
network map or token. Show ship/berth, side-to, numbered lines/types and fitting IDs, scale/orientation, assessed
wind/current vectors and relevant tug assignments; distinguish berthing from continuous holding assistance.
Retain rationale, citations and line/bollard margins in the document. Invalid values remain unavailable.

Acceptance: UI, HTML and rendered PDF show the same saved layout and IDs. Catalog changes after assessment but before
sheet creation must not change the assessed geometry. Editing the canvas/catalog, reloading or restarting cannot
change an old sheet. Reassessment creates a new version; approval preserves its snapshot.
Legacy sheets without geometry report it unavailable instead of capturing the current map. Test persistence,
versioning, invalid-result labels and print/PDF rendering. Preserve the existing prohibition on unbound screenshots
while replacing the current image:null result for supported new sheets. The Safety Sheet has no one-page constraint.
```

### R2. Two-dimensional canvas editing (U9)

```text
Goal: Move a supported ship along and off the pier, and create/reconnect lines by dragging valid fittings.
Read first: frontend/packages/web/src/apps/mooring/{controller.ts,mapping.ts}, their tests,
panels/{SetupPanel.tsx,LinesPanel.tsx}; modeling/mooring/core/schemas/plans.py.
Scope: frontend/ only, including shared scene interaction code and tests where needed.

Map both drag axes into ship_x_ft and nonnegative standoff_ft for either side-to orientation. Keep side-to and the
existing pose contract: do not introduce visual yaw that modeling ignores. Snap line drops to valid ship/pier
fittings. Preserve line identity, type, parts, explicit paid-out length and installation assumptions; do not silently
retend installed lines. Retain click-to-connect and numeric/keyboard alternatives.

Acceptance: pointer drags change the actual modeling request in both axes; reconnect changes the correct fitting
ID. Invalid drops/cancellation preserve the prior configuration. An edit invalidates old margins immediately,
commit triggers reanalysis, and late responses cannot restore stale results. Cover both sides-to, placement bounds,
class/berth changes and line-type selection. A browser test performs real pointer drags and checks resulting request
geometry, updated analysis and numbered-berth selection. Coordinate U9's class-selector changes with R3.
```

### R3. Additional ship-class support (A8/U9)

```text
Goal: Support full mooring planning for the advertised classes using their own fitting and loading data.
Read first: modeling/mooring/refdata/ships/, templates.py, qualification.py, core/schemas/refdata.py,
frontend/packages/web/src/apps/mooring/panels/SetupPanel.tsx; docs/DATA_REQUESTS.md.
Scope: A8 owns refdata/import/qualification, templates.py and associated routes/tests; U9 owns capability display/action
gating. Coordinate template callers and shared reference-schema changes with Snyder and the contract writer.

Publish a class capability matrix separating environmental loads from mooring/sequence support. Validate approved
class/loading-specific fitting/chock schedules, SWL and lead restrictions, line inventory and permitted tug points,
including stable IDs, frames, units, revisions and loading applicability. Add import/validation support before data
arrives. CG-47, LHD-1 and CVN-68 remain blocked for full planning until adequate per-class records are supplied.
Never copy or scale the DDG layout. Synthetic test records must not become qualified catalog assets.
Replace templates.py's hard-coded six BITT-{1..6}{P/S} assumption with class-specific supported templates or validated
geometry/role selection. Missing arrangements or too few usable fittings must return a capability reason, not KeyError.

Acceptance: reject duplicate IDs, bad references, incompatible frames/units and missing required data. Each class
advertised as fully supported completes template, geometry, equilibrium, sequence and sheet using its own inputs.
Hull-only selections explain missing capabilities and clear stale lines/results from the previous class; API/UI
gates agree. Test each current unsupported class and an imported fixture with non-DDG fitting IDs/counts. Record
software support, actual data receipt and physical qualification separately; relabeling a selector does not close
missing class coverage.
```

### R4. NSTM and directional fitting limits (P4)

```text
Goal: Make NSTM checks traceable and evaluate fitting loads using the applicable directional capacity basis.
Read first: modeling/mooring/rules/nstm582.py, moored/solver.py, core/schemas/{mooring,refdata}.py,
qualification.py; modeling/tests/test_s01_qualification.py; docs/DATA_REQUESTS.md.
Scope: Snyder owns rules/solver and modeling tests; Bixler owns qualification/refdata consumers. Reserve shared schemas.

Inventory the exact NSTM 582 edition, supported arrangements and missing/partial rules. Reconcile registry text
against code, including the opposing-spring exception. Record source/reference, applicability, verification evidence
and reviewer; source_verified stays false without evidence. Implement applicable gaps within the declared scope;
unsupported arrangements must remain explicit blockers to broader compliance claims.
Preserve attached-line resultant components and load direction. Select nominal/horizontal/45-degree capacity only
through a sourced applicable method; expose selected basis and governing utilization. Do not invent angle
interpolation or silently substitute nominal capacity for an unsupported directional assessment.
Preserve per-line force vectors and attachment references so R8 can form structural loads when validated application
geometry is supplied; a net force alone must not be treated as a complete structural load case.

Acceptance: independent cases cover horizontal/45-degree and unsupported intermediate angles, multiple/opposing
lines, overload boundaries, missing SWL/ratings and prohibited fittings. Missing evidence propagates through
Planner, Safety and sheet. Synthetic fixtures verify algorithms without verifying NSTM citations. Record source
blockers and remaining rule coverage; passing tests alone cannot establish full NSTM compliance. Call these outputs
bollard load/utilization; literal structural strain is a separate R8 deliverable.
```

### R5. Tug horsepower and placement (P5)

```text
Goal: Recommend the lowest total catalog horsepower fleet within a declared feasible allocation domain, with
automatic permitted-point placement and an honest optimality result.
Read first: modeling/mooring/tugs/allocation.py, moored/holding.py, core/schemas/tugs.py;
modeling/tests/{test_s08_s09_tugs,test_tug_assignment_validity}.py; planner and UI tug consumers.
Scope: M-PLAN owns allocation/holding and tests; M-SIM owns berthing/service.py's adapter. Publish a joint-condition
request/result contract and fixtures before Bixler's planner and Kori's tug consumers change.

Replace count-first allocation and first-passing holding selection with a documented horsepower objective, stable
tie-breakers and bounded search. Use rated bollard pull for force feasibility; never convert horsepower to force.
Honor permitted points/directions, individual limits, unique tugs/points, force and yaw balance, and every required
environmental condition under an explicit placement/availability policy. Report optimum within the stated domain,
best found, infeasible or indeterminate with objective, tolerances and termination evidence. Search exhaustion is
not proof of optimality. Recheck selected assignments with the real equilibrium solver.
Replace Planner's per-condition solve/largest-lateral-result shortcut with the joint-condition result; retaining one
condition's fleet must not imply it covers the rest. Preserve each condition's assignment and feasibility evidence.

Acceptance: independently enumerate small fleets, including lower-HP multiple tugs beating one higher-HP tug and
a later holding candidate beating the first feasible choice. Cover yaw, unsupported surge, empty fleet, ratings,
both sides-to, unknown points, multiple conditions and exhausted search. Include a case where a lower lateral load
governs fleet feasibility because of yaw, direction or availability. Planner/UI/sheet retain the selected fleet,
HP, force, station/bearing and rationale, distinguishing berthing from holding assistance. Retain seed/limited labels;
this is bounded static placement planning, not a maneuver trajectory or unrestricted global optimum.
```

### R6. Ultimate-load gust assessment (P6/A9/U10)

```text
Goal: Establish a defensible modeled line ultimate-load gust threshold, then warn against it separately from WLL.
Read first: modeling/mooring/moored/envelopes_real.py, mechanics/lines.py, core/schemas/risk.py;
agents/mooring_agents/safety/{agent.py,checks.py,schemas.py,sheet.py}; agents/tests/test_safety.py;
docs/WIND_BASIS_REVIEW.md and docs/DATA_REQUESTS.md.
Scope: P6 owns modeling and threshold contract; A9 owns review/watch/sheet; U10 owns warning display. Implement in
that order using labeled fixtures for consumer development. Coordinate shared schema/solver writers with P4/P5.

Define the sourced effective ultimate capacity, material-law range, wet/condition/termination factors, wind
duration/reference-height basis and uncertainty. Search with the actual supported equilibrium/load-sharing model;
do not multiply the WLL gust by a square-root design factor or extend an unsupported material law. Return governing
line/direction, threshold, margins, provenance and validity. Missing evidence, earlier component failure, unresolved
instability, search ceiling or nonconvergence must return unavailable/indeterminate with reasons. Separate the existing
WLL envelope's stopping rule from physical capacity loss: crossing WLL remains a warning, while continuation needs
a supported material/load-sharing domain. Unsupported component behavior or established capacity loss stops it.
Distinguish reaching modeled ultimate capacity from validated prediction of physical rupture; a real breaking claim
needs its own validation evidence. Keep that requirement open if only the former is established.

A9 consumes results without computing physics, retains the existing 80%/100% WLL warnings, and documents a separate
ultimate-threshold warning policy. Bind review/watch/UI/sheet to the same source, forecast revision, configuration
and assessed conditions; changed inputs require reassessment, and source failure never substitutes another provider.

Acceptance: independent analytical synthetic cases, directional/governing-line changes, zero-wind failure, numerical
bracketing/tolerances, supported WLL crossing before ultimate capacity, unsupported material range and another
component failing first. HTTP/SSE tests cross warning boundaries and exercise unavailable/stale inputs and provider
failure. UI/sheet distinguish WLL and ultimate margins with citations. Preserve existing null-breaking assertions
for unsupported cases; only explicitly supported fixtures
may gain thresholds. Software tests cannot qualify a rupture prediction or the seed assets.
```

### R7. Line sequences (S8/U11)

```text
Goal: Automatically propose a feasible line-handling order with explicit intermediate-state evidence and review state.
Read first: modeling/mooring/berthing/sequence.py, modeling/tests/test_s13_sequence.py;
agents/mooring_agents/planner/agent.py; frontend/packages/web/src/apps/mooring/{agent.ts,panels/SequencePanel.tsx}.
Scope: S8 owns sequence generation/validation and modeling tests; U11 owns display. Bixler integrates planner output.
Reserve sequence.py against S1–S3/P2; consume R5's published tug fields rather than duplicating allocation logic.
Agree search-outcome fields with M-PLAN, which owns core/schemas/planning.py, before publishing consumer fixtures.

Replace the unexplained fixed order with a documented bounded search over available lines, roles, crews/stations,
dependencies and supported handling constraints. Check every intermediate restraint state with the real model,
including tug availability/release. Preserve installation tide, paid-out lengths, parts, environmental revision and
cited tug plan. Report no feasible sequence separately from budget-limited/unsupported search. Do not infer sequence
safety from final equilibrium or invent procedure timing. Keep draft_unreviewed until an actual authorized review.
Any required state_ok=None/PARTIAL_RESTRAINT makes feasibility indeterminate unless explicit modeled assistance
establishes restraint; absence of RED findings is insufficient.
Expose step state_ok, issues, limitations and review status in the panel and sheet. Apply completed proposals to the
proper canvas/panel while preserving the distinction between berthing and continuous holding assistance.

Acceptance: a case where the default order fails but an alternate passes; no feasible order; search exhaustion;
crew/dependency cycles; missing lines; unresolved partial restraint that cannot pass; doubled parts and tug release.
Test automatic application, stale-result invalidation and visible draft/blocking status through the browser.
Source-backed crew procedure review remains distinct from successful static validation; this packet does not
certify transient execution.
```

### R8. Structural bollard strain (P7/U12)

```text
Goal: Address the literal structural-strain requirement without relabeling capacity utilization as strain.
Read first: modeling/mooring/moored/solver.py, mechanics/, core/schemas/{mooring,refdata,qualification}.py;
docs/DATA_REQUESTS.md; R4's fitting load and source-evidence contract.
Scope: Snyder owns a separately scoped structural model/API and tests; Bixler coordinates asset inputs/qualification
and agent output; U12 Kori consumes the agreed result. Specify new files/contracts before implementation.

First define the supported fitting/foundation model, load application geometry and output location/strain component,
with an independent structural reviewer. Obtain approved section geometry, material properties, foundation/anchorage
boundary conditions, condition, applicable load range and validation references. Record this additional data request.
Then implement the reviewed model using individual attachment forces/application points or an equivalent force and
moment at a declared structural reference, preserving model/input revisions and validity. R4's net resultant
alone is insufficient for offset loads; missing application geometry remains unavailable. Keep load utilization and
dimensionless strain as separate fields with separate evidence; neither implies the other.
Do not invent elastic modulus, section properties or a universal strain-from-capacity conversion.

Acceptance: independent analytical cases within the declared model, unit/frame checks, load direction, multiple-line
loads (including cancelling forces with a nonzero couple), missing asset properties and out-of-domain loading.
Unsupported fittings return strain unavailable with reasons throughout API/UI/sheet. Qualified strain needs
asset-specific evidence and independent review. API plumbing or a toy fixture may finish first, but the literal
requirement stays open until the model and real inputs are supplied.
```

### R9. Requirements acceptance and evidence (A10)

```text
Goal: Demonstrate the audited requirements locally and identify every remaining software or engineering evidence gap.
Read first: scripts/demo_check*.py, Makefile, docs/LOCAL_REHEARSAL.md, docs/MODELING_BUILDOUT_STATUS.md;
R1–R8 acceptance criteria and the existing four-case/forecast checks.
Scope: Bixler owns integration scripts/CI/evidence; Kori owns frontend browser helpers; Snyder/P3 supplies independent
physics benchmarks. Extend A1's framework instead of creating a duplicate. Exclude the fielding brief from this gate.

Run isolated local services and a real browser offline with no LLM key and labeled deterministic fixtures. Exercise
class/pier/line-type selection, both drag axes, line reconnect, stale-result clearing, Intake → Planner → independent
Safety → sheet → approval/print. Inspect the saved graphic and IDs in HTML/PDF, then edit the canvas/catalog and
reload/restart to prove immutability. Preserve supported/overloaded/invalid/underconstrained outcomes.
Add fleet objective/placement, sequence intermediate states, directional capacity, ultimate-threshold warnings and
structural-strain availability checks as their packets land. Cover every class claimed supported; missing class data
must remain a named blocker. Retain displacement/depth/tide/vector/mock-current/line/static-force regressions.

Acceptance: each requirement maps to an API/browser or independent numerical check and an evidence status. Record
model/input revisions, reference, domain, expected result and predeclared tolerance for physics benchmarks. Separate
algorithm verification, source completeness and physical qualification; investigate discrepancies rather than tuning
coefficients to pass. Track test_loads_ufc.py::test_f_shallow_beam_current_to_wind's conditional expected-failure path
and whether it triggers; resolve reference applicability before removing that discrepancy guard.
Missing data or skipped coverage fails the relevant closure claim. A job claiming PDF support
must render and inspect an actual PDF; an HTML-only fallback is reported as such. Keep existing readiness gates.
Run make test, make contract-check, frontend typecheck/lint/test/build, make demo-check and make demo-check-readiness.
Report exact commands, counts, remaining blockers and owners. No Domino deployment is required for this follow-up.
Update this plan and the capability ledger only with observed evidence; do not mark source-dependent requirements
complete on synthetic tests.
```

## Status board

Bixler updates this table; everyone else posts in the team channel.

### Requirements audit follow-up

Requirements prompts merged in [PR #12](https://github.com/fleethacker/pier-review/pull/12); their audit baseline
was `91ac18a`. Implementation acceptance remains open. Use the primary leads and review assignments in
[execution ownership](#execution-ownership); the planning merge did not complete these requirements.

| Item | Owner | State | Blocker / next evidence |
| --- | --- | --- | --- |
| R1 / A11 U13 reviewed layout | Bixler / Kori | planned | Frozen layout contract and rendering/version tests |
| R2 / U9 canvas editing | Kori | planned | Two-axis request updates and pointer-drag browser proof |
| R3 / A8 U9 class coverage | Bixler / Kori | planned; class data required | Approved CG-47/LHD-1/CVN-68 fitting inputs; importer and capability tests |
| R4 / P4 NSTM/directional limits | Snyder / Bixler | planned; source verification required | Edition/rating method and rule-by-rule evidence |
| R5 / P5 fleet horsepower | Snyder | endpoint implemented on PR #22, awaiting review; sourced fleet data and consumers remain | Objective contract and independently enumerated optima |
| R6 / P6 A9 U10 ultimate gusts | Snyder / Bixler / Kori | P6 basis-required endpoint implemented on PR #22, awaiting review; physical evidence and A9/U10 remain | Supported capacity/material model, thresholds and alert-chain proof |
| R7 / S8 U11 sequences | Snyder / Kori | S8 search endpoint implemented on PR #22, awaiting review; U11 display remains | Feasible-order search and intermediate-state/review display |
| R8 / P7 U12 structural strain | Snyder / Bixler / Kori | planned; model/data required | Reviewed structural specification and asset properties |
| R9 / A10 acceptance | Bixler / Kori / Snyder | planned | Local integrated checks plus separate source/qualification evidence |

### Integration status

Rows updated by the reviewed merges supersede the historical rehearsal notes below. Recheck linked PRs before
resuming a packet; a merged feature with unresolved review findings is not accepted.

| Item | Owner | State | PR | Notes |
| --- | --- | --- | --- | --- |
| A0 remote cut-over | Bixler | cut-over done; admin protection confirmation remains | #1–#3, #7 | Default `main`; feature PRs target `dev`. UI-to-main #15 was reverted by #17; #18 is the correct integration. |
| S1 rm0 live frames | Snyder M-SIM; M-PLAN review | merged | #6 | Rich frames, scene, lifecycle/speed/reconnect, bounded workers and recordings; synthetic dynamics |
| S2 simulation-time forcing | Snyder M-SIM | implemented on PR #22 (`ws-e/snyder-demo-sprint`), merged to `dev` via PR #22 (not yet cross-reviewed) | #22 | Immutable `ForcingSpec` (steady/ramp/gusts/replay, synthetic tide, optional apparent wind, `on_uncovered` stop/invalidate) resolved at stage time on batch and interactive paths; `forcing_revision` on frames/sessions. Tests: `test_s2_forcing.py`, `test_p3_s2_s3_benchmarks.py`. NOT done: no live/D2 composed-forecast feed (forcing is supplied or synthetic), no waves in forcing, current never made vessel-relative, no qualified vessel coefficients, no subject-matter review |
| S3 tug/vertical motion | Snyder M-SIM | implemented on PR #22, merged to `dev` via PR #22 (not yet cross-reviewed) | #22 | Push-point binding, capacity clamp and slew via `s3_tug_geometry`, wired into the berthing model and rm0 frames; heave is `prescribed` from the S2 water level only when a series supplies it, else null/`not_simulated`. Tests: `test_s3_geometry_vertical.py`, `test_s3_wiring.py`, `test_p3_s2_s3_benchmarks.py`. NOT done: roll/pitch not simulated (no GM or displacement supplied or invented), tug position/velocity not simulated (null), no sourced tug/push-point data |
| S4 wave surrogate | Snyder M-PLAN | implemented on PR #22, merged to `dev` via PR #22 (not yet cross-reviewed) | #22 | `POST /loads/wave-surrogate`: seeded JONSWAP-shaped scalar elevation series, total XOR partitions (no double count), always `qualified=false`. Tests: `test_s4_wave_surrogate.py`, `test_api_p5_p6_s4.py`. NOT done: visualization only; not wired into berthing/mooring forces, no direction/berth transfer, gamma is a scenario parameter, not fitted to D4 data; offshore availability is not berth forcing |
| S5 storyboarding | Snyder backend; Kori UI | implemented; findings remain | #10 | [Finding disposition](MODELING_BUILDOUT_STATUS.md#pr-10-review-disposition); #14 did not fix S5 paths |
| S6 transit | Snyder M-SIM | implemented; fixes merged, closure incomplete | #10, #14 | Future tug takeover and chart/route evidence remain; some findings have regressions; always limited |
| S7 prediction | Snyder M-SIM; M-PLAN benchmarks | initial transit service merged; full gates open | #14 | Endpoint/presets exist; state approximation, missing berthing/coastline and illustrative uncertainty; [details](PREDICTION.md) |
| P1 resolver | Snyder M-PLAN | merged | #4 | Immutable supplied/scenario resolution, hashes and coverage; public composer in #13 |
| P2 recheck | Snyder M-PLAN | merged | #8 | Explicit revision reassessment; historical results immutable |
| P3 benchmarks | Snyder M-PLAN | initial suite merged (#5); S2/S3 extension implemented on PR #22, merged to `dev` via PR #22 (not yet cross-reviewed); continuous | #5, #22 | Added `test_p3_s2_s3_benchmarks.py` (closed-form forcing, tug force/yaw-moment geometry, tide heave) beside `test_p3_dynamics_benchmarks.py`. NOT done: S7 and R-packet benchmarks beyond P5/P6/S4/S8 unit tests; synthetic numerical-consistency evidence, not physical qualification; the author of P3 also authored the code reviewed, so independent review is pending |
| P5 tug horsepower | Snyder M-PLAN | implemented on PR #22, merged to `dev` via PR #22 (not yet cross-reviewed) | #22 | `POST /tugs/horsepower-plan`: exhaustive minimum-total-hp placement-feasible assignment (<=8 tugs), deterministic tie-break, margins and infeasibility reasons. Tests: `test_p5_tug_horsepower.py` (independent brute force), `test_api_p5_p6_s4.py`. NOT done: catalog bollard pull/hp are seed/synthetic (validity `limited`), horsepower is never converted to force, normal forces only (surge infeasible), no sourced fleet or push-point inputs, no agent/UI consumer |
| P6 ultimate gust | Snyder M-PLAN | implemented on PR #22, merged to `dev` via PR #22 (not yet cross-reviewed) | #22 | `POST /risk/ultimate-gust`: threshold search against a caller-supplied `capacity_basis`; without one returns 200 `unavailable`. Tests: `test_p6_ultimate_gust.py`, `test_api_p5_p6_s4.py`. NOT done: no sourced ultimate-capacity or material-law data in the repository (only `synthetic_test_fixture` bases are exercised), no invented breaking threshold, `validated_rupture_prediction` always false, A9/U10 consumers not built |
| S8 / R7 sequence search | Snyder M-SIM | implemented on PR #22, merged to `dev` via PR #22 (not yet cross-reviewed) | #22 | `POST /mooring/sequence/search`: bounded (<=60 candidates) search over line orders with caller-supplied `must_precede`/`first_line`, intermediate static checks, ranked proposals. Tests: `test_s8_sequence_search.py`. NOT done: handling constraints are caller-supplied, not sourced; static only; durations and rule table unreviewed; always `draft_unreviewed`; U11 display and Bixler planner handoff not built
| U1–U7 planning/motion/forecast UI | Kori | implementation merged; combined acceptance remains | #18 | Review selection, runtime motion, source/forecast panels, clocks, tooling and conditional scene enhancements; public path awaits #13 |
| U8 camera overlay | Kori | initial missions/Transit overlay merged | #14 | Limited S7 results; further live-state/engine/uncertainty behavior follows S7/D8 |
| D1–D4 provider/forecast/replay/waves | Cruz; existing separate PR reviewer | branch implemented; review/merge pending | #13 open | Do not duplicate work or claim merged availability; waves offshore-only, not load-ready |
| D5 refit/telemetry; D6 charts/UKC | Cruz | remaining | | Qualification policy, arbitration and source/datum/coverage evidence |
| D8 own-ship state | Cruz | remaining | | State/age/quality contract; recorded fixtures are not a live vessel-state feed |
| A1 integrated demo | Bixler | baseline merged; combined gate remains | #7, #18 | Reconcile browser/runtime/provider/camera coverage after #13; previous counts historical |
| A2 hosting | Bixler | local preparation exists; actual target pending | #7, #18 | Target HTTP/SSE/WS and HTML/PDF evidence required |
| A3 forecast binding | Bixler | remaining; P1/P2 available | | One manifest through Intake/Planner/Safety/watch; D2 for public revision discovery |
| A7 prediction narration | Bixler | remaining; S7 interface available | | Immutable IDs and code-owned warnings; LLM computes no physics |
| A4 release | Bixler | procedure/draft exist; milestone pending | | No release implied by #15/#17; deliberate `dev` → `main` gate |
| A5 vision | Bixler | guarded implementation merged | #7 | Fixture/fake-LLM and no-LLM paths; real-provider/target rehearsal separate |
| A6 docs | Bixler | fielding brief merged; status reconciled here; ongoing | #9, #12, #16 | Synchronize this board, capability ledger and UI/release notes at merges |

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
| Prediction behavior, limits and demo | [PREDICTION.md](PREDICTION.md), [PORT_TRANSIT.md](PORT_TRANSIT.md), [DEMO_MISSIONS_TRANSIT.md](DEMO_MISSIONS_TRANSIT.md) |
| Motion frames, scene, recordings | [MOTION_FRAME_DESIGN.md](MOTION_FRAME_DESIGN.md), [BERTHING_SIMULATION.md](BERTHING_SIMULATION.md) |
| Forecast planning ≥24 h | [FORECAST_DOCKING.md](FORECAST_DOCKING.md) |
| Data sources and source notes | [DATA_SOURCES.md](DATA_SOURCES.md), `DC2`–`DC7` notes, [DC4 waves](DC4_WAVE_SOURCE_INVESTIGATION.md), [wind basis](WIND_BASIS_REVIEW.md), [current direction](NOAA_CURRENT_DIRECTION_REVIEW.md) |
| Inputs only humans can supply | [DATA_REQUESTS.md](DATA_REQUESTS.md) |
| Release evidence and procedure | [RELEASE_NOTES.md](RELEASE_NOTES.md), [CONTRIBUTING.md](../CONTRIBUTING.md#releasing-dev-into-main) |
| Deployment and security boundary | [DEPLOYMENT_READINESS.md](DEPLOYMENT_READINESS.md) |
| Contract semantics | [CONTRACT_SEMANTICS.md](CONTRACT_SEMANTICS.md), [contract/README.md](../contract/README.md) |
| UI plan and demo script | [frontend/PLAN.md](../frontend/PLAN.md), [frontend/DEMO.md](../frontend/DEMO.md) |
| Overnight history (logs, release review, old instructions) | [archive/2026-11-05-overnight/](archive/2026-11-05-overnight/) |
