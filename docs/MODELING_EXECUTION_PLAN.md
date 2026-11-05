# Remaining modeling development: execution plan

> Packet **scope and acceptance** still come from this file. **Priorities, owners and order** for the rest of the build come from [MASTER_PLAN.md](MASTER_PLAN.md), which wins on conflict.

Reviewed 4 November 2026 against `dev` at `5345bdd6e8bb48471463531c500c57e8ba1a0fc3` (PRs #6, #7 and #8 merged).

**This is the implementation authority for remaining modeling work.** [PLAN.md](PLAN.md) remains the product roadmap; its illustrative APIs and module sketches are not implementation specifications. The generated [contract](../contract/README.md) defines the current API. This plan describes changes to make through schemas, tests and regenerated contracts, never by hand-editing generated files.

Start with **S00**, then take the first unfinished packet whose dependencies have merged. Each packet is a separate PR into `dev`; packets explicitly split into sub-PRs must be completed in that order. Do not implement the whole roadmap in one branch. The complete sequence includes M1, M2, remaining M3 integration, M4–M7 and M11–M13. LLM agents, frontend features and automated operational approval are outside this workstream, except compatibility tests and documented integration requirements.

## Adversarial review: what would make the old plan fail?

| Priority | Finding and evidence in current code | Required correction |
| --- | --- | --- |
| P0 | A believable response is not proof of equilibrium. `moored/mock/solver.py` distributes loads with springs, fixes yaw and does not establish a three-component balance. Missing fitting ratings can still look GREEN. | S00 separates validity from status; S01 qualifies data; S05–S06 require independent force/moment residuals, active contacts and constraint diagnostics. |
| P0 | The advertised async infrastructure computes before submitting. Routers pass completed results to `core/jobs.py`, which delays revealing them. | S02 implements actual bounded background execution. At the old target of 50 ms/solve, 2,000 samples cost 100 seconds; a 48-hour half-hour timeline with 97 points costs roughly 2.7 hours if repeated naively, before overhead. Budget and benchmark the whole operation. |
| P0 | The environment contract cannot distinguish gust averaging durations; the roadmap confuses reporting cadence with wind averaging time. M3 already converts sustained wind to its design basis. | S03 establishes metadata and one conversion boundary before live feeds; never convert twice or silently treat an unknown gust basis as verified. |
| P0 | “Real seed loader” is being confused with qualified ship/pier data. Several ship seeds lack fittings; line, berth and tug data are placeholders. | S01 defines capabilities per asset. A DDG demonstration does not qualify every class, pier or tug. Missing required data prevents a valid GREEN result. |
| P1 | Backend swaps do not replace direct mock imports. `scenarios.py`, `examples.py`, and phase implementations reference mocks. | S00 inventories callers and introduces stable interfaces; each replacement removes all production imports of the replaced mock. Preserve phase boundaries. |
| P1 | M3 warnings reach loads, analysis and static berthing sizing, but not every risk/window/holding path; `run_rules=False` also bypasses findings. | Validity checks are independent of optional compliance checks and propagate through every aggregate, including sampled failures. S03 and each consumer packet test this. |
| P1 | Risk mock caps samples, uses invented distributions, ignores horizon semantics and maps utilization to a probability. | S10 qualifies an uncertainty model; S11 distinguishes instantaneous exceedance from correlated horizon risk, reports sampling uncertainty and never discards failed solves. |
| P1 | Tug and optimizer mocks can report success without satisfying yaw, inventory, assignments, all MST alternatives or actual assisted equilibrium. | S08–S09 require wrench feasibility; S12 requires hard constraints and separates exhausted search from proven infeasibility. |
| P1 | Envelope bisection assumes monotonicity across changing slack/contact states. Tide calculations can accidentally reset the installed line lengths. | S07 searches for the first failure with explicit bracketing checks and preserves installed rest lengths until a modeled tending action. |
| P1 | A request hash does not capture mutable reference data, resolved environment, model revisions or RNG configuration. In-memory result IDs cannot survive restart. | S02 snapshots resolved inputs and persists immutable results and provenance. |
| P1 | Static drag reuse is insufficient to validate a maneuvering model. The mock simulators and route planner contain synthetic trajectories, depths and energy assumptions. | S15–S19 require qualified hydrodynamics, timestep/contact tests, chart coverage and datum alignment; synthetic fixtures remain clearly labeled. |
| P1 | Telemetry validation is superficial and storage keeps only the latest record per source. Multiple sensors, stale data and apparent wind can corrupt a seemingly valid forecast. | S20 validates identity, units, timestamps, calibration and arbitration before telemetry may affect a calculation. |
| P2 | The roadmap claims Schemathesis CI and Prism integration, but this checkout has no `.github` workflows. Several proposed “golden” tests only compare models sharing the same assumptions. | S00 establishes reproducible CI; every physics packet includes an independent analytical or sourced benchmark. Calibration and cross-module agreement are secondary evidence. |

These findings are development blockers for the affected capabilities, not a request to replace the already reviewed M3 formulas. The merged M3 implementation, its worked-example tests, bounded seed calibration and corrected NSTM bearings are the baseline.

## Rules that apply to every packet

1. Read [CONTRIBUTING.md](../CONTRIBUTING.md), [modeling/README.md](../modeling/README.md), the contract conventions and the relevant code before editing. Branch from latest `dev`; open a PR into `dev`; do not merge it yourself. Never rewrite previous PR history.
2. Keep a packet confined to the named capability, its API wiring, tests, documentation and necessary generated contracts. Changes to shared infrastructure must run both modeling and agent regressions. Coordinate consumer review for additive schema changes; breaking changes require the repository's explicit compatibility process.
3. Put shared mechanics in a new `mooring/mechanics/` capability. Shared capabilities never import phases; phases never import other phases. M11 may reuse line/fender mechanics without importing the M4 phase service. Agents continue to call the modeling API through their gateway.
4. Before implementing a sourced formula, record document edition, equation/table/paragraph, units, domain and a reproducible benchmark. Distinguish published constants, fitted parameters, engineering estimates and numerical tolerances. If the primary source or necessary input is unavailable, stop that formula's implementation, record the missing item and leave the capability unqualified. Do not invent a coefficient to make a demo pass. Do not commit restricted documents or large downloaded datasets.
5. Never infer validity from `backend="real"`, optimizer termination, zero failed samples or a GREEN status. Real describes implementation, not certification. Keep existing status enums; add validity and diagnostic fields through S00. Invalid/unsupported calculations cannot produce a valid GREEN conclusion. A numerical failure is not proof that no physical equilibrium exists.
6. Preserve wind-from/current-toward, true bearings, ship +x forward/+y port/positive yaw counterclockwise, and berth +y off-pier. Explicitly transform between frames. Use named unit conversions; do not require a rewrite of M3's consistent imperial calculation just to impose SI everywhere.
7. Use deterministic fixtures and an injected clock. Unit/integration tests must not depend on live NOAA, wall-clock phase or external model services. Add recorded, small, legally shareable fixtures and separate opt-in live smoke checks.
8. Run `make contract` and `make test` before review; commit generated changes with schema changes. Report counts, skipped/xfail cases and reasons. An xfail documenting a source discrepancy does not satisfy the affected release gate; do not turn an implementation regression into an xfail.
9. Each PR includes scope, dependency commits, equations/parameter provenance, independent expected-versus-computed results, failure tests, performance evidence where relevant, and remaining limitations. Update the packet's completion evidence below only after review/merge. Delete its mock only after searching all imports, examples, jobs and WebSocket callers.

## Contract and validity decisions to implement first

S00 must implement and document these decisions, with exact field placement settled in its PR before downstream work:

- Add optional typed validity/diagnostics to computed results or envelopes without removing current fields: `valid`, `limited`, `invalid`, reason codes and affected components. New real paths always populate them; absence on legacy responses means unknown, never valid by default. Invalid results use RED with explanatory findings; limited results cannot be presented as unconditional GREEN. Preserve physical utilization independently from overall status.
- Distinguish malformed inputs (422), missing path resources (404), unavailable providers (documented service error), physically infeasible cases (completed RED result) and computational failure (invalid result or failed job). Search timeout means undetermined, not infeasible. Do not encode unknown quantities as zero, infinity or NaN.
- Define solver diagnostics: convergence, dimensional force/moment residuals, iterations, active constraints, support/rank checks and tolerance values. Define scenario/body precedence; do not silently resolve conflicting duplicated inputs.
- Define line semantics before writing mechanics: paid-out unstretched length, initial geometry, slack and pretension precedence, wet/dry curve, parts and reeving, chock routing, loading-dependent fitting heights and tending actions. Reject inconsistent specifications. Preserve current payloads with documented legacy defaults where physically interpretable; label assumptions.
- Define environment source metadata: observation versus prediction versus scenario, source and issue/valid times, wind averaging/gust durations and reference height, current depth/bin, vertical datum, quality and freshness. Store originals alongside normalized inputs. Adding metadata must not silently change legacy numerical results.
- Define a dependency manifest for each result: resolved ship/berth/line/tug records and revisions, environment snapshot, model/code version, numerical settings and optional RNG seed/model revision. Keep request hash compatibility; add a resolved-input hash instead of changing the meaning of the existing hash silently.

## Packet order and dependencies

The order below is the default execution order. Dependencies are hard gates, not an invitation to parallelize incomplete assumptions. S20 can be advanced after its dependencies if live sensor integration becomes a priority. S14 is the Phase 1 gate; S17 and S19 are later phase gates.

| Packet | Deliverable | Required packets |
| --- | --- | --- |
| S00 | Contract semantics, stable interfaces and baseline CI | none |
| S01 | M2 reference-data validation and capability qualification | S00 |
| S02 | Reproducible results and real bounded jobs | S00 |
| S03 | M3 validity propagation and environmental basis integration | S00, S01 |
| S04 | M1 replay, observations and forecast adapters | S02, S03 |
| S05 | Shared line, fitting and fender mechanics | S01, S03 |
| S06 | M4 three-DOF equilibrium and compliance integration | S05 |
| S07 | M4 limiting envelopes and tide tending | S04, S06 |
| S08 | M6 constrained tug allocation and static berthing | S01, S03 |
| S09 | M6 holding assistance and berthing windows | S04, S06, S08 |
| S10 | M1 uncertainty-model fitting and qualification | S04 |
| S11 | M5 exceedance, timelines and alerts | S02, S06, S10 |
| S12 | M7 constrained line-plan search | S02, S07, S09, S11 |
| S13 | M7 executable sequence and resource validation | S09, S12 |
| S14 | Phase 1 integration and subject-matter review | S07–S13 |
| S15 | M11 hydrodynamic inputs and three-DOF integrator | S02, S05, S08 |
| S16 | M11 contact, line events and batch berthing | S06, S13, S15 |
| S17 | M11 interactive control and Phase 2 gate | S16 |
| S18 | M12 chart/route/UKC/tidal-window planning | S01–S04 |
| S19 | M12 validated approach dynamics and Phase 3 gate | S15, S17, S18 |
| S20 | M13 telemetry decoding, quality and arbitration | S02–S04 |
| S21 | Deployment and live-use readiness | S14; S17/S19/S20 for capabilities deployed |

### S00 — Freeze semantics and remove hidden swap dependencies

Branch: `ws-a/modeling-foundations`. Scope: core schemas, shared entry points, backend/routers, caller imports, tests, generated contract and `.github/workflows/`.

Implement the decisions above in two reviewable sub-PRs: **S00a** additive contract semantics and fixture validation; **S00b** stable capability/service interfaces and CI. Do not implement new physics. Inventory every direct mock import, including `scenarios.py`, `examples.py`, risk, optimizer and WebSocket code. Existing mocks may remain behind the new interfaces until replaced. Move reusable example/template construction out of mock-only ownership without changing its output.

Acceptance: current example bodies still validate; invalid/conflicting inputs have explicit tests; all existing tests pass; new/old response compatibility is exercised through both services; contract regeneration is deterministic. CI runs locked dependency installation, `make contract-check` and `make test` on PRs into `dev`, without network-dependent fixtures. No claim of OpenAPI fuzzing until that test job actually exists.

### S01 — M2 data qualification and rule inventory

Branch: `ws-a/refdata-qualification`. Scope: `refdata/`, core input schemas, rules metadata and tests.

Validate finite positive dimensions, curve ordering/coverage, unique IDs, fitting/chock references, inventory, fender properties, tug capabilities and depth-profile coverage. Separate schema validity from physical-data confidence. Add per-asset provenance and capability requirements: loading-specific drafts, mooring geometry, contact curves, tug ratings and later dynamic coefficients. Audit every NSTM rule in the registry as implemented, partial or unsupported, with applicability and source references. Do not claim a complete compliance check from the current subset.

Acceptance: missing ratings/fittings or out-of-range curves cannot qualify a real analysis; immutable or defensive-copy catalog access prevents one request mutating another; duplicate IDs and dangling references fail clearly. A synthetic analytical fixture is available for mechanics tests and a separately labeled DDG demonstration fixture for integration. Other classes remain unsupported for capabilities lacking data. No invented fleet-wide fitting layouts or certified tug ratings.

### S02 — Immutable results and actual background work

Branch: `ws-a/modeling-jobs`. Split into **S02a** resolved-input snapshots and persistent results/scenarios, then **S02b** bounded execution and lifecycle. Scope: core stores/jobs, routers, configuration and shared-agent compatibility tests.

Use a small persistent store (SQLite is sufficient for the initial single-host deployment), explicit migrations and immutable result records. Persist the dependency manifest and resolved-input hash. Queue a callable plus frozen inputs; never compute before returning the job acknowledgement. Use bounded CPU workers for CPU-bound work, bounded queue capacity, deadlines and cancellation. Define restart recovery, terminal errors, retention and SSE reconnection behavior. Preserve the existing agents job interface through a tested adapter while migrating its consumers deliberately.

Acceptance: a deliberately blocked computation does not block acknowledgement or unrelated requests; progress follows completed work; cancellation/deadline/shutdown/restart tests cover terminal states; overload has a documented response; result IDs and hashes reproduce after restart; edited catalog records cannot alter old results. No duplicate completion callback on SSE reconnect. Document local single-host limits instead of implying distributed durability.

### S03 — M3 integration, wind basis and validity

Branch: `ws-b/load-validity`. Scope: loads, environment normalization, core metadata and downstream validity plumbing.

Retain reviewed formulas, coefficients, frozen superstructure heights and calibrated seed areas. Define exactly one wind-duration/height conversion boundary using documented source metadata; preserve the existing legacy assumption explicitly when duration is unknown, with limited validity for uses requiring a verified basis. Do not claim a shorter-duration gust is universally conservative for a coupled model. Keep API-to-UFC angle transforms explicit: wind `(180 - relative_from) % 360`; current `(-relative_toward) % 360`.

Classify existing depth/draft, current-speed and low-Reynolds warnings by applicability. A depth at or below draft cannot be a valid floating-mooring result merely because M3 returns finite clamped forces. Preserve diagnostics in all consumers, even when compliance rules are disabled. Aggregates retain affected times/samples/components, not thousands of duplicate findings.

Acceptance: M3 worked examples and all calibration/bearing tests remain passing; each clamp/estimate appears in assumptions and validity; no double normalization; legacy metadata omission is tested; port/starboard and wind/current signs hold; warnings reach analysis, holding, windows and risk interfaces. Benchmark `compute_loads` separately from serialization, retaining the sub-millisecond target on documented hardware.

### S04 — M1 deterministic replay, then real providers

Branch family: `ws-a/environment-*`. Three sub-PRs: **S04a** recorded replay/scenarios and clock injection; **S04b** CO-OPS observations/predictions; **S04c** forecast adapters. Scope: environment, schemas/configuration, scenarios and tests.

Keep scenarios fully deterministic and isolated from live time. Verify provider station coverage, current bins, datum, measurement averaging and forecast issue/valid times before normalization. Reporting interval does not establish wind averaging duration. The [CO-OPS API documentation](https://api.tidesandcurrents.noaa.gov/api/prod/) describes observations and predictions, product-specific intervals, required datum and bin parameters; treat these as distinct inputs. Verify station/product availability at implementation time rather than assuming the roadmap's station IDs remain appropriate.

Implement timeouts, retry limits, caching, rate limits and explicit stale/missing-data policies. Do not substitute synthetic data on provider failure. Normalize directions with circular/vector operations and align timestamps without interpolating across unqualified gaps. Forecast selection must avoid future-issued data in historical replay. Add NWS/CBOFS only with documented spatial/depth sampling, datum and forecast coverage; unavailable forecast components remain unavailable.

Acceptance: recorded fixtures cover normal response, missing fields, bad quality, outage, stale cache, 359°/1° interpolation, non-UTC input, datum mismatch, duplicate/out-of-order timestamps and partial horizon coverage. Replay is identical across clocks and machines. Endpoint/WS consumers use the stable service interface. Separate opt-in provider smoke checks from CI.

### S05 — Shared mechanical components

Branch: `ws-b/mooring-mechanics`. Scope: new `mooring/mechanics/`, core geometry/schema extensions and tests.

Implement rigid-body surge/sway/yaw geometry, tension-only nonlinear line curves, installed rest lengths, explicit pretension/slack initialization, supported multi-part arrangements, chock routing and vector fitting reactions. Implement fender gaps, unilateral contact, force/deflection curves and energy integration. Reject unsupported reeving/friction rather than pretending every arrangement multiplies force identically. Preserve berth/ship frame and side-to transformations and account for water level/loading consistently.

Acceptance: analytical force and moment tests use fixed synthetic geometry; rigid transforms and mirror symmetry hold; slack lines exert zero compression; individual part and fitting reactions match vector balance; nonmonotone/invalid curves are rejected; fenders carry compression only and integrated work matches an independent curve integral. The 50/100 ft line ratio test applies only to identical axial material/area, equal extension and active linear response. Two-versus-three-part comparisons require explicitly identical strain and arrangement assumptions.

### S06 — M4 equilibrium and compliance

Branch: `ws-b/static-equilibrium`. Scope: `moored/solver.py`, shared mechanics, rules integration, backend and tests.

Solve surge, sway and yaw jointly using dimensional force/moment balance. Recompute geometry, contact and heading-dependent loads at the solved pose. Tug inputs contribute their actual force vectors and moments. Warm starts are an optimization, never a substitute for convergence checks. Separate solver validity, physical capacity checks and NSTM applicability so disabling rules cannot disable numerical or load-model validity.

A least-squares termination flag alone is insufficient: [SciPy documents](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html) termination based on cost, step or gradient criteria. Independently evaluate the physical residual, support rank and active bounds. Initial numerical acceptance defaults: each force residual at most `max(1 lbf, 1e-6 * force_scale)` and moment residual at most `max(1 ft·lbf, 1e-6 * force_scale * reference_length_ft)`. Define scales from applied/restoring loads with nonzero floors; these are numerical tolerances, not Navy safety limits. Report them and verify sensitivity.

Acceptance: independent one-line/paired-line analytical fixtures, symmetric and asymmetric yaw balance, unloaded/slack/underconstrained systems, on-pier fender contact, multiple fittings, opposing tug forces, high loads, no equilibrium within bounds and bad initial guesses. A local nonconverged solution never becomes GREEN or a proof of global infeasibility. Check stability/local restoring behavior and report unsupported equilibria. Benchmark p50/p95 solve time and failure rate on representative configurations; the 50 ms target is provisional until measured.

### S07 — M4 limiting wind and tending

Branch: `ws-b/envelopes-tides`. Scope: moored solver services, schemas, tests.

For each bearing, retain specified current, water level, tug configuration and wind basis. Evaluate actual equilibrium and all line/fitting/fender/validity limits. Return the first limiting threshold from the initial operating state, including failure at zero wind, no failure within search range and invalid/undetermined points as distinct outcomes. Sample/bracket transitions and test monotonicity before using bisection; do not infer the limit from one force scaling calculation.

For tide sweeps, preserve installed rest lengths and configuration across time. A tending action explicitly changes length/pretension; never silently retension each snapshot. Determine warning/action times with documented time resolution and cover extremes between coarse samples.

Acceptance: zero-wind overload, sustained current, active-set change, fender limit, unbounded search range, failed intermediate solve and narrow failure interval fixtures; tide cycle without tending returns the same state at the same water level. Report sampling/refinement tolerances and unsupported gaps. No freeboard/datum ambiguity hidden in fitting heights.

### S08 — M6 shared tug allocation and static berthing

Branch: `ws-c/tug-allocation`. Scope: shared `tugs/`, berthing tug service, schemas/tests.

Allocate the full surge/sway/yaw wrench subject to per-tug rated capability, allowed force direction, push/pull/standby mode, attachment location, hull contact limits and assignment uniqueness. Keep certified bollard pull distinct from estimated horsepower conversions; state efficiency/availability assumptions and sources. Preserve a compatibility wrapper for existing `size_tugs` callers. Do not label aggregate lateral capacity as feasible when yaw or point limits fail.

Acceptance: analytically solvable two-point cases; adequate total force but inadequate moment; fore/aft asymmetry; unavailable tug, duplicate allocation, direction constraints, hull limit and unsupported rating. Report residual wrench and binding constraints. Static berthing results require qualified inputs and propagated M3 findings.

### S09 — M6 assisted holding and windows

Branch: `ws-c/holding-windows`. Scope: moored holding service, berthing windows, shared allocator/tests.

Iterate allocation with the real equilibrium solver and re-solve the assisted plan. Size against line/fitting/fender constraints and position, not a scalar sum of overloads. Evaluate berthing windows over the actual forecast with requested fleet, full wrench feasibility, current/gust limits, data coverage and validity. Explicitly define endpoint inclusivity, minimum usable duration and temporal refinement.

Acceptance: adding a tug that fixes sway but worsens yaw is caught; insufficient fleet remains infeasible; all reported assisted utilizations come from a fresh solve; forecast gaps do not become safe windows; threshold crossings and short windows between coarse samples are resolved or bounded. Keep a deterministic 24-hour clock sweep regression for scenario-based berthing tests.

### S10 — Qualified stochastic environmental inputs

Branch: `ws-a/environment-uncertainty`. Scope: environment fitting/sampling tools, small fixtures, model metadata and tests.

Define what is random: observation error, forecast residuals, gust variability, direction/current/tide dependence and temporal correlation. Do not fit forecast error from observations alone. Split fitting and validation data by time/event to avoid leakage; version stations, periods, filters, parameters and applicability. Retain hurricane/storm applicability as an explicit limitation where data do not support it. Commit fetch/fit scripts and compact model artifacts, not bulk history.

Acceptance: deterministic seeded sampling, circular direction handling, valid physical bounds, held-out calibration/coverage diagnostics and a documented minimum-data policy. Synthetic distributions validate algorithms only. Insufficient real data leaves probabilities unqualified; the service may provide deterministic scenarios, clearly identified as such.

### S11 — M5 exceedance, timelines and alerts

Branch family: `ws-c/risk-*`. Split **S11a** instantaneous MC, then **S11b** time-correlated horizon/timeline and alerts. Scope: moored risk, uncertainty interface, jobs, schemas/tests.

Honor requested sample count or reject it explicitly under published budgets; never silently cap it. Record seed, distribution revision, actual samples, failed/invalid samples, confidence intervals and error criterion. Evaluate line and fitting capacity, fenders and equilibrium validity without assigning fictitious MBS values to elements lacking that concept. Define the dynamic factor and its application once; a force multiplier must not accidentally be applied to speed and squared.

Instantaneous probability is not the probability of any failure over 48 hours. Horizon results require correlated trajectories and an explicit event definition. If the temporal model is unavailable, return pointwise results with an unsupported horizon finding; do not sum/max them into a claimed horizon probability. Unknown sampled outcomes require bounds or an invalid/limited estimate, never exclusion from the denominator without disclosure.

Acceptance: analytical distribution cases with known exceedance probability, zero and all exceedance with confidence bounds, quantile coverage tests, reproducible seeds, invalid sample accounting, nonindependent trajectories, stale inputs and empty configurations. Replace the old universal “p95 within 2% at N=2,000” claim with statistical accuracy criteria. Benchmark requested sample counts and full timelines, including queue/serialization; document accuracy versus runtime and cancellation. Alerts identify event time, stale data and probability/model provenance.

### S12 — M7 constrained configuration search

Branch: `ws-d/mooring-search`. Scope: moored optimizer, shared scenario/candidate helpers and tests.

Generate reachable plans respecting inventory/counts, locked lines, fitting/chock compatibility, permitted line types/parts, lead constraints and berth geometry. Evaluate every applicable MST wind/current alternative and the stated forecast planning cases, including tides and assisted conditions. Do not replace a set of MST alternatives with its largest wind value. Use a documented objective only after hard constraints and validity pass; store the actual evaluated candidate/result references.

Acceptance: small exhaustive fixture establishes optimum/feasibility independently; empty inventory, missing compatible fittings, impossible reach, locked infeasible plans, multiple MST alternatives and unsafe forecast peaks are covered. Bounded search returns best found with completeness/budget diagnostics; no candidate found under a budget is not proven infeasible. Do not manufacture a GREEN candidate. Real M5 risk may rank candidates only within its qualified domain.

### S13 — M7 sequence feasibility and review state

Branch: `ws-d/mooring-sequence`. Scope: berthing sequence, shared mechanical evaluators/interfaces and tests.

Represent actions and dependencies, crew/tug resources, safe leads, line handling constraints and intermediate holding conditions. Validate referenced tug/result IDs and their scenario provenance. Use the shared evaluator needed for intermediate states without importing the moored phase. Where static evaluation cannot establish transient safety, flag the limitation for M11. Require sourced NSTM rules and subject-matter review for operational sequences; generated output remains a draft until that review.

Acceptance: missing/invalid tug reference, conflicting actions, insufficient crews, cyclic dependencies, unsafe intermediate state, unavailable line and invalid final plan. A valid final equilibrium alone does not validate the sequence. Explicit timing assumptions and review status survive the API response and safety-sheet handoff.

### S14 — Phase 1 integration gate

Branch: `ws-b/phase-one-validation`. Scope: integration fixtures, modeling compatibility fixes, evidence and documentation; coordinate agent/UI consumers through their APIs.

Demonstrate qualified analytical cases and the labeled DDG/mock-pier scenario through environment → loads → equilibrium → risk → assistance → optimization → sequence. Include a supported safe case, overload/infeasible case, invalid-data case and timeout/undetermined case. Verify every downstream number resolves to immutable inputs/results and warnings survive the chain. No requirement to force a GREEN result or auto-approve a safety sheet.

Acceptance: `make contract` and `make test` pass; packet evidence and performance budgets are recorded; a qualified deck officer/harbor pilot reviews sequence rules and representative outputs, with unresolved findings recorded. This enables a **demonstration within documented assumptions**, not unrestricted operational use. The UI/agent must distinguish mock data, estimates, limited validity and human approval.

### S15 — M11 dynamics inputs and free-motion integration

Branch: `ws-e/berthing-dynamics`. Scope: shared mechanics/hydrodynamics, dynamic schemas/refdata and berthing integrator/tests.

Qualify mass/inertia, added mass, damping and maneuvering coefficients for the modeled vessel, speed/depth domain and units. A generic frigate/tanker model is an explicitly unvalidated surrogate until benchmarked; do not transfer it to every class by displacement alone. Define body/inertial frames and velocity-relative water/air loads, and account for current consistently without double-counting drag. Static M3 calibration is not a maneuvering derivative model.

Acceptance: zero-input rest, constant-force acceleration, free decay, pure yaw, frame rotation, symmetry and energy checks with independent expected solutions; valid mass matrix and passive damping; timestep refinement and tolerance evidence. Benchmark coefficients against accessible primary references or qualified test data. Missing coefficients block vessel qualification, not the synthetic integrator tests.

### S16 — M11 contact, line activation and batch simulation

Branch: `ws-e/berthing-contact`. Scope: shared mechanics and berthing simulator, jobs/results/tests.

Integrate unilateral fender contact, contact energy, line attachment/slack take-up, tug forces and sequence events. Resolve event times and restrict steps near contact; output sampling rate is independent of integration timestep. Define failure/overload behavior without assuming an unvalidated rupture law. Avoid arbitrary energy factors or treating quasi-static line stiffness as a validated snatch model.

Acceptance: analytical spring impact, no tensile fender force, contact/no-contact transitions, line take-up, event-order reproducibility, energy balance and timestep convergence. Reproduce an independently sourced contact benchmark; steady holding agreement with M4/M6 is an additional consistency test, not primary validation. Persist batch frames and diagnostic/validity history with bounded output sizes.

### S17 — M11 interactive simulation and Phase 2 gate

Branch: `ws-e/berthing-interactive`. Scope: simulator session control, WebSockets, schemas/config/tests.

Use one authoritative simulation clock and integrator for batch and interactive modes. Network message frequency must not advance simulation time. Define pause/resume/reset, ordered command timestamps, tug slew/capacity limits, disconnect ownership, session limits and backpressure. Keep controls isolated by session; validate all incoming commands.

Acceptance: replaying the same timed commands gives the same trajectory in batch and WS modes; floods, slow clients, disconnects and reconnects cannot alter physics clock or another session. Phase 2 release requires S15–S16 independent validation and subject-matter review of contact/line assumptions, with explicit supported ship/depth/speed limits.

### S18 — M12 real routes, coverage and UKC

Branch family: `ws-e/approach-data-*`. Split **S18a** chart/depth/coordinate ingestion, then **S18b** route/UKC/tidal-window evaluation. Scope: approach planning, shared geospatial utilities, schemas and tests.

Require official chart/source edition and coverage metadata, horizontal/vertical datums and transformations. Validate the full swept vessel corridor, not only waypoint depths. Handle land, missing cells, depth uncertainty, route width, vessel dimensions and chart updates explicitly. Do not assume every depth and tide is MLLW. Keep synthetic routes/depths strictly in fixtures.

Compute time at each segment from the speed schedule; distinguish through-water from over-ground speed. Include controlling draft/trim, validated squat formulation and applicable margins. Source the squat formula and channel/blockage domain before implementation; mean draft alone is not a general UKC criterion. Search departure windows against the full transit and actual tide/current coverage. Routing, traffic restrictions, tug rendezvous and abort-point recommendations need their own sourced inputs; unsupported features must be labeled rather than invented.

Acceptance: shallow patch between deep endpoints, swept-width obstruction, mixed datum, missing coverage, maximum-draft case, speed change, zero-speed/invalid schedule, tide crossing during transit and no feasible departure. Independent UKC hand calculations and spatial interpolation fixtures are mandatory. Route evaluation may be real before automatic route finding; keep capability statuses separate.

### S19 — M12 maneuvering and Phase 3 gate

Branch: `ws-e/approach-dynamics`. Scope: approach simulator using shared qualified dynamics, route coupling and tests.

Add validated propulsion/rudder/control behavior for approach speeds and current/wind coupling. Do not reuse a low-speed berthing model outside its domain without new evidence. Track the vessel through the chart corridor with time-varying UKC and abort/limit diagnostics. Cross-track error must be computed from the simulated path, not a prescribed sine curve.

Acceptance: independent turning/straight-running/maneuvering benchmarks for the supported vessel/model, current-set tests, timestep convergence, corridor/UKC violations and deterministic command replay. Phase 3 requires qualified bathymetry, hydrodynamic inputs and review by a qualified navigation subject-matter expert. Missing evidence keeps the affected capability experimental even if the software runs.

### S20 — M13 validated telemetry and arbitration

Branch family: `ws-a/telemetry-*`. Split **S20a** supported protocol decoders and quality; **S20b** source arbitration and live integration. Scope: telemetry, environmental input boundary, schemas/config/tests.

Declare exactly which NMEA/AIS/load-cell messages and transport encodings are supported; do not promise complete NMEA 2000 or every AIS sentence. Verify applicable protocol references. Validate checksums/framing, identity, sensor/channel, event/receipt timestamps, units, calibration revision, bounds and out-of-order behavior. Store independent sensor channels without overwriting unrelated lines. Apparent-to-true wind requires synchronized vessel motion and heading data, with explicit frames.

Implement stale-data, conflict and source-priority policy; a sensor never silently overrides a qualified forecast or verified manual/scenario input. Add authenticated ingest, message-size/rate limits and bounded storage before connecting real feeds. Read-only sensor inputs must not become vessel control outputs.

Acceptance: captured/synthetic protocol fixtures, bad checksum, swapped units, duplicate/replayed/out-of-order messages, wrong vessel/sensor, stale calibration, multiple load cells, apparent-wind conversion and conflicting sources. Every adopted observation retains provenance and quality; rejected input cannot influence a result. Live mode requires S21 controls for the deployment involved.

### S21 — Deployment and live-use readiness

Branch: `ws-a/modeling-readiness`. Scope: configuration, operational documentation, observability, integration/load tests and targeted fixes.

Before exposing jobs, simulation controls or telemetry beyond the local demo, enforce authentication/authorization, request/resource limits and separation of user/session data. Exercise storage migrations, backup/restore, cleanup and restart recovery. Log result/job IDs and validity failures, with metrics for provider freshness, solver failures, queue saturation, cancellation and runtime. Set explicit deployment-specific concurrency, retention and forecast-age limits from measured workloads.

Acceptance: concurrent requests cannot mutate shared reference data; unauthorized sessions cannot read/control another run; overload is bounded; slow providers and interrupted jobs recover predictably; restoration preserves result provenance. Publish a supported-capabilities matrix by ship, loading, environment, data quality and phase. Obtain accountable human acceptance for intended live use; neither passing tests nor a real-backend label supplies that acceptance.

## Completion ledger and handoff

Review baseline: `make test` passed **270 tests**; local documentation links and packet numbering were checked. This is existing-suite evidence, not validation of the unimplemented capabilities.

All packets above are **pending** at this review baseline. M3 formulas/calibration and the existing rule/geometry implementations are already present, but that does not complete S03, S05 or S06. Track each packet here with merged PR/commit, commands/counts, benchmark artifact and unresolved limitations. Do not mark completion based solely on backend registration.

Copy this instruction to an execution agent after this documentation PR is merged:

> Read README.md, CONTRIBUTING.md, contract/README.md, modeling/README.md and docs/MODELING_EXECUTION_PLAN.md. Start from latest dev. Implement S00a only on ws-a/modeling-foundations-contract, preserving existing behavior except the explicitly specified validity/input-validation changes. First inspect the schemas and consumers, then implement the additive semantics and deterministic tests required by S00. Do not implement new physics or subsequent packets. Run make contract and make test, commit generated contract changes, and open one PR into dev without merging. Include compatibility evidence and any source/input blockers. After that PR merges, proceed to S00b as a separate task.

If using this plan before merge, read it on `docs/remaining-modeling-plan`; implementation still branches from the agreed integration base, not from an unrelated feature branch. Do not start dependent packets against unmerged contract decisions.
