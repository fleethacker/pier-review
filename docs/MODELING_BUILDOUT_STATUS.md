# Modeling build-out: status, evidence and blockers

Branch `ws-b/modeling-build-out`, stacked on S00a (#11) and S00b (#13). One PR by request; the execution plan wanted one PR per packet, so each packet is its own commit for review. **Nothing here is complete until reviewed and merged.** Tests passing is existing-suite and new-suite evidence only; it is not validation against real ships, piers, ropes or tugs, and the seed data is placeholder data.

## Packet ledger

| Packet | State on this branch | What exists | What is not done / blocked |
| --- | --- | --- | --- |
| S01 data qualification | implemented | `qualification.py`, `GET /qualification`, `GET /capabilities`, rule coverage audit, defensive catalog copies, synthetic fixture | No published data on file, so every real asset is `demonstration`. NSTM paragraph references still unverified (`source_verified=false`). Edited runtime berths use `add_berth` replacement semantics. |
| S02 results and jobs | implemented, single host | SQLite write-once results, resolved-input snapshots, persistent scenarios, bounded worker pool, queue limit (429), deadlines, cancellation, restart recovery, SSE resume | Threads share the GIL; cancellation is cooperative. Not distributed. Agents now use bounded background tasks with cancellation and resumable in-process planner events; agent records remain process-local. Opt-in ownership and authenticated modeling requests are implemented; durable agent recovery remains open. |
| S03 M3 validity | implemented | one wind-basis boundary, validity classification, depth-at-draft invalid, finding aggregation, `compute_loads` p50 about 5 us | UFC conversions beyond 60 s -> 30 s and 10 m are not implemented (reported limited, not converted). |
| S04 environment | S04a and S04b implemented, opt-in | deterministic replay; CO-OPS adapter (wind, water level, currents, tide and current predictions parsed) verified against the live API and recorded fixtures; retries, rate limit, TTL cache, stale policy, 503/502/422 mapping; `MOORING_ENV_SOURCE=coops` wires `/env/now`, `/env/history` and `/ws/env`; opt-in `scripts/smoke_coops.py` | Default stays `mock` (offline). **S04c forecasts not started:** `/env/forecast` returns 503 in coops mode (no wind forecast provider); NWS/CBOFS need documented spatial/depth sampling. Current-direction convention (`d` = toward) is an unconfirmed assumption. Live currents at cb0402 lag by hours, so `/env/now` is often 503 (stale); no prediction fallback was added. |
| S05 mechanics | implemented | pose, tension-only lines, pretension/slack/paid-out initialization, fenders with energy | Multi-part reeving and chock friction rejected or flagged, not modeled. |
| S06 equilibrium | implemented | joint 3-DOF solve, independent residual, rank and stability checks, tolerances, tug vectors | No heave/roll; fender vertical extent ignored; solver is local (a failed solve is never proof of infeasibility). |
| S07 limits and tide | implemented | bracketed limit search with distinct outcomes, tide sweep with explicit tending only | Wind speed scaling holds the request's gust ratio; no probabilistic limit. |
| S08 tug allocation | implemented | wrench allocation, static berthing plan | Ratings are catalog estimates; normal forces only. |
| S09 holding and windows | implemented | verified holding plans, forecast windows with gaps and refinement | Forecast is the deterministic mock. Candidate patterns are water-side points at a uniform rating fraction. |
| S10 uncertainty | tools, fit script and one fitted artifact | fitting, event split, qualification policy, seeded sampler; `scripts/fit_uncertainty.py`; artifact `coops-8638614-2025` (2025 CO-OPS wind 8638614 and current cb0402 bin 4; held-out 90% coverage 0.918) | The artifact is **unqualified**: 364 days against the 365-day policy, no storm data, no forecast error. Gust factor median 1.20 (old mock 1.30), direction scatter 8.5 deg (mock 15), current residual 0.22 kt (mock 0.15), correlation time 4.5 min. Current residuals use only the months with observations at cb0402. |
| S11 risk | implemented | exceedance, horizon trajectories, timeline, alerts | Probabilities are scenario outputs until a model is qualified. |
| S12 search | implemented | constrained bounded/exhaustive search | Tug-assisted conditions not searched; ranking does not use risk. |
| S13 sequence | implemented | generation, validation endpoint, intermediate states, tug provenance | Rule table unverified; durations unreviewed; static only. `draft_unreviewed` always. |
| S14 Phase 1 gate | **partial** | `test_s14_phase1_chain.py` (supported, overload, invalid, undetermined); local supported intake→plan→review→approved HTML chain: five runs, median 3.09 s (3.06–3.31 s), Python 3.12.13/macOS arm64, no LLM or external network, synthetic steady input. Actual TCP smoke also passed; PDF returned explicit 501 (renderer unavailable). | **No subject-matter review.** No performance budget sign-off. Not a release gate pass. |
| S15 dynamics | synthetic integrator; wiring pending review | RK4 3-DOF with analytic tests; shared batch/interactive adapter | **No qualified vessel coefficients**, relative-flow derivatives or operational envelope. |
| S16 contact/batch | implemented, pending review (synthetic scope) | Shared integrator; unilateral fenders; line activation/take-up; bounded persisted frames and validity; energy diagnostics; cooperative jobs | No independently sourced contact benchmark, qualified hull coefficients or rupture/snatch law. Not a Phase 2 gate pass. |
| S17 interactive | implemented, pending review (local controls) | Same timed trajectory as batch; authoritative clock; pause/reset/reconnect; bounded commands, slew/capacity, ownership and latest-frame backpressure | Ephemeral single-process sessions, possible scheduling lag under load; no vessel qualification or subject-matter acceptance. |
| S18/S19 approach | **not started** | | Needs chart source/edition, datum transformations and a sourced squat formulation. Mock remains and is labeled. |
| S20 telemetry | S20a/b implemented | NMEA MWV/HDT, sensor registry validation, bounded storage, arbitration policy, optional key | No AIS/NMEA 2000. Arbitration is not wired to the environment endpoints. No rate limiter beyond batch size. |
| S21 readiness | implemented, pending review (scoped local controls) | Opt-in bearer auth/ownership, HTTP limits, JSON events/metrics, SQLite backup/restore and v1 migration tests; `docs/DEPLOYMENT_READINESS.md` | No deployment load/security review, TLS/proxy/identity lifecycle, UI credential integration or automated retention/backup. Agents bearer propagation and ownership tests now pass. **Not ready for live use.** |

## Test evidence

Contract export and the full Python suite run before review. Final count is in the PR description. Skips: none. xfails: none.

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

## Decisions for review

1. Validity and status are separated and enforced on the envelope; with seed data every real result is `limited`, so nothing returns an unconditional GREEN. Is that the intended demo experience?
2. The real equilibrium shows the single-part template plan overloaded at the MST II design condition and at the example gust. The earlier mock reported it as acceptable. Consumers (UI, agents) will now see RED for the demo example.
3. Sequence generation returns RED for the demo example because the final plan is overloaded.
4. Mock modules for moored solver, risk, optimizer, holding tugs, berthing tugs/sequence and telemetry were deleted after searching imports and callers.
5. When the live current observation lags, `/env/now` is 503 (stale). Should it instead fall back to the CO-OPS current *prediction*, labeled as a prediction? Not done: it would mix bases in one snapshot.
6. The previously published telemetry example sentence had a wrong checksum; it was corrected.

## S16/S17/S21 follow-on scope

Branch `ws-e/berthing-sim-and-readiness`, stacked on the build-out branch while #15 is open. [Simulation semantics](BERTHING_SIMULATION.md) and [readiness controls](DEPLOYMENT_READINESS.md) state parameters, error policies, compatibility and blockers. Synthetic consistency tests do not replace the independent evidence or reviews required by the execution plan.
