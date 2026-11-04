# Team agent instructions 02: realtime ship-motion simulation and visualization

Audience: any agent or engineer assigned a simulation or visualization work item. Written 4 November 2026 against `dev` at `ddcf97d`.

**Goal.** In the UI, a user watches a ship move in near-real time, in a 2D map of the ship and dock and optionally a 3D view, driven by **all** of: wind (with gusts), current, swell/waves, tug push (with tug position, velocity and acceleration), mooring lines and the bollards/fittings they attach to, fenders, and tide. The motion must come from a physics model whose limits are shown, not a canned animation.

This file adds work items. It does **not** replace [docs/MODELING_EXECUTION_PLAN.md](../docs/MODELING_EXECUTION_PLAN.md), the implementation authority. The baseline motion packets already live there:

| Packet | What it gives | Status at writing |
| --- | --- | --- |
| S05 | Line, fitting and fender mechanics | pending |
| S06 | M4 three-DOF equilibrium | pending |
| S08 | Tug allocation (force/wrench level) | pending |
| S15 | M11 three-DOF dynamics (surge, sway, yaw) | pending |
| S16 | Contact, line activation, batch simulation | pending |
| S17 | Interactive session and WebSocket, Phase 2 gate | pending (check for an existing `ws-e` branch or worktree) |

Do not redo or fork those. Items below (RM0–RM8) are **NEW** scope that sits on top of them or extends them. Their own acceptance text applies and, where an item changes a packet's scope, the packet owner is coordinated with, not overridden. Environmental data sources (including waves) are in [01-data-connections.md](01-data-connections.md).

## What exists today (so nobody assumes more)

- `modeling/mooring/berthing/mock/simulator.py`: a mock with **one** degree of freedom (sway toward the pier), environment force computed once and held constant, lines not modeled (`lines=[]`), fender energy with invented factors.
- `modeling_api/ws.py` `/ws/sim/{session_id}`: 10 Hz loop; accepts `tug_command`, `line_event`, `pause`, `resume`, `reset`; emits `SimFrame` (pose, tugs, lines, fenders, alerts). `ws.py` ties simulation time to the message loop, which the plan's S17 forbids.
- `SimFrame` has 2D pose only, force-and-direction tugs with no position or kinematics, no waves, no vertical motion, no environment at time `t`, no validity.
- Real: UFC wind and current loads (M3), line geometry, a subset of NSTM rules. Everything else is mock.
- Frontend: only a README. There is no 2D map or 3D view code yet.

## Before you start (every item)

Same rules as file 01: read the docs listed there plus `docs/PLAN.md` sections M3, M4, M6, M11; other agents are working in this repo, so touch only your scope, never push to `dev` or `main`, branch from latest `origin/dev`, open a PR, do not merge it; claim your item by checking `gh pr list --state all` and remote branches for its ID (`rm3`, etc.) and the related packet number; do not start until dependencies have merged.

## Rules specific to motion simulation

- **Physics is the authority; the UI only draws it.** The simulation clock is owned by the simulator. Network message rate, frame rate and client speed never advance physics time (S17). Same timed commands give the same trajectory in batch and interactive modes.
- **Qualified versus synthetic must be visible.** Anything driven by unvalidated coefficients, estimated areas, surrogate wave response or mock data is labeled in the frame (`validity`, `provenance`) and shown by the UI as such. Do not present plausible motion as validated. Do not invent hydrodynamic coefficients, response operators or tug performance to make a demo look right. If a primary source or input is missing, record it (file 01, DC8 data request list), leave the capability unqualified, and offer a clearly labeled synthetic surrogate for visualization only.
- **Frames and conventions unchanged:** wind-from, current-toward, true bearings, ship +x forward / +y port / +z up, positive yaw counterclockwise, berth +y off-pier, MLLW datum. Transform explicitly; name unit conversions.
- **Contract first, additive only.** New frame and schema fields are optional and additive, defined in schemas and regenerated into `contract/` with `make contract`. Legacy `SimFrame` consumers keep working; absence of validity means unknown, not valid.
- **Determinism and tests.** Injected clock, seeded randomness, fixed fixtures, no network. Each physics piece needs an independent analytical or sourced benchmark, plus timestep-convergence evidence. Agreement between two of our own modules is secondary.
- **Budgets.** Real-time means the server can compute faster than the display rate on documented hardware. Measure p50/p95 step time, state the supported step size and number of concurrent sessions, and decide in the PR how the stream degrades when it cannot keep up (drop display frames, never slow or skip physics silently).
- Run `make contract` and `make test`. Report counts, skips, benchmark artifacts.

## Work items

### RM0 — Frame and contract design for motion and visualization (do first; no physics)

Depends on S00 merged. Write the additive schema changes and a short design note (`docs/MOTION_FRAME_DESIGN.md`) that every other RM item and both UI items follow. Cover at least:

