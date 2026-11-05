# Berthing simulation: synthetic demonstration only

The batch and interactive APIs use `mooring.berthing.simulator` and shared RK4 mechanics. This is an implemented adapter, pending review, **not vessel-qualified dynamics or a Phase 2 release**. Every result, frame and session acknowledgement includes `VESSEL_DYNAMICS_UNQUALIFIED`. Seed outputs are limited (at least AMBER); invalid output is RED.

## Parameters and physical limits

`synthetic-demonstration-v1` defines an arbitrary numerical body: mass 1,000,000 slug, yaw inertia 10,000,000,000 slug·ft², linear surge/sway damping 100,000 lbf·s/ft and yaw damping 1,000,000,000 ft·lbf·s/rad. Added mass and quadratic damping are zero. These are demonstration inputs, **not estimates derived from displacement, fitted hull coefficients or recommended operating values**. No real vessel coefficient source is available.

Shared tension-only lines, unilateral fenders and M3 environmental loads act on the body. Environment is a fixed snapshot resolved at creation; there is no relative-flow hydrodynamic model, waves, grounding, rupture law or validated snatch model. Batch `gusting` requests fail explicitly. Reaching a line's effective breaking strength stops integration with invalid output; fender stored energy above its catalog rating is RED. This does not implement the full moored WLL/fitting/rule analysis; use that analysis separately, and do not interpret AMBER as acceptable dynamic line handling.

Lines start inactive. `secured` and `tensioned` activate their installed rest lengths from the scenario configuration; `released` deactivates them. Neither operation changes the rest length or simulates a rope-handling transient. The energy diagnostic accounts separately for the instantaneous change in stored line energy. Transitions record activation/release, taut/slack crossings and contact start/end; legacy contact events remain present. `contact` reports the maximum stored energy of an individual fender, with the normal speed at that sampled integration state, **not an impact-energy prediction or initial approach speed**.

Tugs map in catalog order to distinct water-side push points ordered fore to aft. Only normal forces (90° starboard, 270° port) are supported. Capacity is the existing allocation model's bollard-pull and push-point bounds. The demonstration slew is `max(abs(lower_bound), abs(upper_bound)) / 5` lbf/s; reversals ramp from the current force. Five seconds is an explicit demonstration actuator setting, not a measured tug response. Unsupported points/directions or over-capacity commands are rejected.

## Clock and commands

The simulation clock is the integrator's time. Batch and interactive modes use the same fixed integration boundaries, shortened at command times and near contact. Commands sort by simulation timestamp, then arrival order for ties. A past timestamp is rejected. Once the simulation reaches its duration, further force/line commands require a reset. Clients should provide `t_s` for reproducibility; omitted WS timestamps schedule at the next integration boundary for compatibility. A late network arrival cannot be applied retroactively.

Interactive scheduling follows monotonic elapsed time. Each worker chunk performs at most ten work units: one accepted integration segment (including contact subdivisions) or one applied timestamped command counts as a unit. Dense commands cannot hide unlimited work inside one nominal timestep. Yielding retains the original fixed-grid/command boundaries, pending commands, crossing events and diagnostics; it is not an invalid simulation. A recorded boundary frame waits until all commands at that timestamp finish. Commands and display reads also acquire the session lock in workers, so waiting for that session cannot block the ASGI event loop. Cancellation, including repeated cancellation during attach/commands/detach, joins owned work before releasing controller ownership. Commands and frame delivery never advance time. Under CPU overload or very small timesteps the simulation may lag wall time; it reports lag and never skips physics steps. Python workers and sessions still share the process/GIL; this is not a real-time service.

* New session: starts running when its first controller connects.
* `pause`: freeze at the last completed integration boundary. `resume`: re-anchor scheduling there, with no catch-up for the pause.
* `reset`: restore the original scenario/environment/initial state, clear commands and diagnostics, return to time zero **paused**.
* `set_speed`: set simulated seconds per wall second in `(0, 16]`; preserve elapsed demand and fractional steps at the previous speed. Repeating the current speed or `resume` is idempotent. Speed never changes the integration timestep.
* Disconnect: freeze and release the controller. Reconnect: return the saved state **paused**, requiring explicit `resume`.
* Ownership: creating authenticated principal owns the session; only one controller is allowed. Unauthenticated demo mode has no user separation.

