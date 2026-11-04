# Modeling build-out: status, evidence and blockers

Branch `ws-b/modeling-build-out`, stacked on S00a (#11) and S00b (#13). One PR by request; the execution plan wanted one PR per packet, so each packet is its own commit for review. **Nothing here is complete until reviewed and merged.** Tests passing is existing-suite and new-suite evidence only; it is not validation against real ships, piers, ropes or tugs, and the seed data is placeholder data.

## Packet ledger

| Packet | State on this branch | What exists | What is not done / blocked |
| --- | --- | --- | --- |
| S01 data qualification | implemented | `qualification.py`, `GET /qualification`, `GET /capabilities`, rule coverage audit, defensive catalog copies, synthetic fixture | No published data on file, so every real asset is `demonstration`. NSTM paragraph references still unverified (`source_verified=false`). Edited runtime berths use `add_berth` replacement semantics. |
| S02 results and jobs | implemented, single host | SQLite write-once results, resolved-input snapshots, persistent scenarios, bounded worker pool, queue limit (429), deadlines, cancellation, restart recovery, SSE resume | Threads share the GIL; cancellation is cooperative. Not distributed. The agents service still uses its in-memory legacy job path. No authn/z on jobs. |
| S03 M3 validity | implemented | one wind-basis boundary, validity classification, depth-at-draft invalid, finding aggregation, `compute_loads` p50 about 5 us | UFC conversions beyond 60 s -> 30 s and 10 m are not implemented (reported limited, not converted). |
| S04 environment | S04a only | deterministic replay library, fixtures, gap/datum/quality/staleness policy | Replay is not wired to `/env/*` or WebSockets. **S04b CO-OPS and S04c forecasts not started:** they need live documentation and network access that this build could not verify. |
| S05 mechanics | implemented | pose, tension-only lines, pretension/slack/paid-out initialization, fenders with energy | Multi-part reeving and chock friction rejected or flagged, not modeled. |
| S06 equilibrium | implemented | joint 3-DOF solve, independent residual, rank and stability checks, tolerances, tug vectors | No heave/roll; fender vertical extent ignored; solver is local (a failed solve is never proof of infeasibility). |
| S07 limits and tide | implemented | bracketed limit search with distinct outcomes, tide sweep with explicit tending only | Wind speed scaling holds the request's gust ratio; no probabilistic limit. |
| S08 tug allocation | implemented | wrench allocation, static berthing plan | Ratings are catalog estimates; normal forces only. |
| S09 holding and windows | implemented | verified holding plans, forecast windows with gaps and refinement | Forecast is the deterministic mock. Candidate patterns are water-side points at a uniform rating fraction. |
| S10 uncertainty | tools implemented | fitting, split, qualification policy, seeded sampler | **No fitted model exists**; only the synthetic demo, unqualified. Fetch/fit scripts and real data not included. |
| S11 risk | implemented | exceedance, horizon trajectories, timeline, alerts | Probabilities are scenario outputs until a model is qualified. |
| S12 search | implemented | constrained bounded/exhaustive search | Tug-assisted conditions not searched; ranking does not use risk. |
| S13 sequence | implemented | generation, validation endpoint, intermediate states, tug provenance | Rule table unverified; durations unreviewed; static only. `draft_unreviewed` always. |
| S14 Phase 1 gate | **partial** | `test_s14_phase1_chain.py` (supported, overload, invalid, undetermined) | **No subject-matter review.** No performance budget sign-off. Not a release gate pass. |
| S15 dynamics | integrator only | RK4 3-DOF with analytic tests | **No vessel coefficients; not wired to the berthing API** (still mock). |
| S16 contact | integrator only | unilateral fenders, line take-up, event times, energy balance | No independently sourced contact benchmark; batch persistence not done. |
| S17 interactive | **not started** | | WebSocket session control still mock. |
| S18/S19 approach | **not started** | | Needs chart source/edition, datum transformations and a sourced squat formulation. Mock remains and is labeled. |
| S20 telemetry | S20a/b implemented | NMEA MWV/HDT, sensor registry validation, bounded storage, arbitration policy, optional key | No AIS/NMEA 2000. Arbitration is not wired to the environment endpoints. No rate limiter beyond batch size. |
| S21 readiness | **docs only** | `docs/DEPLOYMENT_READINESS.md` | No authn/z, metrics, backup/restore tests or load tests. Not ready for live use. |

## Test evidence

`make contract` and `make test` run before every commit. Final count is in the PR description. Skips: none. xfails: none.

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

## Decisions for review

1. Validity and status are separated and enforced on the envelope; with seed data every real result is `limited`, so nothing returns an unconditional GREEN. Is that the intended demo experience?
2. The real equilibrium shows the single-part template plan overloaded at the MST II design condition and at the example gust. The earlier mock reported it as acceptable. Consumers (UI, agents) will now see RED for the demo example.
3. Sequence generation returns RED for the demo example because the final plan is overloaded.
4. Mock modules for moored solver, risk, optimizer, holding tugs, berthing tugs/sequence and telemetry were deleted after searching imports and callers.
5. The previously published telemetry example sentence had a wrong checksum; it was corrected.