- `SimFrame` additions: sim time and a monotonically increasing frame/sequence number; six-component ship pose and velocity (surge, sway, heave, roll, pitch, yaw) with heave/roll/pitch optional and flagged when not simulated; accelerations where available.
- Tugs: position in berth frame, heading, velocity vector, acceleration vector, commanded versus actual force vector, push point, mode (push/pull/standby), contact state, capacity utilization.
- Environment at time `t`: wind speed/gust/direction, current speed/set, water level, wave height/period/direction (optional), each with source and validity.
- Lines: tension, status (slack/taut/overloaded), world-frame endpoints and catenary-free polyline for drawing, attached ship fitting and pier fitting IDs. Fittings and bollards: load, capacity, percent. Fenders: compression, reaction.
- Force breakdown per frame (wind, current, wave, tug, lines, fenders) as vectors and yaw moments, so the UI can draw force arrows.
- Frame-level `validity` and `provenance` (mock, estimated, qualified), plus alerts with severity.
- Static scene payload fetched once per session (berth outline and fittings, ship hull outline and fittings, fender positions, depth profile), so frames stay small.
- Session lifecycle messages (created, running, paused, reset, ended, error) and a sampling/decimation rule for slow clients.

Acceptance: contract regenerates deterministically, legacy examples still validate, example frames and a sample 60-second recording are published under `contract/examples/modeling/` for the UI team to build against while physics is mock. Coordinate with the S17 owner (check for an active `ws-e` branch) rather than diverging.

### RM1 — Time-varying environment inside the simulation

Depends on RM0 and the S15 integrator. Replace the held-constant environment force with forcing evaluated every step from an environment *source*: steady, ramp, gust time series (with correlation, seeded), replay of a recorded window, or forecast-driven (from DC1–DC3 when merged). Wind and current loads come from M3 evaluated at the **instantaneous** relative velocity and heading (ship motion changes relative wind/current), with no double-counting of drag. Water level changes feed draft/depth and line geometry. Declare units, wind-basis handling (one conversion boundary) and gust-duration assumptions.

Acceptance: constant-environment case reproduces S15 results; step and ramp responses against analytical expectations; seeded gust series reproducible; relative-velocity handling tested with a moving ship in still air.

### RM2 — Swell and wave environment and wave forcing (NEW scope)

Schema design and isolated synthetic tests depend on merged RM0 and may precede source approval. Real ingestion requires the human's DC4 approval for each selected component/source and the DC4 Stage 2 dependencies. Integration into the motion simulator additionally depends on merged RM1 (including its zero-wave baseline). Coordinate the RM2 schema before DC4 adapter implementation so these stages do not form a circular dependency. Two layers, kept separate:

1. **Schema and ingestion shape:** additive wave fields on the environment snapshot (significant height, peak or mean period, direction-from, optional spectrum) with metadata, validity and datum/height basis; coordinate with DC4 so there is one schema. Represent DC4 components with their own source, validity, availability, observation/model location, issue/valid times and transfer-to-berth provenance. Preserve unpartitioned total sea-state data explicitly rather than labeling it swell or forcing an unsupported decomposition. Wind sea/swell entries may carry bulk statistics or spectra; wake entries need event/arrival time, duration and a sourced waveform or response representation when available. Do not require stationary height/period statistics for every wake. Missing/unavailable is distinct from an explicitly measured or prescribed zero. Define spectrum frequency/angular units, direction-from in degrees true, and normalization; record any partitioning and source overlap so the solver can select a non-overlapping forcing representation. New inactive fields use `wire_omitted_defaults` to preserve legacy payloads and hashes.
2. **Wave-induced motion and forces:** first-order wave-frequency motion and slow-drift/mean drift forces need ship-specific response data (response amplitude operators, drift coefficients) that the repo does not have. Source them from published data or human-supplied data (DC8 request list) and cite edition, table and domain. Where unavailable, provide a **clearly labeled synthetic surrogate** (for example regular or irregular waves with an assumed simple response) for visualization, marked unqualified. Define how berth sheltering and wave transformation into the pier are handled; state the assumption and never imply it is validated. Do not apply the total spectrum and its partitions together, or overlay local chop/wake already represented in the selected measurement/model. A stationary wind-wave response model is not automatically valid for transient wake; absent suitable wake response data, keep that capability unavailable/unqualified. Surface wake does not authorize propeller-wash or tug-interaction forces excluded by RM3.

Acceptance: deterministic seeded wave realization; known-spectrum statistics and normalization checks; total-versus-partition selection prevents duplicate forcing; unavailable/stale components never become zero or qualified; forecast-as-of replay excludes future-issued inputs; wake arrival, finite duration and missing-event coverage are tested separately from stationary spectra. Explicitly prescribed zero-wave input reproduces RM1 exactly; unknown wave exposure must not pass as that zero-wave case. Unqualified/unavailable status propagates to frames and the UI badge; the PR lists missing data and which capability stays unqualified. Synthetic visualization may continue with unavailable exposure only when that limitation remains explicit, not as a claimed all-forces prediction.

### RM3 — Tug kinematics and push model (NEW scope)

