# Modeling build-out: status, evidence and blockers

> Priorities and owners for remaining work: [MASTER_PLAN.md](MASTER_PLAN.md). This file is the capability ledger.

**Product audit, 5 November 2026 (`ac73e1f`):** [NEXT_STEPS.md](NEXT_STEPS.md) preserves 28 product findings,
including modeling validity/contact failures (F03–F08, F24–F26), rich-frame evidence loss (F05/F25), API/source
compatibility (F20/F21) and runtime/persistence/telemetry failures (F14–F22). F01/F02/F09/F10 are cross-service UI
handoff defects, not completed integration simply because the underlying endpoints exist. Follow the named leads,
reviewers and closure evidence in that ledger before treating the historical implementation rows below as accepted.
F01–F28 are resolved through source/contract commit `ea62351`; independent review and final local checks pass
(2,815 Python tests, 1,066 frontend tests, contract/type/lint/build checks). See
[PRODUCT_AUDIT_REMEDIATION.md](PRODUCT_AUDIT_REMEDIATION.md) for reproducible scope and the PR for CI/merge status.
The camera seek and unbound-berth corrections in `5c28b56` passed independent browser/probe checks.
G01–G08 and physical qualification remain open. The archived NOAA prediction example now correctly returns RED/invalid because its declared
environment interval ends before the prediction clock; this is an intentional validity correction, not a qualified new forecast.

