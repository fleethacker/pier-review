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
| NOAA/NDBC 44099 | Cape Henry realtime `.spec`, `.data_spec`, `.swdir`, `.swdir2`, `.swr1`, `.swr2` | Offshore total sea, provider wind-sea/swell partitions and native density/Fourier products | Provider UTC timestamps; metres normalized to feet only in suffixed output fields; frequency in Hz, density in m²/Hz; alpha directions are from true north clockwise; rows older than three hours are unavailable, not `live` | U.S. government data with NOAA/NDBC and Scripps/CDIP attribution retained | About 54 km from the berth; sample bounds/timestamp position remain unknown for selected realtime text products; no harbor/berth transfer |
| NOAA/NDBC 44014 | Virginia Beach realtime `.spec` | Independent offshore total-sea check | Provider UTC timestamps; metres normalized to feet; missing native partitions stay missing | U.S. government data; identify NOAA/NDBC and station | About 139 km from the berth; independent comparison only, never automatic substitution or berth truth |
| NOAA/NCEP GFS-Wave | decoded `atlocn.0p16` artifact configured by `MOORING_GFS_WAVE_ARTIFACT` | Offshore total sea, wind sea and provider swell partitions | Artifact retains declared reference/issue/retrieval and valid times; exact `HTSGW/PERPW/DIRPW`, `WVHGT/WVPER/WVDIR`, and sequence levels 1–3 for `SWELL/SWPER/SWDIR`; offshore target `atlocn.0p16:row109,col146` at approximately `36.833333,-75.666667`; cycle and FH000–FH384 bound to the product identity | U.S. government data; identify NOAA/NCEP and product | API process reads a bounded, self-hashed decoded artifact whose official URLs and product identity are cross-bound; this checks integrity, not cryptographic source authenticity. Issues older than 18 hours and absent/late/malformed/uncovered guidance are unavailable; grid guidance has no validated harbor transfer |
| Recorded real replay | `recorded_real/noaa-coops-norfolk-2026-01-01-v1` | Joined wind/current/water-level observations for an offline 54-minute window | Manifest-backed, SHA-256 verified; exact historical valid times; `replay` / `observation`; never looped or extrapolated | NOAA CO-OPS attribution; [NOAA/NOS disclaimer](https://oceanservice.noaa.gov/about/disclaimer.html); legal status not independently reviewed | Demo replay only; unknown wind averaging/gust duration; current direction convention and bin-4 applicability unqualified; station representativeness unqualified |
| Synthetic recorded-format fixture | `modeling/mooring/environment/fixtures/replay_sample.json` | Deterministic parser/training values | `replay` / `scenario`; explicitly synthetic | Project-generated fixture | Never eligible for `auto` fallback and never evidence of provider observations |
| Provider parser fixtures | `modeling/mooring/environment/fixtures/{coops,nws,cbofs,ndbc}/` where present | Small raw response samples for offline parser tests | Provider-shaped data; deterministic test inputs | Inherit the source fixture's terms; store only legally shareable excerpts | Parser evidence only; prediction/error samples are not observation replay packages |

## Runtime source policy

`MOORING_ENV_SOURCE` is required by the modeling process and accepts exactly `mock`, `coops`, `replay`, or `auto`.
The supported `app.sh` and Makefile launchers make the explicit default choice `auto`; direct process launches must set it.

- `mock` is the only mode that serves synthetic environment values.
- `coops` serves live observations only and fails if they are stale, incomplete, or unavailable.
- `replay` serves only the manifest-backed recorded-real package.
- `auto` tries a fresh, complete CO-OPS snapshot, then the recorded-real replay, then fails explicitly. It never calls mock.
- The offline demo and `make demo-check` select `recorded_real` explicitly, verify its deterministic manifest and exercise
  it through the environment API. This archive contains CO-OPS observations only; no NWS response was archived, so NWS
  forecast wind and waves remain unavailable rather than being inferred from the observation window.

`GET /api/v1/env/availability` reports wind, current, water level, composed forecast, and waves independently. A missing
component is `unavailable` with a reason and provenance; it is never numeric zero or silently replaced by a prediction.

`POST /api/v1/env/forecast/compose` requires an explicit source, as-of cutoff, horizon, current depth and bin/layer.
It returns a content-addressed component manifest. Public mode composes NWS wind with exact CO-OPS prediction products;
an optional CBOFS artifact is used only after bounded out-of-process acquisition and exact applicability checks. Missing
gusts, late retrieval, stale cache, gaps, depth mismatch and provider outages produce partial/unavailable components.
Only aligned, fully populated prediction times are emitted as `EnvironmentSnapshot`s. The legacy forecast GET remains
synthetic and works only in explicit mock mode.

`POST /api/v1/env/waves/compose` independently acquires NDBC 44099 observations and a 44014 comparison, and reads a
validated decoded GFS-Wave artifact when one is configured. Each role can fail without zero-filling or changing another
role. Total sea, provider partitions and native spectra remain alternative representations. Every output is labeled
`offshore_boundary_only` and `load_ready=false`; ocean-swell transfer, local chop, ship wake and tug wake remain explicit
berth-level gaps. NDBC acquisition streams through byte, per-response elapsed-time and composition deadlines; stale 44099 input remains unavailable while
GFS-Wave is explicitly retained as prediction guidance. The GFS artifact is accepted only for the reviewed Pier 12 North
target and exact grid cell; a nonmissing decoded cycle value is not evidence of a permanent wet-cell mask. The exact
source decision and remaining engineering gates are in
[`DC4_WAVE_SOURCE_INVESTIGATION.md`](DC4_WAVE_SOURCE_INVESTIGATION.md).

The `0p16` product name denotes **1/6 degree (10 arcminutes)**, not an exact 0.16-degree lattice; see NOAA's
[GFS-Wave model description](https://polar.ncep.noaa.gov/waves/Model_Description.pdf).
The [5 November 2026 12Z, FH003 GRIB](https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.20261105/12/wave/gridded/gfswave.t12z.atlocn.0p16.f003.grib2)
was inspected using bounded header/bitmap requests: template 3.0, 301 columns by 331 rows, longitude 260–310°E,
latitude 55–0°N, scanning east then south, and stored increments of 166667 microdegrees. Row 109, column 146
(zero based) is the nearest native cell to station 44099; its `HTSGW` bitmap entry was present in this one cycle.
The adapter uses native row/column identity and tolerates only coordinate error caused by the rounded GRIB increment.
This verifies a source location and one available sample, not a permanent wet-cell mask or harbor applicability.
The former `36.96,-75.68` target was not a native grid cell and is rejected.

ENC chart data and opt-in telemetry arbitration will be added by their item-specific work after source verification.