Depends on RM0 and S08; extends S15/S16. Move from "force plus direction relative to the bow" to tugs as bodies: position, velocity and acceleration vectors in the berth frame; first-order thrust lag and slew limits (plan M11); allowed force direction and capacity per propulsion type (using certified bollard pull where known, labeled estimates otherwise); push points on the hull and contact/no-contact; line-made-up (pull) mode; tug-to-ship force and moment applied at the actual contact point. Decide in the PR how tug motion is produced (scripted waypoints, simple speed-and-heading controller, or user command via the session) and keep it deterministic. Any tug wash or interaction effects are out of scope unless the human adds them; say so.

Acceptance: single tug pushing at a known point produces the analytically expected force and yaw moment; lag and slew step responses; capacity limits enforced; direction constraints; tug position integrates to commanded velocity; tug contact transitions are event-resolved; frames expose kinematic vectors per RM0.

### RM4 — Vertical motions (heave, roll, pitch) for the 3D view (NEW scope)

Depends on RM0 and RM2 decisions. Decide with the human whether the 3D view needs (a) tide-following heave only, (b) quasi-static heel from wind and wave and line loads, or (c) dynamic roll/pitch/heave. Implement only what is chosen and flag the rest as "not simulated" in frames. Dynamic vertical response needs hydrostatics and response data not in the repo; do not invent them. Water level (tide, MLLW) must visibly move the ship against the fixed pier deck height and shift line geometry consistently (loading-dependent fitting heights).

Acceptance: tide cycle moves the ship by the right amount relative to the pier; heel under steady beam wind matches a hand-calculated metacentric estimate if (b) is chosen; vertical line angles in frames match geometry.

### RM5 — Real-time session service and stream

Depends on RM0 and S15–S16; this extends S17 rather than duplicating it, so coordinate with that owner. Deliver the authoritative simulation clock, session lifecycle (create, pause, resume, reset, speed control such as 1x to N x), ordered timestamped commands, per-session isolation and limits, backpressure and slow-client handling, reconnect and resume from sequence number, and a WebSocket/SSE stream carrying RM0 frames plus the static scene fetch. Also support server-side recording and playback of a session for demos and for the replay-driven UI.

Acceptance (S17 plus): identical trajectory for batch, interactive and playback of the same timed commands; message floods, slow clients, disconnects and reconnects cannot change physics time or another session; benchmark of step time versus display rate, and number of concurrent sessions, on documented hardware.

### RM6 — UI: 2D map of ship and dock

Depends on RM0 (build against the published example frames and mock first). The UI team owns framework choice (`frontend/README.md`). Show: pier face and berth outline, fittings and bollards with load/capacity color, fenders with compression, ship hull outline with pose and heading, mooring lines colored by status and tension, tugs with position, velocity and acceleration vectors and push force arrows, environment glyphs (wind and current arrows, wave direction and height), force breakdown arrows, time controls (play, pause, speed, scrub through a recording), alerts, and the mandatory badges for mock/estimated/unqualified data and frame validity. Generate TypeScript types from `contract/`; add contract consumer tests against the example frames.

### RM7 — UI: 3D view of ship and dock (optional per the human)

Depends on RM0, RM4 and RM6. Same data as the 2D map in a 3D scene (hull, pier deck and fittings at correct heights, water surface following tide and optional waves, lines in 3D, tugs), camera presets, and the same badges. Hull geometry is a simplified or parametric model from `ShipClass` dimensions unless the human provides real models. Only draw motion components the frame marks as simulated.

### RM8 — End-to-end demonstration and validation

Depends on the items above that the human selected. Run a scripted scenario from berthing through all lines fast under changing wind, current, swell and tide, with tug commands: record frames, replay in the 2D and 3D views, and write `docs/MOTION_DEMO_EVIDENCE.md` with the scenario, parameters, benchmark results, a table of every validated versus synthetic component, performance numbers, and known limits. This extends the S17 Phase 2 gate: independent dynamics and contact benchmarks, timestep convergence, and subject-matter review of contact and line assumptions are still required before any claim beyond "demonstration within documented assumptions".

## Suggested order

RM0 first, then in parallel: RM1, RM3, RM6 (against mock frames), and DC4 stage 1. Then RM2 and RM4 after decisions, RM5 alongside the S15–S17 owner, RM7 after RM4, and RM8 last. The S05, S06, S08, S15 and S16 packets are on the critical path for real physics; the UI items can progress against published example frames in the meantime.

## Open decisions for the human (agents must ask, not guess)

- Wave source and how much swell physics: surrogate for visualization only, or qualified (needs data in DC8).
- Whether the 3D view is required, and which vertical motions it needs (RM4 a, b or c).
- How tugs move: scripted, controller-driven or user-driven; whether tug wash or interaction is in scope.
- Real ship hulls, response data and fender curves: can any be supplied?
- Whether "demonstration within documented assumptions" is the target, or qualified results for a specific ship, pier and condition range.