**Reconciled 5 November 2026 against `dev` at `3ababad` (PR #18).** Snyder maintains modeling evidence;
Cruz supplies source/telemetry/chart evidence, Kori supplies browser evidence, and Bixler maintains the integrated
status and release gate. [Execution ownership](MASTER_PLAN.md#execution-ownership) names leads, collaborators,
reviewers and dependencies. This documentation pass ran no tests or CI; previous counts remain tied to their PRs.

P1's canonical resolver is implemented and merged in #4; it is not a 501 stub. P2 rechecks (#8), initial P3 analytic
benchmarks (#5), S1 rich runtime/recordings (#6), S7/U8's initial transit-based camera (#14), and U1–U7 UI (#18) are
merged. #14 addresses several S6 defects but not the full #10 review; see the disposition below. D1–D4 composition,
source selection, replay and waves subsequently merged in #13, followed here by integration of `dev` at `684db99`.
The Bixler implementation branch now provides supplied/scenario
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
| S04 environment | provider composition and offshore-wave acquisition implemented, opt-in | strict `mock`/`coops`/`replay`/`auto` source selection; component availability; manifest-backed recorded-real replay; content-addressed NWS + CO-OPS + optional decoded CBOFS forecast composition; bounded NDBC 44099 native total/partition/spectrum parsing, NDBC 44014 independent check and optional decoded GFS-Wave guidance bound to reviewed grid, cycle, lead, partition and variable identities; deterministic offline tests and opt-in `scripts/smoke_{coops,waves}.py` | Public availability is not engineering qualification. Live cb0402 observations may be stale; CBOFS depth/cell must match exactly and GFS-Wave needs a separately acquired decoded artifact. NDBC rows over three hours old and GFS issues over 18 hours old are unavailable; NDBC sample bounds remain unknown. All wave data are offshore boundary conditions with `load_ready=false`; no validated berth transfer, directional fetch, ship wake or tug wake exists, so waves do not yet feed qualified vessel forcing. Instrument heading, current-bin and station/grid representativeness remain unqualified. |
| S05 mechanics | implemented | pose, tension-only lines, pretension/slack/paid-out initialization, fenders with energy | Multi-part reeving and chock friction rejected or flagged, not modeled. |
| S06 equilibrium | implemented | joint 3-DOF solve, independent residual/rank/stability checks, tolerances, tug vectors, resolved line spans and solved-pose line geometry for reports/rules | No heave/roll; fender vertical extent ignored; solver is local (a failed solve is never proof of infeasibility). |
| S07 limits and tide | implemented | bracketed limit search with distinct outcomes and null limits for invalid inputs; supplied-forecast or explicitly synthetic tide sweep with explicit tending only | Wind speed scaling holds the request's gust ratio; no probabilistic limit. |
| S08 tug allocation | implemented | wrench allocation, static berthing plan | Ratings are catalog estimates; normal forces only. |
| S09 holding and windows | implemented | verified holding plans, forecast windows with gaps and refinement | Forecast is the deterministic mock. Candidate patterns are water-side points at a uniform rating fraction; first passing candidate, not a minimum-force optimum. Empty requested fleets remain empty; duplicate tug IDs reject. |
| S10 uncertainty | tools, fit script and one fitted artifact | fitting, train-only event split, qualification policy, seeded global sampler; exploratory sector fits with explicit unqualified status; `scripts/fit_uncertainty.py`; artifact `coops-8638614-2025` (2025 CO-OPS wind 8638614 and current cb0402 bin 4; held-out 90% coverage 0.918) | The artifact is **unqualified**: 364 days against the 365-day policy, no storm data, no forecast error. Gust factor median 1.20 (old mock 1.30), direction scatter 8.5 deg (mock 15), current residual 0.22 kt (mock 0.15), correlation time 4.5 min. Current residuals use only the months with observations at cb0402. Existing artifact is unchanged and predates fitter hardening; no new qualified fit was produced. New fits count usable days, reject missing current uncertainty and keep AR input contiguous. |
| S11 risk | implemented | line and rated ship/pier/fender sampling (fender energy comparison, reaction-force percentiles); combined solve budget; endpoint-inclusive horizon with failed-solve bounds; supplied-snapshot or explicitly synthetic timeline; validity-aware alerts preserving installation tide | Probabilities are scenario outputs until a model is qualified. Sub-sample events remain unresolved; all-failed calculations are invalid. |
| S12 search | implemented | constrained bounded/exhaustive search; optional candidate resolved_config preserves the assessed installation for later tide rechecks | Fixed holding-tug assistance is evaluated across every case; tug selection is not optimized. Ranking does not use unqualified risk. |
| S13 sequence | implemented | generation/validation with loading/MST and explicit installation tide, staged parts and tug-release checks, quality/depth/rating guards, nonrecursive timing, cited printable intermediate states | Rule table unverified; durations unreviewed; static only. `draft_unreviewed` always. |
| F24 advance docking / master P1–P2 | implemented; resolver/recheck merged (#4/#8), supplied-series static scope | Canonical immutable supplied/scenario resolution with content/binding hashes; explicit revision comparison and reassessment without mutating old results. Default at-least-24h lead with explicit short-lead reassessment, candidate arrivals through operation/holding, coverage/issue/replay gates, bounded optional search, retained installation lengths, invalid-snapshot isolation and immutable result references. | A composed public forecast contract now exists, and A3 binds supplied/scenario agent assessments to one manifest. Agent public-revision acquisition, complete component coverage and engineering review remain. No transient approach/contact/line-handling clearance; separate sequence review required. Synthetic generators are training inputs, not forecasts. |
| S14 Phase 1 gate | **partial** | `test_s14_phase1_chain.py` (supported, overload, invalid, undetermined); local supported intake→plan→review→approved HTML chain: five runs, median 3.09 s (3.06–3.31 s), Python 3.12.13/macOS arm64, no LLM or external network, synthetic steady input. Actual TCP smoke also passed; PDF returned explicit 501 without native-library discovery; a subsequent full supported chain returned HTTP 200/26,175-byte PDF with the documented macOS library path. | **No subject-matter review.** Four named API chains also complete in 3.10–4.35 s locally; the initially underconstrained arrangement is repairable by search. No performance budget sign-off. Not a release gate pass. |
| S15 dynamics | synthetic integrator and wiring implemented | RK4 3-DOF; shared batch/interactive adapter; independent P3 analytical benchmarks merged (#5) | **No qualified vessel coefficients**, relative-flow derivatives or operational envelope. |
| S16 contact/batch | implemented (synthetic scope); physical gate open | Shared integrator; unilateral fenders; line activation/take-up; bounded persisted frames and validity; energy diagnostics; cooperative jobs | No independently sourced contact benchmark, qualified hull coefficients or rupture/snatch law. Not a Phase 2 gate pass. |
| S17 interactive / master S1 | implemented; rich runtime and review fixes merged (#6) | rm0-v1 frames, scene, lifecycle, speed, reconnect and saved recordings; same timed trajectory as batch; authoritative clock; pause/reset/reconnect; bounded commands, slew/capacity, ownership and latest-frame backpressure | Ephemeral single-process sessions, possible scheduling lag under load; no vessel qualification or subject-matter acceptance. |
| S18/S19 approach | **not started** | | Needs chart source/edition, datum transformations and a sourced squat formulation. Mock remains and is labeled. |
| S20 telemetry | S20a/b implemented | NMEA MWV/HDT/VTG/GGA/DPT declared subset, sensor registry validation, bounded storage, arbitration policy, optional HTTP/WS key | No AIS/NMEA 2000. Arbitration is not wired to the environment endpoints. No rate limiter beyond batch size. |
| S21 readiness | implemented local controls; deployment gate open | Opt-in bearer auth/ownership, HTTP limits, JSON events/metrics, SQLite backup/restore and v1 migration tests; remediation adds per-tab runtime HTTP/fetch-SSE credentials; `docs/DEPLOYMENT_READINESS.md` | Native browser WebSockets still require a trusted gateway. No deployment load/security review, identity lifecycle or automated retention/backup. Separate pre-remediation Domino smoke does not validate remediation code or per-user resource isolation. **Not ready for live use.** |

## Current master-plan additions

| Master item | Lead | Implemented | Remaining gate |
| --- | --- | --- | --- |
| S5 storyboarding | Snyder backend; Kori UI | Track/media/report ingestion, locations, storyboard and replay (#10) | Findings below; historical/simulated evidence must retain its validity |
| S6 port transit | Snyder M-SIM; Cruz source support | Surrogate transit and selected fixes (#10/#14) | Finding closure, source/route coverage and qualified maneuvering/propulsion inputs |
| S7/U8 camera | Snyder service; Kori overlay | `/predict/trajectory`, presets and initial missions/Transit overlay (#14) | Berthing engine, complete initial state, changing forcing/live own-ship integration, coastline and calibrated uncertainty; see [PREDICTION.md](PREDICTION.md) |
| U1–U7 | Kori; Bixler integration | UI and browser-check additions merged (#18) | Combined integration/target evidence; conditional roll/pitch/water displays do not implement missing S2/S3 physics |
| R1–R9 | Leads in [master plan §11](MASTER_PLAN.md#11-requirements-audit-remediation-prompts) | Executable specifications merged (#12) | Implementation and source evidence still required; use the [ownership table](MASTER_PLAN.md#execution-ownership) |
| A3/A7/A11, incremental A8/A10 | Bixler | Branch implementation: canonical supplied/scenario identity through agents, cited prediction explanations, frozen illustrated sheets, unsaved ship validation and geometry-based templates | Public provider discovery, U13/U9 consumption, actual additional-class records, loading-specific heights/review metadata and R4–R8 evidence remain; [current tests and handoff](BIXLER_IMPLEMENTATION.md) |

## Snyder-lane additions (PR #22)

Implemented on `ws-e/snyder-demo-sprint` (PR #22), awaiting cross-review and merge to `dev`; not on `dev` until then. All
are synthetic and unqualified. Merged would still not mean qualified. This pass ran no tests; the files named are the evidence
that exists on the branch, and their results belong to the PR/CI run.

| Master item | Implemented | Evidence | What is not done / limits |
| --- | --- | --- | --- |
| S2 forcing | Immutable `ForcingSpec` (steady, ramp, seeded gusts, replay; synthetic tide term; optional apparent wind; `on_uncovered` stop/invalidate) resolved at integration-stage time for batch and interactive paths; `forcing_revision`/`forcing_synthetic` on sessions and frames; a channel the series lacks is unavailable, not zero | `test_s2_forcing.py`, `test_p3_s2_s3_benchmarks.py` | Forcing is supplied or generated, not a composed live forecast (D2/D8 not wired). Gusts and tide are synthetic. No waves in forcing. Current is not made vessel-relative (water drag stays in body damping). No qualified vessel coefficients |
| S3 wiring | Tug push-point binding, capacity clamp and slew (`s3_tug_geometry`) inside the berthing model, numerically identical to the prior inline ramp; heave `prescribed` in rm0 frames from the S2 water level only when a series supplies it, else null and `not_simulated` | `test_s3_geometry_vertical.py`, `test_s3_wiring.py`, `test_p3_s2_s3_benchmarks.py` | Roll and pitch not simulated: no GM or displacement exists or is invented. Tug position/velocity/acceleration not simulated (null). Heave is the water level with zero waterline offset, not a hydrodynamic response. No sourced push-point or tug data |
| S4 surrogate | `POST /loads/wave-surrogate`: seeded random-phase JONSWAP-shaped scalar elevation; total or partitions, never both; missing spectrum is `unavailable`; always `qualified=false` | `test_s4_wave_surrogate.py`, `test_api_p5_p6_s4.py` | Visualization only: not connected to mooring or berthing forces, no direction, no berth transfer; gamma is a scenario parameter; offshore availability (D4) is not berth forcing |
| P5 horsepower | `POST /tugs/horsepower-plan`: exhaustive minimum-total-hp placement-feasible assignment for a required wrench, at most 8 tugs, deterministic tie-break, margins and infeasibility reasons | `test_p5_tug_horsepower.py` (includes an independent brute-force comparison), `test_api_p5_p6_s4.py` | Fleet bollard pull and horsepower are catalog seed/synthetic (validity `limited`); horsepower is never converted to force; normal forces only (surge infeasible); not wired to the planner or UI |
| P6 ultimate gust | `POST /risk/ultimate-gust`: gust threshold search against a caller-supplied `UltimateCapacityBasis`; no basis returns 200 `unavailable`; indeterminate outcomes are distinct; WLL crossing reported separately | `test_p6_ultimate_gust.py`, `test_api_p5_p6_s4.py` | The repository holds **no sourced ultimate capacity or material-law data**; only `synthetic_test_fixture` bases are exercised. No breaking threshold is invented; `validated_rupture_prediction` is always false; static wind/current only; A9/U10 consumers absent |
| S8 sequence search | `POST /mooring/sequence/search`: bounded (at most 60) deterministic search over line orders with caller-supplied `must_precede`/`first_line`, intermediate static checks, ranked proposals and explicit truncation bounds | `test_s8_sequence_search.py` | **Draft, unreviewed** (`draft_unreviewed`). Constraints are not sourced handling rules; static only (no dynamic handling, crews' timing unreviewed); not an optimum over all orders when truncated; U11 and planner handoff not built |
| P3 extension | Independent closed-form S2/S3 benchmarks (forcing series, tug force/yaw moment, tide heave) | `test_p3_s2_s3_benchmarks.py` | Synthetic numerical consistency only; not vessel or physical qualification; cross-review pending |

## PR #10 review disposition

Source: [the 16-finding review](https://github.com/fleethacker/pier-review/pull/10#issuecomment-6663809986), compared
with merged #14 and #18. This is a read-only code/history reconciliation, not a new reproduction run or blanket
approval. Record the closing PR, regression and independent review against each finding when it is resolved.

| Finding | Disposition on reconciled `dev` | Lead / next evidence |
| --- | --- | --- |
| 1: rejected RMC/GGA changes the NMEA date state | **Closed on branch (pending independent review).** Date/time-of-day state is staged and committed only for accepted sentences | `test_s5_ledger.py::test_rejected_rmc_does_not_change_the_date_for_later_gga`, `::test_rejected_gga_does_not_roll_the_date_over` |
| 2: simulated-track validity | **Closed on branch (pending review).** Events located on a `simulated*` source fix are `limited` with `SIMULATED_TRACK`, never `valid` | `test_s5_ledger.py::test_events_on_simulated_track_are_limited_never_valid` |
| 4: GGA quality | **Closed on branch (pending review).** Only quality 1-5 accepted; 0, 6 (estimated), 7 (manual), 8 (simulation) and non-numeric rejected | `test_s5_ledger.py::test_gga_quality_only_measured_fixes_accepted` |
| 5: malformed uploads | **Partly closed.** Oversized CSV fields (`csv.Error`) were an uncaught 500, now 422; a fuzz set of malformed CSV/GPX/GeoJSON/NMEA bodies returns 4xx. Not an exhaustive fuzz | `test_s5_ledger.py::test_csv_oversized_field_is_4xx_not_500`, `::test_malformed_uploads_never_500` |
| 6: JPEG decoding | **Closed on branch (pending review).** `verify()` only checks structure; images are now fully decoded at upload, so a truncated JPEG is 422 | `test_s5_ledger.py::test_truncated_jpeg_is_refused_at_upload` |
| 7: duplicate-row memory | **Closed on branch (pending review).** Same-timestamp fixes are dropped during parsing (first kept) and still counted as `duplicates`; existing tests `test_cap_counts_distinct_timestamps_so_duplicate_reupload_still_works` and `test_csv_fixture_reports_each_bad_row_with_line_numbers` were updated to the new accounting (fixes + duplicates unchanged) | `test_s5_ledger.py::test_duplicate_timestamps_are_dropped_while_parsing_and_still_counted` |
| 12–16: mission-selection race, decimated playback evidence, antipodal/dateline behavior, authenticated media/downloads | Open; relevant mission geometry/playback/media paths unchanged | Kori fixes; Snyder supplies authoritative location semantics; Bixler reviews integration |
| 9: future manual tug command suppresses earlier auto-assist | **Closed on branch (pending review).** Manual ownership starts at the tug's first command in simulation time | `test_s6_ledger.py::test_future_manual_command_does_not_suppress_earlier_auto_assist`, `::test_manual_command_at_t0_still_owns_the_tug` |
| 3, 8, 11: arrival speed, latched auto-assist, exact output sampling | Fixes and regressions added in #14; explicit independent closure still to record | Snyder's independent reviewer verifies each against original acceptance |
| 10: land-crossing presets | Partially addressed: OSM checks/rerouting, a 1 km pier-zone exception and two simulated presets; original complete NOAA-based criterion not demonstrated | Snyder + Cruz complete/review authoritative coverage and all applicable routes; keep restricted scope visible |

S7 hazard-coverage honesty, swept-hull checking, uncertainty-unavailable reporting and clone/bounds tests are in
`modeling/tests/test_s7_honesty.py` (see [PREDICTION.md](PREDICTION.md)). Findings 12-16 (Kori's UI paths) and 10 (coastline source
evidence) are untouched here and remain open. "Closed on branch" means fixed with a regression test on the working branch, not yet merged
or independently reviewed.

## Test evidence

The remediation report records the newer local evidence separately: an earlier integrated Python run reported
2,776 passed; frontend checks subsequently reported 1,065 passed in 72 files with typecheck/lint/build passing, before
the latest camera review follow-ups. The final integrated rerun, exact skip/xfail accounting and independent acceptance
are pending. The first final Python rerun reported 2,808 passed and 6 A7 narration fixture failures. Those fixtures
were corrected in `a978b57` with 14 focused tests passing; a further full rerun is pending, as explained in the report. The scoped no-browser smoke reported 21 passed, 0 failed and 4 skipped; it is not a readiness pass.
See [the evidence scope](PRODUCT_AUDIT_REMEDIATION.md#validation-evidence) rather than treating these provisional counts as release approval.

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