One latest-frame slot replaces unread frames; no frame history queues behind a socket. Sending a frame has a two-second timeout (close 1013). Slow transport cannot block integration or another session. Disconnect and reset intentionally change the future control timeline; equivalence applies to the same timed commands and pause history.

## Bounds and errors

| Bound | Default / error |
| --- | --- |
| Global sessions | `MOORING_MAX_SESSIONS=32`; HTTP 429, `Retry-After: 5` |
| Sessions per principal | `MOORING_SESSIONS_PER_PRINCIPAL=4`; same 429 (all demo clients share one principal) |
| Disconnected idle retention | `MOORING_SESSION_IDLE_S=1800`; pruned on the next creation; sessions disappear on process restart |
| Integration step | 0.0001–1 s; smaller steps rejected (422) to bound work and avoid floating-point non-progress |
| Simulation duration | At most 7200 simulated seconds; request validation 422 |
| Incoming commands | 100 per one-second monotonic window; close 1008 with reason |
| Pending commands | 1000; close 1008 (batch job fails with the reason) |
| WS message size/type | 8192 UTF-8 bytes; close 1009 if larger, 1003 for binary, 1008 for invalid schemas/commands |
| Authentication / ownership / controller conflict | Close 4401 / 4404 / 4409 |
| Integration work / transitions | 300,000 steps / 10,000 transitions; stop with invalid output |
| Batch frames | At most 10,000; excessive requested density is 422 |

Session duration bounds simulation time, not the lifetime of an idle connected socket. There is no distributed session registry or controller handoff between processes. Proxy connection/idle caps and deployment-specific limits remain required.

Batch `sample_interval_s` defaults to 1 s, independent of `dt_s`. Dense samples do not alter integration, maxima or transitions. Batch jobs report progress from integrated time and check cooperative cancellation per step. Frames (including validity history), final energy diagnostics and resolved input snapshots persist in SQLite when `MOORING_DB` is configured. Series are exposed only for succeeded jobs; cancelled/failed jobs do not expose series. A cancellation racing final persistence can leave unreachable audit artifacts; cleanup/retention is not automatic.

Interactive `rm0-v1` recordings are sampled at simulation-time boundaries, independently of the latest-only display. Each is bounded by 10,000 frames, 1,000 lifecycle messages and `MOORING_RECORDING_MAX_BYTES` (32 MiB default) of compact frame JSON. Truncation is explicit. Pause/reset persistence is throttled to two wall seconds; disconnect/end/error force persistence. A reset starts a new run, but the recording keeps prior runs and their validity: retained invalid history keeps the whole recording invalid.

Saved recordings and their immutable scenes survive session expiry and, with file-backed `MOORING_DB`, server restart. `GET /berthing/recordings?limit=20&after_session_id=...` returns an owner-scoped page (maximum 100) with scene/recording URLs; IDs sort lexically, not chronologically. `next_cursor`, when present, requests the next page. This index contains saved snapshots, not unsaved live sessions. Existing scene and recording URLs remain valid after expiry; active controllers and physics state are still ephemeral. There is no automatic archive retention policy.

Rich line geometry starts at the named ship bitt, passes through the configured/paired chock when present, and ends at the pier fitting. The model resolves the external lead-to-pier wrench and pier reaction. It does not resolve inner-segment tension/friction or individual redirected bitt/chock reactions; those ship fitting loads are `unavailable` with null values and `ROUTING_REACTION_UNMODELED`. Direct bitt-to-pier reactions remain available. This limitation does not change the integrator's net line wrench.

## Evidence and blockers

`test_s17_simulation.py` covers batch/WS trajectory agreement, sampling independence, pause/reset/disconnect/reconnect, rate/capacity/slew bounds, output backpressure, cancellation, spring contact energy, timestep refinement and agreement with static equilibrium. These are synthetic analytic/consistency checks. `test_s15_s16_dynamics.py` remains unchanged.

Missing: sourced vessel mass/added-mass/damping derivatives, qualified velocity-relative environment coupling, independently sourced contact benchmark, validated dynamic line/rupture behavior, supported vessel/depth/speed envelope and subject-matter acceptance. Passing tests or `backend="real"` does not resolve these blockers.
