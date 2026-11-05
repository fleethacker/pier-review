# Advance docking planning

`POST /api/v1/mooring/forecast-plan` returns a job; its result is `ForecastDockingResponse`. Use `contract/examples/modeling/mooring_forecast_plan.json` for a complete, explicitly synthetic 48-hour example. Arrival must be at least 24 hours after `as_of_utc`; docking and holding must end within 120 hours.

The caller supplies an ordered, timezone-aware forecast. Agent C owns `/env/forecast` and public-provider normalization. The modeling endpoint does not fetch the network: it evaluates the supplied snapshots and retains their source, issue and valid times. Submit forecast data issued no later than planning time. An observation in the future, missing/stale component flag, or uncovered interval is unavailable, not zero. Forecasts with unknown averaging metadata remain limited under the loads model.

For each candidate arrival, line installation lengths use that arrival's tide and stay fixed through docking and holding. All supplied snapshots within the interval, including interior peaks, are evaluated. For coverage between snapshots the forcing is held piecewise constant up to `max_gap_min`; peaks between samples remain unresolved. The end must lie within actual supplied coverage. A budget-exhausted or unconverged interval is undetermined. Every computed condition cites its immutable analysis result; the aggregate manifest records request/config and result references.

`optimize_lines=true` searches a common configuration across the relevant forecast conditions with a separate bounded `search_budget`. This is forecast-only planning, not MST design-condition compliance. Fixed tug assignments are checked against catalog/push-point capacities and are required throughout the operation. Arrival alternatives can be rejected even when one is supported. No arrival is selected unless its entire docking and holding interval meets the requested utilization target and has admissible computed inputs. All aggregate results remain limited because static, sampled conditions do not validate maneuvering/contact or line-handling safety.

The endpoint supplies line placements and holding assessments. Generate and independently review a draft sequence using the existing sequence/planner/safety APIs; a selected arrival does not approve the sequence. Qualified UKC, bathymetry, dynamic vessel response, wake, traffic, tug availability and deck-officer/pilot acceptance remain separate requirements. Recheck after new forecasts, changed arrival/assets or observed deviations; do not transfer an approval to changed inputs.

## Training and temporary public data

`POST /api/v1/data-simulation/forecast` generates labeled synthetic training series. Implementation and reusable examples live in `modeling/mooring/data_simulation/`. The request fixes seed, UTC anchor, baseline, triangular gust peak/noise and optional water-level oscillation. These are scenario controls, not fitted meteorological/tidal coefficients. Results say `source=scenario`, `basis=scenario`, and `not_a_forecast`; no generator is an automatic NOAA fallback.

Opt-in public checks on 4 November evening successfully fetched NWS `/points/36.959,-76.33` and 48 hours of CO-OPS MLLW tide predictions for 8638610 into `/tmp/psp-public-data/`, with retrieval URLs/times. Files are temporary and not part of tests or committed fixtures. Provider implementation stays with agent C. Source references: [NWS API](https://www.weather.gov/documentation/services-web-api), [CO-OPS API](https://api.tidesandcurrents.noaa.gov/api/prod/).

## Tide-dependent tending checks

`POST /mooring/tide-sweep` accepts optional `water_level_forecast`: a list of supplied
`EnvironmentSnapshot` records covering the whole requested interval. Only their MLLW water levels vary;
wind/current remain fixed at the main request. Supplied levels are linearly interpolated with a maximum
60-minute gap, and each forecast knot is evaluated so an interior peak is not lost between report times.
Interpolation and spatial representativeness remain unqualified. Missing/poor/stale source data or incomplete
coverage returns 422; it never falls back to synthetic values.

Omitting the series explicitly uses the legacy training tide, now isolated in `mooring/data_simulation/tides.py`
and labeled `SYNTHETIC_TIDE_SERIES` in validity. It can never establish a qualified GREEN result. Sweeps require
timezone-aware, increasing bounds, at most 120 hours, and include the final partial reporting interval. Tending
actions must fall within the window; actions that produce a nonpositive rest length are rejected. Tending
recommendations remain advisory and unreviewed.

Forecast provenance gates also reject poor/suspect quality, future observations disguised as forecasts, missing public
forecast issue time/prediction basis, snapshots before their declared interval, and holding a snapshot past its declared
validity end. Short operations may fit within a short declared interval; extending the holding duration requires actual
coverage. These gates apply before a window is called supported; unavailable data is never replaced by a calm value.

## Reusing a selected installation

When an arrival is supported, `selected_config` resolves each line's modeled `paid_out_unstretched_length_ft` and wet/dry condition, and `installed_at_water_level_mllw_ft` identifies its installation tide. The original common `config` remains available for comparing arrival alternatives; each evaluated condition/window also carries its installation tide. No selected configuration is published when no supported arrival exists.

Use `selected_config` for a later static recheck so a changed tide does not silently reinstall/retension every line. Preserve these fields when applying the plan in the UI. The modeled unstretched span is a reproducibility input, **not a rope-cutting length or deck-handling instruction**; actual measurements, reeving and handling procedure require qualified review. The resolved configuration and installation level are retained in the result manifest.

## Supplied-series risk timeline

`POST /risk/timeline` accepts optional `forecast` snapshots and an explicit timezone-aware `start_utc`. Supply both exact horizon endpoints, strictly increasing timestamps and no gap over 60 minutes. Every supplied knot in the horizon is assessed, even an interior peak between the legacy `step_min` report times. There is no interpolation, extrapolation or automatic provider fallback. This is a conditional timeline, not an as-of forecast qualification; use `/mooring/forecast-plan` for advance-arrival/issue-time gates.

Each step carries the exact environment, validity and (when sampling is requested) successful/failed counts and probability bounds. Invalid source data or all-failed sampling is RED/invalid and has no usable probability. Installations stay fixed at the main request's water level unless paid-out lengths are supplied. The manifest retains all forcing snapshots. Without `forecast`, `forcing_source=synthetic_training`, source scenario and `SYNTHETIC_TIMELINE` explicitly identify training data, even if a public provider is configured. Its adapter lives in `mooring/data_simulation/timeline.py`; changing providers never turns that legacy generator into a forecast.
