# Modeling and agents — overnight 4–5 November 2026

## Log

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
