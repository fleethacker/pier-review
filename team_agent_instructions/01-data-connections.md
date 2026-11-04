# Team agent instructions 01: data connections

Audience: any agent or engineer assigned a data-connection work item. Written 4 November 2026 against `dev` at `ddcf97d`.

**Goal.** Every external input the modeling service needs (wind, gusts, current, water level, forecasts, waves and swell, charts, ship sensors, tug positions, reference data) reaches the service through a real, tested provider adapter that fills `EnvironmentSnapshot` and its metadata honestly. Today **none** of these connections exist: `modeling/mooring/environment/mock.py` and `telemetry/mock.py` are synthetic, and `modeling/pyproject.toml` has no HTTP, netCDF or GIS dependency.

This file adds work items. It does **not** replace [docs/MODELING_EXECUTION_PLAN.md](../docs/MODELING_EXECUTION_PLAN.md), which stays the implementation authority. Where an item below maps to a packet there (S01, S04, S10, S18, S20), the packet's scope and acceptance text still apply and wins on any conflict. Items marked **NEW** are not in that plan yet.

## Before you start (every item)

1. Read `README.md`, `CONTRIBUTING.md`, `contract/README.md`, `modeling/README.md`, `docs/CONTRACT_SEMANTICS.md`, `docs/MODELING_EXECUTION_PLAN.md` (especially "Rules that apply to every packet") and `docs/PLAN.md` section M1.
2. **Other agents are working in this repo.** Never edit another agent's worktree or branch, never touch files outside your item's scope, never force-push, never push to `dev` or `main`. Branch from latest `origin/dev`, open a PR into `dev`, and do not merge it yourself.
3. **Claim your item** so two agents do not build the same thing: run `git fetch` and `gh pr list --state all` and check remote branches for your item ID (for example `dc1`) or its packet number. If someone already has it, pick another or ask the human. Name your branch `<area>/<item-id>-<short-name>` (area from CONTRIBUTING, usually `ws-a`), and put the item ID in the PR title.
4. Do not start an item until its dependencies have merged into `dev`. If a dependency is open, say so and stop or take another item.

## Rules specific to data connections

- **Never fabricate data on failure.** On provider outage, missing fields, bad quality flags or stale data, return an explicit unavailable/limited result with reason codes. Do not substitute synthetic values (execution plan S04).
- **Metadata is mandatory.** Every adapter fills `EnvironmentMetadata`: basis, source, issue and valid times, wind averaging and gust duration, reference height, current depth/bin, vertical datum, quality, age, and the provider's original values. Reporting interval is **not** averaging duration; if the provider does not document averaging, leave it unset (legacy limited-validity rule), never infer it.
- **One conversion boundary.** Wind-duration/height conversion happens once (S03). Adapters normalize units, time zones, datums and circular directions and nothing else. Directions use vector/circular math (359°/1° must average to about 0°). Wind is "from", current is "toward".
- **Tests never touch the network.** Use small, legally shareable recorded fixtures plus an injected clock. Live checks are a separate opt-in smoke test (for example `make smoke-live`, skipped unless an env variable is set) and are never part of CI.
- **Be a good API citizen.** Explicit timeouts, bounded retries with backoff, a response cache with TTLs, rate limiting, a descriptive User-Agent that is a generic client name (not a personal email), and a circuit breaker so a slow provider cannot stall the service.
- **Verify, don't trust, the station list.** The IDs below came from the roadmap. Confirm at implementation time that each station and product exists, what it measures, its bins, datum and sample interval, and record the check in the PR. If an ID is wrong or retired, stop, report, and propose the replacement; do not silently swap it.
- **Credentials and licensing.** No secrets in the repo. Record each provider's terms and attribution requirement in the PR. Do not commit bulk downloads or restricted documents.
- **Interfaces.** Implement behind the stable service interface introduced by S00b (`modeling_api/backend.py` and the package entry point). Remove production imports of `environment/mock.py` only after searching all callers, examples, jobs and WebSocket code (`ws.py` currently builds snapshots from the mock).
- Run `make contract` and `make test`. Report counts, skips and reasons. Schema changes are additive and regenerate `contract/`.

## Work items

Dependency notation uses packet numbers from the execution plan.

### DC0 — Provider plumbing and recorded fixtures (S04a groundwork)

Depends on S02 and S03 merged. Scope: provider interface, HTTP client wrapper (add `httpx`), retry/cache/rate-limit/circuit-breaker policy, clock injection, fixture recorder script and directory convention, opt-in live-smoke harness, configuration (provider enable flags and base URLs).

Acceptance: a fake provider and a fixture-backed provider both pass the same interface tests; timeout, retry exhaustion, cache hit/expiry and breaker open/close are tested with the injected clock; replay across clocks and machines is byte-identical. Every later DC item builds on this; do not start DC1–DC3 until it merges unless the human says otherwise.

### DC1 — NOAA CO-OPS observations and predictions (S04b)

