# Modeling build-out: status, evidence and blockers

> Priorities and owners for remaining work: [MASTER_PLAN.md](MASTER_PLAN.md). This file is the capability ledger.

**Reconciled 5 November 2026 against `dev` at `3ababad` (PR #18).** Snyder maintains modeling evidence;
Cruz supplies source/telemetry/chart evidence, Kori supplies browser evidence, and Bixler maintains the integrated
status and release gate. [Execution ownership](MASTER_PLAN.md#execution-ownership) names leads, collaborators,
reviewers and dependencies. This documentation pass ran no tests or CI; previous counts remain tied to their PRs.

P1's canonical resolver is implemented and merged in #4; it is not a 501 stub. P2 rechecks (#8), initial P3 analytic
benchmarks (#5), S1 rich runtime/recordings (#6), S7/U8's initial transit-based camera (#14), and U1–U7 UI (#18) are
merged. #14 addresses several S6 defects but not the full #10 review; see the disposition below. D1–D4 composition,
source selection, replay and waves remain in open #13 under separate review; A3 agent-wide revision binding remains
work to do on that reconciled revision. The subsequent Bixler implementation branch now provides supplied/scenario
agent binding, saved sheet diagrams, prediction narration and ship-input capability gates; see the
[branch implementation/evidence record](BIXLER_IMPLEMENTATION.md). Public revision discovery and combined release or
physical qualification are not established by those additions.

Earlier rehearsal evidence (1,769 Python / 227 UI tests and 27 local API/browser checks, with six uncovered readiness
requirements) belongs to #7's integration branch; see [LOCAL_REHEARSAL.md](LOCAL_REHEARSAL.md). The 1,734/191 morning
counts belong to the [overnight report](archive/2026-11-05-overnight/modeling-agents.md#final-report). Neither is the
current post-#18 suite count. Use exact PR/CI evidence for newer changes.

## Packet ledger

S01–S21 below are legacy modeling packets, not the master plan's S1–S8 task IDs. The master plan determines
current ownership/order; this ledger records implementation and remaining technical/qualification gates.

| Packet | State on reconciled `dev` | What exists | What is not done / blocked |
| --- | --- | --- | --- |
| S01 data qualification | implemented | `qualification.py`, `GET /qualification`, `GET /capabilities`, rule coverage audit, defensive catalog copies, synthetic fixture | No published data on file, so every real asset is `demonstration`. NSTM paragraph references still unverified (`source_verified=false`). Runtime berth IDs are immutable: identical retries are accepted, changed revisions require new IDs. Confirmed runtime additions persist with MOORING_DB and survive backup/restore; default storage is ephemeral. Catalog administration/retirement policy remains missing. A published tug label does not establish rating verification; unverified ratings remain demonstration/limited. |
| S02 results and jobs | implemented, single host | SQLite write-once results, resolved-input snapshots, persistent scenarios, bounded worker pool, queue limit (429), deadlines, cancellation, restart recovery, SSE resume | Threads share the GIL; cancellation is cooperative. Not distributed. Agents now use bounded background tasks with cancellation; opt-in durable documents/jobs, service-scoped recovery and completed event replay. Authenticated ownership survives restart. Interrupted work is failed, not resumed; active events are not journaled. One process per service/database. |
| S03 M3 validity | implemented | one wind-basis boundary with actual applied factor, explicit environmental quality/interval gates, depth-at-draft invalid, finding aggregation, `compute_loads` p50 about 5 us | UFC conversions beyond 60 s -> 30 s and 10 m are not implemented (reported limited, not converted). |
| S04 environment | S04a and S04b implemented, opt-in | deterministic replay; CO-OPS adapter (wind, water level, currents, tide and current predictions parsed) verified against the live API and recorded fixtures; retries, rate limit, TTL cache, stale policy, 503/502/422 mapping; `MOORING_ENV_SOURCE=coops` wires `/env/now`, `/env/history` and `/ws/env`; opt-in `scripts/smoke_coops.py` | Default stays `mock` (offline). **S04c composition incomplete:** NWS wind adapter is integrated with interval/unit/cache tests, but `/env/forecast` still returns 503 in coops mode until wind/current/water-level components can be composed honestly. CBOFS regular-grid sampling is integrated with units, domain, time and missing-layer guards; live surface sampling succeeds but the demo-pier 4m/6m layers are missing. Complete composition, available depth coverage and pier applicability remain blockers. Current flow-toward convention is supported by NOAA definitions; see [source check](NOAA_CURRENT_DIRECTION_REVIEW.md). Instrument heading and pier/bin applicability are not independently qualified. Live currents at cb0402 lag by hours, so `/env/now` is often 503 (stale); no prediction fallback was added. |
| S05 mechanics | implemented | pose, tension-only lines, pretension/slack/paid-out initialization, fenders with energy | Multi-part reeving and chock friction rejected or flagged, not modeled. |
| S06 equilibrium | implemented | joint 3-DOF solve, independent residual/rank/stability checks, tolerances, tug vectors, resolved line spans and solved-pose line geometry for reports/rules | No heave/roll; fender vertical extent ignored; solver is local (a failed solve is never proof of infeasibility). |
| S07 limits and tide | implemented | bracketed limit search with distinct outcomes and null limits for invalid inputs; supplied-forecast or explicitly synthetic tide sweep with explicit tending only | Wind speed scaling holds the request's gust ratio; no probabilistic limit. |
| S08 tug allocation | implemented | wrench allocation, static berthing plan | Ratings are catalog estimates; normal forces only. |
| S09 holding and windows | implemented | verified holding plans, forecast windows with gaps and refinement | Forecast is the deterministic mock. Candidate patterns are water-side points at a uniform rating fraction; first passing candidate, not a minimum-force optimum. Empty requested fleets remain empty; duplicate tug IDs reject. |
| S10 uncertainty | tools, fit script and one fitted artifact | fitting, train-only event split, qualification policy, seeded global sampler; exploratory sector fits with explicit unqualified status; `scripts/fit_uncertainty.py`; artifact `coops-8638614-2025` (2025 CO-OPS wind 8638614 and current cb0402 bin 4; held-out 90% coverage 0.918) | The artifact is **unqualified**: 364 days against the 365-day policy, no storm data, no forecast error. Gust factor median 1.20 (old mock 1.30), direction scatter 8.5 deg (mock 15), current residual 0.22 kt (mock 0.15), correlation time 4.5 min. Current residuals use only the months with observations at cb0402. Existing artifact is unchanged and predates fitter hardening; no new qualified fit was produced. New fits count usable days, reject missing current uncertainty and keep AR input contiguous. |
| S11 risk | implemented | line and rated ship/pier/fender sampling (fender energy comparison, reaction-force percentiles); combined solve budget; endpoint-inclusive horizon with failed-solve bounds; supplied-snapshot or explicitly synthetic timeline; validity-aware alerts preserving installation tide | Probabilities are scenario outputs until a model is qualified. Sub-sample events remain unresolved; all-failed calculations are invalid. |
| S12 search | implemented | constrained bounded/exhaustive search; optional candidate resolved_config preserves the assessed installation for later tide rechecks | Fixed holding-tug assistance is evaluated across every case; tug selection is not optimized. Ranking does not use unqualified risk. |
| S13 sequence | implemented | generation/validation with loading/MST and explicit installation tide, staged parts and tug-release checks, quality/depth/rating guards, nonrecursive timing, cited printable intermediate states | Rule table unverified; durations unreviewed; static only. `draft_unreviewed` always. |
| F24 advance docking / master P1–P2 | implemented; resolver/recheck merged (#4/#8) | Canonical immutable supplied/scenario resolution with content/binding hashes; explicit revision comparison and reassessment without mutating old results. Default at-least-24h lead with explicit short-lead reassessment, candidate arrivals through operation/holding, coverage/issue/replay gates, bounded optional search, retained installation lengths, invalid-snapshot isolation and immutable result references | Public composer is in open #13; A3 must still bind agents/watch to one manifest. No transient approach/contact/line-handling clearance; separate sequence review required. Synthetic generators are training inputs, not forecasts. |
| S14 Phase 1 gate | **partial** | `test_s14_phase1_chain.py` (supported, overload, invalid, undetermined); local supported intake→plan→review→approved HTML chain: five runs, median 3.09 s (3.06–3.31 s), Python 3.12.13/macOS arm64, no LLM or external network, synthetic steady input. Actual TCP smoke also passed; PDF returned explicit 501 without native-library discovery; a subsequent full supported chain returned HTTP 200/26,175-byte PDF with the documented macOS library path. | **No subject-matter review.** Four named API chains also complete in 3.10–4.35 s locally; the initially underconstrained arrangement is repairable by search. No performance budget sign-off. Not a release gate pass. |
| S15 dynamics | synthetic integrator and wiring implemented | RK4 3-DOF; shared batch/interactive adapter; independent P3 analytical benchmarks merged (#5) | **No qualified vessel coefficients**, relative-flow derivatives or operational envelope. |
| S16 contact/batch | implemented (synthetic scope); physical gate open | Shared integrator; unilateral fenders; line activation/take-up; bounded persisted frames and validity; energy diagnostics; cooperative jobs | No independently sourced contact benchmark, qualified hull coefficients or rupture/snatch law. Not a Phase 2 gate pass. |
| S17 interactive / master S1 | implemented; rich runtime and review fixes merged (#6) | rm0-v1 frames, scene, lifecycle, speed, reconnect and saved recordings; same timed trajectory as batch; authoritative clock; pause/reset/reconnect; bounded commands, slew/capacity, ownership and latest-frame backpressure | Ephemeral single-process sessions, possible scheduling lag under load; no vessel qualification or subject-matter acceptance. |
| S18/S19 approach | **not started** | | Needs chart source/edition, datum transformations and a sourced squat formulation. Mock remains and is labeled. |
| S20 telemetry | S20a/b implemented | NMEA MWV/HDT/VTG/GGA/DPT declared subset, sensor registry validation, bounded storage, arbitration policy, optional HTTP/WS key | No AIS/NMEA 2000. Arbitration is not wired to the environment endpoints. No rate limiter beyond batch size. |
| S21 readiness | implemented local controls; deployment gate open | Opt-in bearer auth/ownership, HTTP limits, JSON events/metrics, SQLite backup/restore and v1 migration tests; `docs/DEPLOYMENT_READINESS.md` | No deployment load/security review, TLS/proxy/identity lifecycle, UI credential integration or automated retention/backup. Agents bearer propagation and ownership tests now pass. **Not ready for live use.** |

## Current master-plan additions

| Master item | Lead | Implemented | Remaining gate |
| --- | --- | --- | --- |
| S5 storyboarding | Snyder backend; Kori UI | Track/media/report ingestion, locations, storyboard and replay (#10) | Findings below; historical/simulated evidence must retain its validity |
| S6 port transit | Snyder M-SIM; Cruz source support | Surrogate transit and selected fixes (#10/#14) | Finding closure, source/route coverage and qualified maneuvering/propulsion inputs |
| S7/U8 camera | Snyder service; Kori overlay | `/predict/trajectory`, presets and initial missions/Transit overlay (#14) | Berthing engine, complete initial state, changing forcing/live own-ship integration, coastline and calibrated uncertainty; see [PREDICTION.md](PREDICTION.md) |
| U1–U7 | Kori; Bixler integration | UI and browser-check additions merged (#18) | Combined integration/target evidence; conditional roll/pitch/water displays do not implement missing S2/S3 physics |
| R1–R9 | Leads in [master plan §11](MASTER_PLAN.md#11-requirements-audit-remediation-prompts) | Executable specifications merged (#12) | Implementation and source evidence still required; use the [ownership table](MASTER_PLAN.md#execution-ownership) |
| A3/A7/A11, incremental A8/A10 | Bixler | Branch implementation: canonical supplied/scenario identity through agents, cited prediction explanations, frozen illustrated sheets, unsaved ship validation and geometry-based templates | Public provider discovery, U13/U9 consumption, actual additional-class records, loading-specific heights/review metadata and R4–R8 evidence remain; [current tests and handoff](BIXLER_IMPLEMENTATION.md) |

## PR #10 review disposition

Source: [the 16-finding review](https://github.com/fleethacker/pier-review/pull/10#issuecomment-6663809986), compared
with merged #14 and #18. This is a read-only code/history reconciliation, not a new reproduction run or blanket
approval. Record the closing PR, regression and independent review against each finding when it is resolved.

| Finding | Disposition on reconciled `dev` | Lead / next evidence |
| --- | --- | --- |
| 1, 2, 4–7: rejected RMC date changes, simulated-track validity, GGA quality, malformed uploads, JPEG decoding, duplicate-row memory | Open; relevant S5 backend paths were unchanged by #14/#18 | Snyder M-SIM fixes; Snyder M-PLAN independently verifies |
| 12–16: mission-selection race, decimated playback evidence, antipodal/dateline behavior, authenticated media/downloads | Open; relevant mission geometry/playback/media paths unchanged | Kori fixes; Snyder supplies authoritative location semantics; Bixler reviews integration |
| 9: future manual tug command suppresses earlier auto-assist | Open; manual tug IDs still selected from all future commands at initialization | Snyder M-SIM fixes simulation-time ownership; M-PLAN regression/review |
| 3, 8, 11: arrival speed, latched auto-assist, exact output sampling | Fixes and regressions added in #14; explicit independent closure still to record | Snyder's independent reviewer verifies each against original acceptance |
| 10: land-crossing presets | Partially addressed: OSM checks/rerouting, a 1 km pier-zone exception and two simulated presets; original complete NOAA-based criterion not demonstrated | Snyder + Cruz complete/review authoritative coverage and all applicable routes; keep restricted scope visible |

## Test evidence

Use the exact implementation PR and CI run for test counts, skips and xfails. This documentation reconciliation
intentionally skipped tests/CI at Snyder's request; it does not produce new runtime or release evidence.
The later Bixler branch has a separate [local acceptance record](BIXLER_IMPLEMENTATION.md), including the observed
status of the conditional shallow-current benchmark. Keep those results separate from the historical counts above.

## Measured performance (one machine, macOS arm64, Python 3.12, single runs; not a budget sign-off)

| Operation | Measurement |
| --- | --- |
| `compute_loads` (no serialization) | p50 about 5 us |
| Equilibrium solve, example mooring | p50 1.1 ms, p95 1.4 ms, 0 failures in 40 |
| Limiting wind, 24 bearings, 5 kt scan + 0.25 kt refinement | about 0.25 s |
| Exceedance, 200 samples | about 0.2 s; 2000 samples about 2 s |
| Horizon, 50 trajectories x 12 steps | about 0.25 s |
| Berthing windows, 24 h at 6 min | about 0.65 s |
| Line search, bounded descent | about 0.05 s |

The earlier 50 ms solve target is met on this machine for these cases; it says nothing about harder configurations.

## Environment findings (4 Nov 2026, live)

* Seed stations are valid: wind 8638614, water level 8638610, currents cb0402. Wind is **not** offered at 8638610.
* cb0402 observation and prediction bins differ: predictions exist for bins 4, 8, 11 only; bin 4 (about 20.6 ft deep, the real-time bin) is used for both.
* The current series is stamped about 2 minutes off the wind/water-level series; series are joined by nearest timestamp within 3 minutes, never interpolated across gaps.
* Several months of 2025 currents were missing at cb0402 ("No data was found"); the fit used what existed.
* Latest current observations lagged by about 2.3 hours while wind and water level were current.

## Historical decisions for review (4 November)

1. Validity and status are separated and enforced on the envelope; with seed data every real result is `limited`, so nothing returns an unconditional GREEN. Is that the intended demo experience?
2. The real equilibrium shows the single-part template plan overloaded at the MST II design condition and at the example gust. The earlier mock reported it as acceptable. Consumers (UI, agents) will now see RED for the demo example.
3. Sequence generation returns RED for the demo example because the final plan is overloaded.
4. Mock modules for moored solver, risk, optimizer, holding tugs, berthing tugs/sequence and telemetry were deleted after searching imports and callers.
5. When the live current observation lags, `/env/now` is 503 (stale). Should it instead fall back to the CO-OPS current *prediction*, labeled as a prediction? Not done: it would mix bases in one snapshot.
6. The previously published telemetry example sentence had a wrong checksum; it was corrected.

## S16/S17/S21 follow-on scope

Historical follow-on: `ws-e/berthing-sim-and-readiness` was stacked on the legacy repository's build-out PR #15.
That work is already integrated; current S1 (#6 in `fleethacker/pier-review`) extends its runtime. Do not reopen
the historical stack as a new task. [Simulation semantics](BERTHING_SIMULATION.md) and [readiness controls](DEPLOYMENT_READINESS.md) state parameters, error policies, compatibility and blockers. Synthetic consistency tests do not replace the independent evidence or reviews required by the execution plan.

## Concurrent agent-job smoke (4 November evening)

A burst of 40 real planner HTTP requests through in-process ASGI with two job workers and 16 queue slots accepted 18 and rejected 22 with HTTP 429 plus Retry-After. One queued job was cancelled; the remaining 17 completed with unique plan ids and AMBER/limited supported-case results. Elapsed 31.85 s, macOS arm64, no LLM or external provider. This demonstrates local queue/cancellation behavior, not deployment capacity, cross-host operation or scheduling guarantees.

A follow-up on 5 November repeated six bursts of 40 submissions with resolved line spans retained in each final plan: 240 submitted, 108 accepted, 132 rejected with 429/Retry-After, six queued cancellations and 102 successful unique AMBER/limited plans. Each burst took 30.87–32.87 s locally. This checks queue reuse, cancellation and payload preservation; it does not establish deployment throughput or operational qualification.
