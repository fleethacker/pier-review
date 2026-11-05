# Recorded NOAA CO-OPS window (real observations)

Recorded 2026-11-05 at 17:11 UTC with `scripts/record_provider_fixture.py` (`MOORING_FIXTURE_RECORD=1`) from the public
NOAA CO-OPS Data API (`https://api.tidesandcurrents.noaa.gov/api/prod/datagetter`), `begin_date=20261105 16:11`,
`end_date=20261105 17:11`, `units=english`, `time_zone=gmt`, `format=json`. Responses are stored verbatim in canonical
(key-sorted, compact) form. NOAA CO-OPS data are public U.S. Government information; credit NOAA/NOS/CO-OPS.

| File | Product | Station | Notes |
| --- | --- | --- | --- |
| `wind_8638614.json` | wind | 8638614 Willoughby Degaussing Station | speed/gust kt, direction FROM; averaging basis not stated by the API (left unknown) |
| `water_level_8638610.json` | water_level, datum MLLW | 8638610 Sewells Point | latest values are preliminary (`q: p`) and flagged |
| `currents_cb0402_bin4.json` | currents, bin 4 (~20.6 ft) | cb0402 Naval Station Norfolk LB 7 | direction assumed TOWARD (see docs/NOAA_CURRENT_DIRECTION_REVIEW.md) |
| `currents_predictions_cb0402_bin4.json` | currents_predictions, bin 4 | cb0402 | tidal prediction; not used when the observation is fresh |

Joined through the repo's live CO-OPS path (`mooring.environment.live.latest` with a fixture transport and a clock frozen
at 17:11 UTC), the latest complete snapshot is 16:54 UTC: wind 12.44 kt from 214°, gust 14.0 kt; current 0.617 kt toward
352°; water level 0.869 ft MLLW; basis `observation`, quality `suspect` (preliminary water level), age 1020 s. These are
real observations for one moment; they say nothing about other times or about the berth itself.