Depends on DC0. Candidate stations (verify first): `8638614` Willoughby Degaussing (wind, gust), `cb0402` Naval Station Norfolk LB 7 PORTS (current, current predictions), `8638610` Sewells Point (water level, tide predictions). Use the [CO-OPS data API](https://api.tidesandcurrents.noaa.gov/api/prod/); treat observations and predictions as distinct products with their own interval, datum (`MLLW`) and bin parameters.

Deliver: observation and prediction adapters, quality-flag mapping, stale-data policy, current-bin and depth handling, history retrieval for replay, and `GET /env/now`, `/env/history` and `WS /ws/env` live/replay modes served from providers instead of the mock.

Acceptance (S04 fixtures): normal response, missing fields, bad quality, outage, stale cache, 359°/1°, non-UTC input, datum mismatch, duplicate and out-of-order timestamps, partial coverage.

### DC2 — NWS wind forecast (S04c)

Depends on DC0. Gridpoint forecast for the berth location. Document forecast issue time versus valid time, the averaging basis of NWS wind and gust values, and spatial resolution. Forecast selection must never use data issued after the replay time. Unavailable components stay unavailable.

### DC3 — CBOFS current and water-level forecast (S04c)

Depends on DC0. Source: NOAA CBOFS model output (THREDDS/netCDF; add `xarray` and `netCDF4`). Document spatial sampling at the berth, model layer/depth used for "current", datum, forecast cycle and horizon. Handle large files with subset requests and caching; commit only tiny fixtures. Compare against CO-OPS predictions at cb0402 and Sewells Point in a recorded test to catch datum or direction-convention errors (current "toward").

### DC4 — Wave and swell source — NEW (decision gate first)

`docs/PLAN.md` currently says waves and swell are out of scope. The human has now asked for swell in the ship-motion simulation, so this item reopens that scope. **Stage 1 is investigation only; do not write an adapter until the human approves the chosen source.**

Stage 1 deliverable (a short markdown note in the PR, no code): candidate sources, verified for the Norfolk/Hampton Roads berths, with what each provides (significant height, peak/mean period, direction, spectrum), update rate, licensing, and how far the measurement is from a sheltered pier. Candidates to evaluate: NDBC buoys near the bay entrance (for example 44099 Cape Henry and 44014 Virginia Beach; verify), a NOAA wave model product (for example WaveWatch III), CBOFS if it provides any wave fields (verify; do not assume), and a local measurement the human may be able to supply. State plainly how swell penetrates (or does not) into the harbor and berth and what transfer assumption would be needed. Recommend one primary and one fallback.

Stage 2 (after approval): adapter filling the new wave fields defined by RM2 (coordinate with that item; this item does not invent the schema), with the same metadata, quality and staleness rules as DC1.

### DC5 — History retrieval and uncertainty-model fitting (S10)

Depends on DC1 and S04 merged. Fetch and fit scripts plus compact model artifacts (gust-factor by direction sector, direction scatter, current residuals observed-minus-predicted at cb0402, plus wave-height residuals if DC4 lands). Split fit and validation data by time/event. Do not fit forecast error from observations alone. State applicability limits (no hurricane claims). Commit scripts and small artifacts, not bulk history. `GET /env/gust-model` serves the fitted model with provenance.

### DC6 — Charts, bathymetry and berth geometry (S18a)

Depends on S01–S04. NOAA ENC (S-57) read with GDAL/Fiona; record chart edition, update number, horizontal and vertical datums and coverage. Validate the whole swept corridor, not waypoints. Also supply berth-area depth profile for the berth model and the berth/pier outline used by the 2D and 3D maps. Keep synthetic routes only in fixtures. Needed for approach (Phase 3) and for realistic pier/water geometry in the maps.

### DC7 — Telemetry decoders and arbitration (S20)

Depends on S02–S04. Declare exactly which NMEA 0183 sentences (for example MWV, HDT, VTG, GGA, DPT), AIS message types and load-cell payloads are supported; verify against the protocol references. Checksums and framing, sensor identity, event versus receipt time, calibration revision, units, bounds, out-of-order handling, independent per-sensor channels, apparent-to-true wind with synchronized heading and motion. Authenticated ingest with size and rate limits before any real feed is connected. A sensor must never silently override a qualified forecast or a verified scenario.

### DC8 — Reference-data qualification and the inputs only humans can supply (S01 plus data requests)

Depends on S00. Two parts:

1. S01 engineering: validation, per-asset capability flags, provenance, defensive copies.
2. A **data request list for the human** (write it as `docs/DATA_REQUESTS.md` in your PR), because these have no public feed and must not be invented: real pier fitting and fender layouts and ratings (NAVFAC berthing plans or an approved vision-confirmed berth), per-class ship fitting positions and loading-condition drafts, line strength and stretch data sheets, real tug fleet ratings (certified bollard pull, propulsion, maximum push points), ship mass/inertia/added-mass/maneuvering coefficients for the motion model (see file 02, RM3 and RM4), and fender force-deflection curves. For each, list what is needed, in what format, which module is blocked without it, and who plausibly holds it.

## Cross-cutting definition of done

- Provider data flows end to end: provider → snapshot with metadata → loads (S03) → whichever consumer, with validity and findings preserved and visible.
- `/health` and `/version` report which providers are live, mock or unavailable, and each snapshot's source and age, so the UI can label data honestly.
- A short `docs/DATA_SOURCES.md` (create on the first merged DC item and extend from there) lists each source, station or endpoint, what it provides, averaging/datum/units, cadence, terms, and known gaps.
- Final report in your PR: scope, commands and counts, fixtures used, verification evidence for each station, remaining limitations.

## Open decisions for the human (agents must ask, not guess)

- Which wave and swell source to adopt (DC4 stage 1 recommends, the human decides).
- Hosting and credentials policy for providers that need keys.
- Whether any real berth plan, tug fleet data or ship coefficients can be supplied (DC8).
- Whether telemetry live mode is in scope for the demo (S20 and S21 gate it).
