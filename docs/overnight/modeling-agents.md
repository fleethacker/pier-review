# Modeling and agents — overnight 4–5 November 2026

## Log

- 20:12 EST: started from origin/dev 191a41a in ../psp-agents, agents/overnight. Main contains the same release plus its release merge. Read shared instructions and ownership. Baseline suite running.
- UI audit: planner bypasses explicit intake; sheet creation bypasses explicit safety-review selection; target defaults to 70%. Forecast risk requests 24h but saved scenarios freeze weather. Recommendation includes MST design cases regardless of moderate forecast.

## Decisions

- Integrate green PRs into dev; leave main and colleagues’ worktrees alone.
- Deliver demonstration within assumptions; seed data and unreviewed sequence rules prevent operational qualification.
- Expanded plan: [MODELING_OVERNIGHT_PLAN.md](../MODELING_OVERNIGHT_PLAN.md).

## Interfaces

- /intake/reports supports horizon_hours 1–120 (24 default); pass intake_report_id to /agent/plans to preserve forecast conditions.
- /mooring/recommend checks MST alternatives plus forecast_env; failed bounded search is not proof of infeasibility.
- Additive forecast-planning contract to follow; agent C owns NOAA acquisition.

## Requests

## Tomorrow

- Qualified vessel/pier data and pilot/deck-officer review remain prerequisites for live use.

## REVIEW_NEEDED

NSTM references, line/pier capacities, wind averaging conversions, tug estimates, sequence durations and intermediate handling assumptions.
