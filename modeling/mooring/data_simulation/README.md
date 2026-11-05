# Training forcing adapters

These modules generate or adapt **synthetic training inputs**, not public forecasts. They are reusable by a future scenario editor; they never replace an unavailable provider automatically.

| Module | Entry point | Purpose |
| --- | --- | --- |
| `forecast.py` | `generate(SyntheticForecastRequest)` | Seeded gust pulse/noise and optional water-level oscillation about an explicit baseline. Published by `POST /data-simulation/forecast`. |
| `examples.py` | generated contract examples | Reproducible input fixtures for the forecast-planning consumer. |
| `legacy_forecast.py` | `generate(...)` | Compatibility adapter for the offline environment provider. Explicit clock, supplied legacy snapshot factory, source `mock`, scenario basis; includes coverage through now plus the requested horizon. |
| `tides.py` | `legacy_tide_levels(berth, times)` | Explicitly synthetic tide sweep when no water-level series is supplied. |
| `timeline.py` | `sample(at, stations)` | Explicitly synthetic risk-timeline forcing when no forecast is supplied. |

The seeded generator preserves the baseline sustained wind, directions and current, then varies only the documented controls. Its periods, amplitudes and noise are scenario inputs, not fitted weather/ocean coefficients. Keep the exact request, seed and UTC anchor to reproduce a run. Legacy adapters retain existing fixture curves; their station labels identify the configured demo location, not measurements from those stations.

For a UI, separate training from public/replayed data. Preview the generated forcing, preserve its labels through analysis and reports, and show gaps/failures without filling them. `POST /mooring/forecast-plan` can compare arrivals at least 24 hours ahead using the generated series, but a supported static training result does not approve an actual docking or line-handling procedure. See `docs/FORECAST_DOCKING.md` and `docs/MODELING_UI_RECOMMENDATIONS.md` at the repository root.
