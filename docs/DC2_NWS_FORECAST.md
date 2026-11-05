# DC2 NWS wind forecast adapter (not operationally qualified)

The adapter resolves the berth coordinate through NWS `/points` and follows
`forecastGridData` to the raw grid forecast. NWS documents this grid as about
2.5 km by 2.5 km and warns that office/grid coordinates can change, so the
point mapping is fetched rather than hard-coded. The verified 4 November 2026
mapping for Pier 12 was AKQ 88,56.

`properties.updateTime` is retained as issue time; each quantity's ISO-8601
`validTime` is its valid interval. Replay rejects a response whose update time
is after the replay clock. Wind speed and gust are converted from km/h to
knots, direction is retained as true direction from, and original provider
values are retained. NWS API documentation does not establish the averaging
duration or gust duration for these grid fields, so both remain unset.

Missing wind speed or direction makes that period unavailable. A missing gust
stays `None`. DC2 does not create complete `EnvironmentSnapshot` objects,
because those require current and water level; public forecast composition is
therefore gated on DC3 rather than filling absent fields with synthetic zeroes.

Source: [NWS API Web Service](https://www.weather.gov/documentation/services-web-api).

Intervals already active at the requested as-of time are retained and clipped. The adapter splits at every speed, gust and direction boundary, so a gust change within a constant-speed period is not lost. Fixed-length ISO day/hour/minute/second durations are supported; overlapping intervals, invalid units and nonfinite/negative values are rejected. Missing gust remains unavailable. HTTP stale/cache-age provenance is retained for downstream gating.
