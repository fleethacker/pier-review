# Modeling and agents — overnight 4–5 November 2026

## Log

- 20:22 EST: M0 PR #25 merged green. M1+M2+intake/safety fixes full suite 1121 passed. Supported scenario traversed real HTTP intake/planner/safety in 3.34s: plan AMBER, review ready_for_signature with AMBER validity floor. UI generated-type check exposed scalar-default requiredness; changed new design_basis to optional null (absent keeps MST+forecast), preserving callers.

- 20:17 EST: baseline 1108 Python tests, contract-check, frontend typecheck/lint/81 tests/build passed. Branch watcher /tmp/psp-modeling-watch.py polls every 5m until 08:00 EST; snapshots/inbox copies in /tmp/psp-watch-*. M1 tests verify all four actual outcomes.

- 20:12 EST: started from origin/dev 191a41a in ../psp-agents, agents/overnight. Main contains the same release plus its release merge. Read shared instructions and ownership. Baseline suite running.
- UI audit: planner bypasses explicit intake; sheet creation bypasses explicit safety-review selection; target defaults to 70%. Forecast risk requests 24h but saved scenarios freeze weather. Recommendation includes MST design cases regardless of moderate forecast.

## Decisions

- Integrate green PRs into dev; leave main and colleagues’ worktrees alone.
- Deliver demonstration within assumptions; seed data and unreviewed sequence rules prevent operational qualification.
- Expanded plan: [MODELING_OVERNIGHT_PLAN.md](../MODELING_OVERNIGHT_PLAN.md).

## Interfaces

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
