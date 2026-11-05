# Data sources

This registry records external inputs, their normalization basis, and known
gaps. Provider adapters must preserve original values and return an explicit
unavailable result rather than substitute synthetic data.

| Source | Endpoint/station | Provides | Basis, units, cadence | Terms / attribution | Known gaps |
| --- | --- | --- | --- | --- | --- |
| NOAA CO-OPS | `8638614` Willoughby Degaussing | Wind speed, gust, direction from | English-unit API response; nominal 6-minute reports; averaging and gust duration undocumented and therefore unset | U.S. government data; identify NOAA CO-OPS and station | Current adapter still treats current `d` as direction toward pending authoritative confirmation |
| NOAA CO-OPS | `cb0402` Naval Station Norfolk LB 7 PORTS, bin 4 | Current observations and predictions | Knots, degrees true toward; observation and prediction treated as distinct products; bin/depth retained | U.S. government data; identify NOAA CO-OPS and station | Observations may lag by hours; no silent prediction fallback |
| NOAA CO-OPS | `8638610` Sewells Point | Water-level observations and tide predictions | Feet relative to MLLW; nominal 6-minute series | U.S. government data; identify NOAA CO-OPS and station | Prediction and observation issue/valid times remain distinct |
| NWS API | `/points/36.9585,-76.3305` → AKQ gridpoint (mapping must be refreshed periodically) | Wind speed, gust and direction forecast | Raw grid data, about 2.5 km grid; provider issue and ISO-8601 valid intervals retained; km/h normalized to knots; averaging and gust duration undocumented and therefore unset | Open U.S. government data; identify NOAA/NWS | Grid wind is not a berth measurement; missing gusts remain missing; public combined forecast waits for CBOFS current/water level |
| NOAA CBOFS | regular-grid forecast via CO-OPS THREDDS/OPeNDAP | Current vector and water level | Hourly, four cycles/day, 48-hour horizon; `u_eastward`/`v_northward` m/s at declared standard depth; `zetatomllw` metres relative to MLLW | U.S. government data; identify NOAA/NOS CO-OPS CBOFS | Nearest wet-cell sampling is model guidance, not a berth measurement; layer and cell must be exposed; no use of MSL `zeta` |
| Recorded real replay | `recorded_real/noaa-coops-norfolk-2026-01-01-v1` | Joined wind/current/water-level observations for an offline 54-minute window | Manifest-backed, SHA-256 verified; exact historical valid times; `replay` / `observation`; never looped or extrapolated | NOAA CO-OPS attribution; [NOAA/NOS disclaimer](https://oceanservice.noaa.gov/about/disclaimer.html); legal status not independently reviewed | Demo replay only; unknown wind averaging/gust duration; current direction convention and bin-4 applicability unqualified; station representativeness unqualified |
| Synthetic recorded-format fixture | `modeling/mooring/environment/fixtures/replay_sample.json` | Deterministic parser/training values | `replay` / `scenario`; explicitly synthetic | Project-generated fixture | Never eligible for `auto` fallback and never evidence of provider observations |
| Provider parser fixtures | `modeling/mooring/environment/fixtures/{coops,nws,cbofs}/` where present | Small raw response samples for offline parser tests | Provider-shaped JSON; deterministic test inputs | Inherit the source fixture's terms; store only legally shareable excerpts | Parser evidence only; prediction/error samples are not observation replay packages |

## Runtime source policy

`MOORING_ENV_SOURCE` is required by the modeling process and accepts exactly `mock`, `coops`, `replay`, or `auto`.
The supported `app.sh` and Makefile launchers make the explicit default choice `auto`; direct process launches must set it.

- `mock` is the only mode that serves synthetic environment values.
- `coops` serves live observations only and fails if they are stale, incomplete, or unavailable.
- `replay` serves only the manifest-backed recorded-real package.
- `auto` tries a fresh, complete CO-OPS snapshot, then the recorded-real replay, then fails explicitly. It never calls mock.

`GET /api/v1/env/availability` reports wind, current, water level, composed forecast, and waves independently. A missing
component is `unavailable` with a reason and provenance; it is never numeric zero or silently replaced by a prediction.

`POST /api/v1/env/forecast/compose` requires an explicit source, as-of cutoff, horizon, current depth and bin/layer.
It returns a content-addressed component manifest. Public mode composes NWS wind with exact CO-OPS prediction products;
an optional CBOFS artifact is used only after bounded out-of-process acquisition and exact applicability checks. Missing
gusts, late retrieval, stale cache, gaps, depth mismatch and provider outages produce partial/unavailable components.
Only aligned, fully populated prediction times are emitted as `EnvironmentSnapshot`s. The legacy forecast GET remains
synthetic and works only in explicit mock mode.

ENC chart data, live telemetry,
and approved wave sources will be added by their item-specific PRs after source
verification. DC4 Stage 1 source research is in
[`DC4_WAVE_SOURCE_INVESTIGATION.md`](DC4_WAVE_SOURCE_INVESTIGATION.md); it is
not approval to ingest a wave source.
