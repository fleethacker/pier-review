# Master plan: remaining build

**This is the single planning document for the rest of the build.** It replaces the overnight agent instructions, the
overnight logs' "next steps" and "tomorrow" sections, the expanded modeling plan and the release review's deferred list
(all now in [docs/archive/2026-11-05-overnight/](archive/2026-11-05-overnight/)). If a priority or assignment here
conflicts with another document, this one wins. Detailed packet specifications stay where they are (see [Document map](#document-map)).

Written 5 November 2026 against `dev` at `e0e0fcf` (PR #106). The repo now lives at
[fleethacker/pier-review](https://github.com/fleethacker/pier-review); its default branch is `main`, so **always open PRs
with `--base dev`**.

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

**Works on `dev` today** (1,736 Python tests, 227 UI tests, contract/typecheck/lint/build green, scoped `make demo-check` 24/24):

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
7. `make demo-check` covers 3–5 end to end and passes; `frontend/DEMO.md` has the final 5-minute script; README and status
   docs are truthful.

**Cut order if time runs short** (cut from the bottom): approach/ENC (D6) → telemetry (D5b) → uncertainty refit (D5a) →
waves (D4, S4) → tug kinematics and heel (S3) → composed public forecast (D2: fall back to recorded/synthetic series,
labeled) → sim-time forcing (S2). Never cut: items 1–3, rm0 live frames (S1), source-selection honesty (D1), item 7.

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
| **Claude (M-SIM)** | Simulation runtime: S1 → S2 → **S5 + S6** → S3 | `berthing/`, `sim_sessions.py`, `ws.py`, `routers/berthing.py`, `schemas/motion.py`, `schemas/dynamics.py`; new `missions/`, `transit/`, `routers/{missions,transit}.py`, `schemas/{missions,transit}.py` |
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
| T0 + 6 h | S5 storyboarding and S6 port transit merged (added 5 Nov; executed in parallel with sub-agents) | Snyder (Claude) |
| T0 + 8 h | S2 sim-time forcing; D2 composed forecast; U3/U4; A3 agents on forecast revision. **Release to `main` #2** | all |
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
| A0 remote cut-over | Bixler | history imported; default branch and CI to confirm | | |
| S1 rm0 live frames | Snyder (Claude) | in review | #6 | |
| S5 mission storyboarding | Snyder (Claude) | in review | #10 | demo script: [DEMO_MISSIONS_TRANSIT.md](DEMO_MISSIONS_TRANSIT.md) |
| S6 port transit simulation | Snyder (Claude) | in review | #10 | same PR as S5; always limited validity |
| P1 forecast resolver | Snyder (GPT) | in review | #4 | |
| P3 | Snyder (GPT) | in review | #5 | |
| U1 Intake/review selection | Kori | not started | | |
| U2 live rm0 motion | Kori | blocked on S1 interface | | build on fixtures meanwhile |
| D1 source selection | Cruz | not started | | |
| D2 composed forecast | Cruz | not started | | |
| A1 demo-check | Bixler | in review | #7 | PR #7 also covers A2 and A5 |
| A2 demo-check motion/data checks | Bixler | in review | #7 | |
| A5 docs truthfulness pass | Bixler | in review | #7 | |

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
