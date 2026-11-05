# Master plan: remaining build

**This is the single planning document for the rest of the build.** It replaces the overnight agent instructions, the
overnight logs' "next steps" and "tomorrow" sections, the expanded modeling plan and the release review's deferred list
(all now in [docs/archive/2026-11-05-overnight/](archive/2026-11-05-overnight/)). If a priority or assignment here
conflicts with another document, this one wins. Detailed packet specifications stay where they are (see [Document map](#document-map)).

Written 5 November 2026 against `dev` at `e0e0fcf` (PR #106). The repo now lives at
[fleethacker/pier-review](https://github.com/fleethacker/pier-review); its default branch is `main`, so **always open PRs
with `--base dev`**.

**Requirements audit update, 5 November 2026:** [§11](#11-requirements-audit-remediation-prompts) contains the
implementation prompts for the requirements reviewed at `851ae24`, checked against current `dev` at `91ac18a`.
Only the fielding-brief files changed between those commits; that item is excluded from this follow-up.
The original build snapshot and integration notes below are historical; use §11 for the new gaps, owners,
dependencies and acceptance criteria. This update adds planned work, not completed implementation.

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

**Original build baseline** (1,736 Python tests, 227 UI tests, contract/typecheck/lint/build green, scoped `make demo-check` 24/24):

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

**Original build gaps** (recheck current `dev` before starting an existing packet):

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

Requirements-audit closure has the additional acceptance criteria in [§11](#11-requirements-audit-remediation-prompts).
Track software completion and engineering/source qualification separately; a passing baseline demonstration does not
close an uncovered requirement.

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
| **Bixler** | **A**: agents, integration, release, odd jobs | `agents/`, `scripts/demo_check*.py`, `Makefile`, `app.sh`, `.github/`, `contract/README.md`, `README.md`, this plan, `docs/DEPLOYMENT_READINESS.md`, refdata/qualification (`refdata/`, `qualification.py`, `templates.py`, `routers/{refdata,qualification,system}.py`) |

Shared, single-writer-at-a-time: `modeling/modeling_api/main.py`, `core/schemas/__init__.py`, `common.py`,
`scenarios.py`, `contract/` (generated; see [§8](#8-coordination-rules)).

## 4. Snyder: modeling (Claude session + GPT session)

Snyder runs two coding sessions at once. Split them by **file ownership**, not by task type, so they never edit the same
file, and use each as the other's independent reviewer.

| Session | Lane | Files (exclusive) |
| --- | --- | --- |
| **Claude (M-SIM)** | Simulation runtime: S1 → S2 → S3 | `berthing/`, `sim_sessions.py`, `ws.py`, `routers/berthing.py`, `schemas/motion.py`, `schemas/dynamics.py` |
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

**S3 (P2). Tug geometry and vertical motion.** Packet 5. Tugs bound to permitted push points, capacity and slew; moments from
contact geometry; tug positions only where a kinematic model exists. Tide-following heave first; quasi-static heel only
with supported loading/stability inputs (else "not simulated"). No invented GM or hydrodynamic coefficients.

**S5 (P1). Constraint-based line sequence proposals.** [Prompt R7](#r7-line-sequences-s5u11). Replace the fixed default
ordering with a bounded search over supported handling constraints and intermediate static states. Coordinate the
`berthing/sequence.py` writer with S1–S3 and P2; Kori owns the sequence display (U11).

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
| U2 | P0 | **Live motion on rm0-v1**: consume S1's scene route, rich frames, lifecycle, recordings list/playback, speed control (enable the disabled control), reconnect-from-sequence; draw tugs/lines/fittings/forces/env from live frames | S1 interface (draft PR) |
| U3 | P1 | **Per-component environment availability** (wind/current/tide/forecast/waves): source, state, age, basis; misconfiguration error state | D1 interface |
| U4 | P1 | **Advance-planning panel**: as-of, arrival ≥24 h, holding duration, coverage and provenance preview, alternatives table, apply `selected_config` (keep paid-out lengths and installation tide), "recheck required" on changed inputs | P1/D2 for public data; works now with supplied series |
| U5 | P1 | Simulation-time display (sim time vs wall time, forcing revision) and training-scenario controls (seed, source, persistent "training" label) | S2 |
| U6 | P2 | Upgrade test toolchain to clear the 13 dev-dependency findings (Vitest/Tinypool/Vite); compatibility-tested, no `npm audit fix --force` | none |
| U7 | P2 | Cesium-scene motion view with roll/pitch and water surface when frames supply them; accessibility pass (contrast, screen reader); profile React path at 10 Hz | S3 |
| U8 | P0 | [R1: display and print the layout frozen with the reviewed sheet](#r1-reviewed-sheet-layout-a7u8) | A7 layout contract and immutable fixture |
| U9 | P1 | [R2: two-axis ship placement and fitting-to-fitting line drag](#r2-two-dimensional-canvas-editing-u9); [R3: class capability display](#r3-additional-ship-class-support-a8u9) | Existing pose fields; A8 class capability contract |
| U10 | P0 | [R6: distinct working-load and ultimate-load gust warnings](#r6-ultimate-load-gust-assessment-p6a9u10) | P6/A9 contracts; labeled fixtures until available |
| U11 | P1 | [R7: sequence feasibility, draft/review state and step issues](#r7-line-sequences-s5u11) | Existing sequence fields first; S5 additions after contract publication |
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
| A7 | P0 | [R1: immutable graphical layout in the Safety Sheet](#r1-reviewed-sheet-layout-a7u8); coordinate the sheet/layout contract with U8. |
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

Times are relative to the start of work after the remote move (**T0**). Adjust to the build end.

| When | Milestone | Who |
| --- | --- | --- |
| T0 + 1 h | Default branch/CI confirmed on the new remote, everyone re-cloned (A0). Contract-only PRs opened for S1 (frames/scene/recording routes) and D1 (availability shape) | Bixler, Snyder (Claude), Cruz |
| T0 + 3 h | U1 merged; S1 live frames merged; D1 merged; demo-check extended to the planning chain | Kori, Snyder, Cruz, Bixler |
| T0 + 5 h | U2 live rm0 motion in the UI; D2 series contract + fixtures published; P1 resolver against fixtures. **Release to `main` #1** | Kori, Cruz, Snyder (GPT), Bixler |
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

R1–R9 are cross-workstream tracking labels; the A/P/S/U IDs below retain file ownership. Every packet is **planned**.
The source dependencies in R3, R4, R6 and R8 must remain open until evidence arrives: an importer, an unavailable
result, a synthetic fixture or an honest label alone does not satisfy the corresponding missing capability.

| Packet | Gap to close | Implementation owners | Dependency / order |
| --- | --- | --- | --- |
| R1 | Safety Sheet has no immutable plan-bound graphic | A7 Bixler; U8 Kori | Publish layout snapshot contract, then renderer/UI |
| R2 | Ship drag is along-pier only; line editing is click-based | U9 Kori | Existing pose/line contract; coordinate shared UI files with R1/R3 |
| R3 | CG-47, LHD-1 and CVN-68 lack fitting layouts | A8 Bixler; U9 Kori | Approved class-specific inputs; software support can precede receipt |
| R4 | NSTM references unverified; fitting checks nominal-only | P4 Snyder; Bixler qualification handoff | Source edition and approved directional-rating method |
| R5 | Tug recommendations do not minimize horsepower | P5 Snyder; agent/UI handoff | Define objective and publish additive allocation contract |
| R6 | No defensible gust-to-breaking threshold or warning | P6 Snyder; A9 Bixler; U10 Kori | Supported ultimate-load model/evidence, then warning consumers |
| R7 | Fixed line order; incomplete sequence status display | S5 Snyder; U11 Kori; Bixler planner handoff | Handling constraints; R5 contract for new tug fields |
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

### R1. Reviewed sheet layout (A7/U8)

```text
Goal: Every new supported Safety Sheet includes a reproducible graphic of the reviewed plan with its rationale
and margins, in the UI, printable HTML and PDF.
Read first: agents/mooring_agents/safety/{schemas.py,sheet.py}, planner/agent.py;
frontend/packages/web/src/apps/mooring/{agent.ts,agent.test.ts,panels/Overlay.tsx}.
Scope: A7 owns agents/, persistence and tests; U8 owns frontend consumption. Agree layout metadata and fixtures first.

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

### R7. Line sequences (S5/U11)

```text
Goal: Automatically propose a feasible line-handling order with explicit intermediate-state evidence and review state.
Read first: modeling/mooring/berthing/sequence.py, modeling/tests/test_s13_sequence.py;
agents/mooring_agents/planner/agent.py; frontend/packages/web/src/apps/mooring/{agent.ts,panels/SequencePanel.tsx}.
Scope: S5 owns sequence generation/validation and modeling tests; U11 owns display. Bixler integrates planner output.
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

Planning branch: `docs/a7-requirements-remediation-prompts`, based on `dev` at `91ac18a`. Only this plan is changed;
the prompts have not been executed. States below describe the new implementation work, not the completed audit.

| Item | Owner | State | Blocker / next evidence |
| --- | --- | --- | --- |
| R1 / A7 U8 reviewed layout | Bixler / Kori | planned | Frozen layout contract and rendering/version tests |
| R2 / U9 canvas editing | Kori | planned | Two-axis request updates and pointer-drag browser proof |
| R3 / A8 U9 class coverage | Bixler / Kori | planned; class data required | Approved CG-47/LHD-1/CVN-68 fitting inputs; importer and capability tests |
| R4 / P4 NSTM/directional limits | Snyder / Bixler | planned; source verification required | Edition/rating method and rule-by-rule evidence |
| R5 / P5 fleet horsepower | Snyder | planned | Objective contract and independently enumerated optima |
| R6 / P6 A9 U10 ultimate gusts | Snyder / Bixler / Kori | planned; physical evidence required | Supported capacity/material model, thresholds and alert-chain proof |
| R7 / S5 U11 sequences | Snyder / Kori | planned | Feasible-order search and intermediate-state/review display |
| R8 / P7 U12 structural strain | Snyder / Bixler / Kori | planned; model/data required | Reviewed structural specification and asset properties |
| R9 / A10 acceptance | Bixler / Kori / Snyder | planned | Local integrated checks plus separate source/qualification evidence |

### Original integration snapshot

The rows and validation notes below describe the earlier `282c046`-based Bixler integration work. They are retained
as history, not current completion assertions; recheck merged PRs before resuming those packets.

| Item | Owner | State | PR | Notes |
| --- | --- | --- | --- | --- |
| A0 remote cut-over | Bixler | local cut-over docs complete; protection pending admin | | GitHub checked 5 Nov: default `main`, `dev`/`main` unprotected; explicit `--base dev`; CI triggers both branches |
| S1 rm0 live frames | Snyder (Claude) | remote branches published; not integrated here | | `ws-e/s1-frames`, `ws-e/s1-protocol`, `ws-e/s1-rm0-live-frames`; baseline still emits legacy frames |
| P1 forecast resolver | Snyder (GPT) | interface published; implementation/merge pending | | `ws-b/p1-forecast-resolver` at `828d5ec`; resolve route is a 501 preview |
| U1 Intake/review selection | Kori | not started | | |
| U2 live rm0 motion | Kori | blocked on S1 interface | | build on fixtures meanwhile |
| D1 source selection | Cruz | not started | | |
| D2 composed forecast | Cruz | not started | | |
| A1 demo-check | Bixler | expanded baseline implemented locally; full gate pending | | Four API chains, synthetic advance planning, legacy WS; CI job added; readiness profile fails uncovered S1/D1/A3/browser gates |
| A2 hosting | Bixler | local launcher/browser rehearsal passed; target deferred | | Node >=22.17, startup health, installer/service cleanup, HTML fallback; Bixler requested local tests instead of Domino |
| A3 forecast binding | Bixler | blocked on implemented P1/D2 | | Published binding/manifest contract exists; resolver still 501, no latest-revision lookup for supplied series; saved-source Safety watch remains |
| A4 release | Bixler | draft notes/procedure prepared; unreleased | | [Release draft](RELEASE_NOTES.md); milestone dependencies, review, CI and clean-main target gate remain |
| A5 vision | Bixler | implemented locally | | Fixture-image/fake-LLM HTTP flow; empty/duplicate/oversized proposal fallback; no-LLM catalog labels preserved |
| A6 docs | Bixler | integration truthfulness pass | | README, contribution/release/hosting docs and UI/modeling status distinguish baseline evidence from full acceptance |

This Bixler work is on `agents/a0-bixler-integration`, based on `origin/dev` at `282c046`. Changes are local and
unreleased. The new CI job retains logs and failure ownership in its run summary; no team messages were sent.
Cross-workstream edits are limited to the A6 status notes in the modeling ledger and UI plan/demo documents.

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
