# Modeling and agents — overnight 4–5 November 2026

## Log

- 21:11 EST: DC0 provider branch merged locally; fixed cache age after retry/backoff, age-bounded breaker fallback, shared-client serialization and invalid policy settings. No peer branch/worktree altered. Source/provider adapters remain data-team-owned.

- 21:08 EST: direct static tug assistance now invalidates unknown/duplicate/overrated assignments; invalid assistance produces no numeric wind limit, and tug records enter result manifests. Tide sweep accepts supplied water-level snapshots, evaluates their knots, and isolates/labels its legacy training fallback. Source and interpolation remain explicitly limited.

- 21:00 EST: auth packet PR #32 published, 1189 tests pass. Job client now enforces elapsed-time deadlines including submission/poll HTTP, handles cancelled remote jobs immediately, cancels accepted remote work on caller stop, and refuses untrusted status paths before forwarding credentials.

- 20:55 EST: agents auth integration implemented: caller credentials forwarded to modeling through worker context; plans/reports/reviews/sheets/vision jobs/ledger owner-scoped, body and per-principal rate caps. Authenticated real chain and adversarial cross-owner attempts pass. Shared confirmed berth catalog and unverified approval roles remain deployment blockers.

- 20:51 EST: integrated colleague branch ws-a/dc8-data-requests into the modeling branch, retaining its detailed asset/sensor inventory and adding our procedure, forecast-basis, propulsion and abort/replan requirements. Provider plumbing branch remains pending the stale-age review request. Jobs packet: 1179 Python and 81 UI tests pass.

- 20:48 EST: provider/intake PR #30 published with 1175 passing tests. Real agent task queue and live planner events implemented; 64 focused tests pass including gated work, saturation, cancellation, failure, and SSE resume. Persistence/authentication still separate work, not claimed.

- 20:43 EST: vision PR #29 CI green and merged. Intake now refuses to extrapolate ramp/replay snapshots as steady; missing scenario-series capability is explicit. Partial/malformed forecast coverage and future-sample quality flags propagate into safety findings. 204 focused tests pass.

- 20:41 EST: M4 PR #29 published, 1148 Python tests. M5 Anthropic Messages adapter implemented with official current protocol, explicit model/key, no network in tests, existing application guards unchanged. Full suite 1165 passed; contract-check clean; 177 provider/agent focused checks passed. Provider perception/narration quality remains unverified.

- 20:40 EST: safety PR #28 merged after green CI (1136 Python tests). Vision metadata/optional image pipeline implemented: modeling owns projection and estimated catalog capacities; confirmation uses logged toolkit and cannot replace catalog ids or promote provenance. Full suite 1147 passed before one additional confirmation regression; frontend 81 passed, typecheck/lint/build green.

- 20:30 EST: Safety basis corrections targeted 40 tests passed, including real supported demo through sheet. Explicit modeled gust limits replace mislabeled sustained limits; unsupported breaking-speed estimates removed (prior test expectation corrected accordingly). Sheet now carries validity and real source/forecast statements. OpenAI Docs skill applied to optional vision input adapter; claude-api and openai-platform-api-key skills not installed, so provider documentation will be checked directly; no live LLM dependency.

- 20:27 EST: PR #26 merged after both CI jobs passed. F24 full suite 1131 passed; frontend typecheck/lint/81 tests/build passed. No skips/xfails.

- 20:26 EST: public NWS grid AKQ/88,56 and hourly forecast downloaded (issue 23:38:07Z), plus 48h CO-OPS tide predictions. Temporary raw/provenance files only in /tmp/psp-public-data. M7 data-request inventory written. Found further safety basis defect: limiting wind is sustained but was labeled gust; breaking-speed square-root estimate also applied to fenders. Correcting via modeling-owned explicit gust limits, no fabricated breaking threshold.

- 20:22 EST: M0 PR #25 merged green. M1+M2+intake/safety fixes full suite 1121 passed. Supported scenario traversed real HTTP intake/planner/safety in 3.34s: plan AMBER, review ready_for_signature with AMBER validity floor. UI generated-type check exposed scalar-default requiredness; changed new design_basis to optional null (absent keeps MST+forecast), preserving callers.

- 20:17 EST: baseline 1108 Python tests, contract-check, frontend typecheck/lint/81 tests/build passed. Branch watcher /tmp/psp-modeling-watch.py polls every 5m until 08:00 EST; snapshots/inbox copies in /tmp/psp-watch-*. M1 tests verify all four actual outcomes.

- 20:12 EST: started from origin/dev 191a41a in ../psp-agents, agents/overnight. Main contains the same release plus its release merge. Read shared instructions and ownership. Baseline suite running.
- UI audit: planner bypasses explicit intake; sheet creation bypasses explicit safety-review selection; target defaults to 70%. Forecast risk requests 24h but saved scenarios freeze weather. Recommendation includes MST design cases regardless of moderate forecast.

## Decisions

- Integrate green PRs into dev; leave main and colleagues’ worktrees alone.
- Deliver demonstration within assumptions; seed data and unreviewed sequence rules prevent operational qualification.
- Expanded plan: [MODELING_OVERNIGHT_PLAN.md](../MODELING_OVERNIGHT_PLAN.md).

## Interfaces

- Vision: same upload/job/confirm endpoints, now real deterministic catalog drafts by metadata berth_id; no-LLM path does not claim image extraction. Optional image proposals require scale plus pier_face_start_px/end_px. POST /berth-drafts computes unsaved geometry; confirmed berths are registered via toolkit POST /berths. Drafts stay estimated/unqualified.

- F24: POST /mooring/forecast-plan (job → ForecastDockingResponse) and POST /data-simulation/forecast (ForecastSeries). Documentation docs/FORECAST_DOCKING.md; full request fixtures in contract/examples/modeling. Ten new tests cover coverage, interior peak, issue-time leakage, cancellation/budget and real API jobs.

- /mooring/recommend additive design_basis=forecast_only requires forecast_env; absent retains MST checks. Optional tugs and standoff_ft preserve assisted geometry. Candidate.tugs identifies assistance actually evaluated. Actual forecast tides retained. New forecast docking endpoint in progress.

- M1: GET /api/v1/demo/docking-cases returns four typed request bundles (ddg-supported-limited, ddg-overloaded, ddg-invalid-data, ddg-undetermined). POST environment_request to /env/scenarios, substitute returned id into scenario_request.env_source.env_scenario_id, then POST /scenarios. Direct analysis_request and optional envelope_request reproduce the named outcomes. Contract examples demo_ddg-*.json are generated.

- /intake/reports supports horizon_hours 1–120 (24 default); pass intake_report_id to /agent/plans to preserve forecast conditions.
- /mooring/recommend checks MST alternatives plus forecast_env; failed bounded search is not proof of infeasibility.
- Additive forecast-planning contract to follow; agent C owns NOAA acquisition.

## Requests

## Tomorrow

- Qualified vessel/pier data and pilot/deck-officer review remain prerequisites for live use.

## REVIEW_NEEDED

NSTM references, line/pier capacities, wind averaging conversions, tug estimates, sequence durations and intermediate handling assumptions.
