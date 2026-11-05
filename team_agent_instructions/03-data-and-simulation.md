# Agent 3: data connections and simulation

Read [README.md](README.md) (shared rules, do-not-stop, degradation ladder, acceptance gate) first. Worktree: `../psp-ws-e`,
branch `ws-e/overnight`. Log: `docs/overnight/data-sim.md`.

**You own**, in `modeling/`: `mooring/environment/`, `mooring/telemetry/`, `mooring/approach/`, `mooring/berthing/`,
`modeling_api/ws.py`, `modeling_api/sim_sessions.py`, the env/telemetry/approach/berthing routers, and `scripts/` for data
(fetch, fit, smoke). **Agent B owns** loads, mechanics, moored, tugs, rules, refdata, agents; ask through
`docs/overnight/modeling-agents.md` `## Requests`. The UI agent consumes your frames; your top priority is to unblock them.

## What exists

- Environment: deterministic replay; CO-OPS adapter (stations wind 8638614, water level 8638610, currents cb0402 bin 4) with
  recorded real fixtures, retries, rate limit, TTL cache, stale policy; `MOORING_ENV_SOURCE=coops` serves `/env/now`,
  `/env/history`, `/ws/env`. Default `mock`. `/env/forecast` is 503 in `coops` mode. Live cb0402 current often lags hours, so
  `/env/now` is often 503. A fitted but **unqualified** uncertainty artifact (`coops-8638614-2025`). DC4 investigation done
  and the human approved the source order: NDBC 44099 observations, GFS-Wave forecast (`docs/DC4_WAVE_SOURCE_INVESTIGATION.md`).
- Simulation: synthetic 3-DOF integrator, contact and line activation, interactive sessions (`/ws/sim/{id}`) with an
  authoritative clock, timed commands, pause/reset/reconnect; RM0 additive frame/scene/lifecycle/recording schemas and fixtures
  (`docs/MOTION_FRAME_DESIGN.md`) **that the live simulator does not yet populate** (it emits legacy frames).
- Telemetry: NMEA MWV/HDT decode, sensor registry, bounded storage, arbitration policy (not wired to env endpoints).
- Approach (M12): mock, labeled. No real chart data.
- Berths: built on real piers from OSM/satellite (`scripts/build_berths.py`).

## Work, in priority order

### S-A. Publish live RM0 frames and the scene (FIRST, within about 2 hours; the UI is waiting)
1. Make the live simulator **emit `rm0-v1` frames** (identity fields, sequence, six-component pose with heave/roll/pitch flagged
   not-simulated, kinematic tug fields, line endpoints/polylines, fitting loads, force breakdown, environment at time `t` with
   source and validity, frame `validity`/`provenance`), as an opt-in the UI can request or by default if legacy consumers
   still work. Legacy fields unchanged.
2. Serve the **static scene** (berth outline, fittings, hull outline, fender positions, depth) and lifecycle messages
   (created, running, paused, reset, ended, error) per `docs/MOTION_FRAME_DESIGN.md`; recording and playback of a session
   (server-side record; replay stream with the same frame schema; scrub by sequence). Resume from sequence number on reconnect.
3. Write exactly how to use it in `## Interfaces` (session create call, WS URL, message types, fixtures), then tell the UI via its
   `## Requests` and merge to `dev`. Physics quality can be low at this point; the plumbing is the deliverable.

### S-B. Simulation fidelity (RM1 to RM5), in this order
- **RM1 time-varying environment inside the sim:** forcing evaluated each step from an environment source: steady, ramp,
  seeded correlated gust series, replay of a recorded window, forecast-driven. M3 loads at the **instantaneous relative**
  wind and current (ship motion counts), no double-counted drag; water level moves draft/depth and line geometry.
  Constant case reproduces the S15 result. This is the largest visible improvement; do it before waves.
- **RM3 tug kinematics:** tugs as bodies (position, velocity, acceleration in berth frame), thrust lag and slew limits, capacity
  and direction constraints per propulsion type (catalog estimates labeled), push points, contact events, pull mode, scripted or
  commanded motion, deterministic. Force and yaw moment applied at the actual contact point.
- **RM4 vertical motion:** tide-following heave and quasi-static heel (decision: options a and b); water level visibly moves the
  ship against the fixed deck and changes line geometry; dynamic roll/pitch flagged "not simulated".
- **RM2 waves:** additive wave fields with metadata (total vs. partition vs. spectrum preserved; unavailable is not zero; no
  double counting of total and partitions). First-order response is a **labeled synthetic surrogate** (simple response of the
  hull to regular/irregular seeded waves), unqualified, flagged in frames. Wake `unavailable`. An explicit zero-wave input must
  reproduce RM1 exactly.
- **RM5 session service:** authoritative clock owned by the simulator (message rate never advances physics time), speed control
  1x to Nx, ordered timestamped commands, per-session isolation and limits, latest-frame backpressure (drop display frames, never
  skip or slow physics silently), recording and playback identical to batch and interactive for the same commands. Measure p50/p95
  step time and sessions supported and write it down.
