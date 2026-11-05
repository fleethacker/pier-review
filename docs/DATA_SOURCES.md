# Data sources

This registry records external inputs, their normalization basis, and known
gaps. Provider adapters must preserve original values and return an explicit
unavailable result rather than substitute synthetic data.

| Source | Endpoint/station | Provides | Basis, units, cadence | Terms / attribution | Known gaps |
| --- | --- | --- | --- | --- | --- |
| NOAA CO-OPS | `8638614` Willoughby Degaussing | Wind speed, gust, direction from | English-unit API response; nominal 6-minute reports; averaging and gust duration undocumented and therefore unset | U.S. government data; identify NOAA CO-OPS and station | Current adapter still treats current `d` as direction toward pending authoritative confirmation |
| NOAA CO-OPS | `cb0402` Naval Station Norfolk LB 7 PORTS, bin 4 | Current observations and predictions | Knots, degrees true toward; observation and prediction treated as distinct products; bin/depth retained | U.S. government data; identify NOAA CO-OPS and station | Observations may lag by hours; no silent prediction fallback |
| NOAA CO-OPS | `8638610` Sewells Point | Water-level observations and tide predictions | Feet relative to MLLW; nominal 6-minute series | U.S. government data; identify NOAA CO-OPS and station | Prediction and observation issue/valid times remain distinct |
| Recorded fixtures | `modeling/mooring/environment/fixtures/` | Offline provider responses and replay windows | Canonical, key-sorted JSON; deterministic across clocks and machines | Inherit the source fixture's terms; store only legally shareable excerpts | Fixtures are test evidence, not live data |

NWS wind, CBOFS current/water-level forecasts, ENC chart data, live telemetry,
and approved wave sources will be added by their item-specific PRs after source
verification. DC4 Stage 1 source research is in
[`DC4_WAVE_SOURCE_INVESTIGATION.md`](DC4_WAVE_SOURCE_INVESTIGATION.md); it is
not approval to ingest a wave source.