- Tests per piece: analytical benchmarks (single tug at a known point gives the expected force and moment; tide cycle moves the
  ship the right amount; relative-velocity case in still air; known-spectrum statistics; timestep convergence). Update
  `docs/BERTHING_SIMULATION.md`. All determinism: injected clock, seeded randomness.

### S-C. Data connections
1. **Resilient environment (gate item 4):** fix the stale-current problem without inventing data. Return partial snapshots with
   per-component availability instead of one 503; add `MOORING_ENV_SOURCE=auto`: live CO-OPS when reachable and fresh, otherwise
   a **recorded real window served as `replay`, labeled**, with the active source and age in `/health`, `/version` and each
   snapshot. Make the app's default (`app.sh`, `make mock`) `auto`, falling back to `replay`, then to the existing synthetic
   mock only as the last rung and labeled `mock`. The network is not guaranteed overnight: tests use fixtures. Publish the
   switch and status shape for the UI.
2. **DC2 NWS wind forecast (S04c):** gridpoint forecast for the berth, issue vs. valid time, averaging basis documented, never
   use data issued after replay time; recorded fixtures; serve `/env/forecast` from it. If NWS is unreachable or its averaging
   basis cannot be established, serve CO-OPS **predictions** (tide, current) as forecast and leave wind forecast `unavailable`.
3. **DC3 CBOFS forecast:** timebox 60 minutes (netCDF, large files, `xarray`/`netCDF4`). Fallback is CO-OPS predictions at
   cb0402 and Sewells Point, labeled `prediction`. Compare against predictions in a recorded test to catch datum or direction errors.
4. **DC4 stage 2 (approved):** NDBC 44099 observation ingestion (total sea state vs. provider swell/wind-sea partition preserved;
   confirm field definitions, direction convention and cadence from the recorded fixture, do not assume), GFS-Wave forecast if
   its archive/endpoint is reachable (else observation only, forecast `unavailable`), local chop from fetch-limited relation
   per the investigation note only if geometry is available (else `unavailable`), wake `unavailable`. Fill the RM2 fields; never
   synthesize a fallback silently; forecast-as-of replay without later-issued data.
5. **DC5 refit:** extend the uncertainty fit to 2024 plus 2025 (365+ days) with a time/event split; keep the artifact
   **unqualified** unless the policy is truly met (no storms, no forecast error means it is not). `GET /env/gust-model` serves
   it with provenance. Tell agent B the new artifact id.
6. **DC6 charts and geometry, then S18/S19 approach (Phase 3, last):** NOAA ENC via GDAL/Fiona if installable in `uv` without
   heroics; otherwise NOAA chart REST services, or the already-built OSM berth geometry for pier outlines plus depth profile
   at the berth. Real route and UKC with a sourced squat formulation only if chart data and sources are in hand; otherwise leave
   approach as the labeled mock and say so. Never let this block anything above.
7. **DC7:** wire telemetry arbitration into env only as an opt-in, never overriding a qualified forecast or verified scenario.
   Lowest priority.
8. `docs/DATA_SOURCES.md`: each source, station/endpoint, what it provides, averaging/datum/units, cadence, terms, gaps.
   Recorded fixtures only, small, legally shareable.

### S-D. Demonstration and evidence (RM8)
A scripted scenario: berthing through all-lines-fast under changing wind, current, tide and (synthetic-surrogate) swell, with tug
commands; saved as a recording that the UI can replay (`contract/examples/` or a recordings dir the UI can fetch); and
`docs/MOTION_DEMO_EVIDENCE.md`: scenario, parameters, benchmark results, table of every validated vs. synthetic component,
performance numbers, known limits. Be exact: "demonstration within documented assumptions"; no claim of qualification.

### S-E. Hardening (then keep going)
Flood/slow-client/disconnect tests cannot change physics time or other sessions; session limits; replay byte-identical across
runs; error paths; `/health` truth; scripts reproducible offline; README status table and the milestone ledger in
`docs/MODELING_BUILDOUT_STATUS.md` for S04c/S15-S20 kept truthful.

## Interfaces you depend on / publish

- Depend on agent B: loads/tug/line APIs (stable); `refdata` changes. Do not wait for anything.
- Publish (first within 45 minutes, kept current): sim session API, frame and scene shapes with fixtures, recording API,
  env-source modes and status shape, forecast and wave availability, new env variables, performance numbers.
- UI first: whatever the UI needs to light up the motion view is more valuable than fidelity.

## Done means

Gate items 3 and 4 pass on `dev` (verify with `make demo-check` and a manual WS session), all new physics has analytical tests
and the others' tests still pass, no provider data is faked, the sim's synthetic components are flagged in every frame, scripts
and fixtures are committed, final report written with measured performance and what is synthetic.
