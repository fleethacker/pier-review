# DC4 Stage 1: wave and swell source investigation

**Decision gate:** investigation only. No wave adapter or schema change should be
implemented until a human approves a source and RM2 defines the wave fields.

This note was checked on 4 November 2026 for the repository's mock NAVSTA Norfolk
Pier 12 location (`36.9585, -76.3305`). Distances below are approximate great-circle
distances to that point; they are not claims of hydrodynamic representativeness.

## Candidate sources

| Source | Verified coverage and products | Cadence and access | Distance and fitness for a sheltered pier |
| --- | --- | --- | --- |
| [NDBC 44099, Cape Henry](https://www.ndbc.noaa.gov/station_page.php?station=44099) | Active directional Waverider at `36.915, -75.722`, 15 m water depth. It reports significant wave height, dominant and average period, mean direction, separated swell and wind-wave height/period/direction, and directional spectra. NDBC defines wave height from a 20-minute acquisition and directions as the direction **from** true north. | Recent text and spectral files, 45-day real-time data, and historical files are public. The displayed standard wave series is roughly 30 minutes at present, while some summary fields are documented as hourly; an adapter must use each record's timestamp rather than assume one cadence. | About 54 km from Pier 12 and seaward of the Chesapeake entrance. Best public observation of the incoming offshore sea state, but not a berth measurement. Shoals, the bay entrance, shoreline shelter and the Elizabeth River remove or transform much of that energy. |
| [NDBC 44014, Virginia Beach](https://www.ndbc.noaa.gov/station_page.php?station=44014) | Active directional buoy at `36.603, -74.837`, 64 nautical miles east of Virginia Beach. It supplies significant height, dominant/average period, mean direction and directional spectra; its station page currently exposes wind-sea/swell partition products as well. | Near-real-time records are currently about 30 minutes apart, with public historical files. | About 139 km from Pier 12. It is an offshore regional boundary/reference and a useful independent fallback check, but is materially farther away than 44099 and cannot describe harbor wind waves or pier shelter. |
| [NCEP GFS-Wave / WAVEWATCH III guidance](https://nomads.ncep.noaa.gov/gribfilter.php?ds=gfswave) | NOMADS currently exposes gridded significant height (`HTSGW`), primary-wave direction/period, swell height/direction/period (up to three partitions), and wind-wave height/direction/period. The global files are identified as `0p16` (about 0.16 degrees). | Four forecast cycles are exposed (00, 06, 12 and 18 UTC), with GRIB subsetting by variable and region. This is model guidance rather than an observation, and issue time must be retained so replay never selects a future cycle. | The grid is far too coarse to resolve a berth or the Elizabeth River, and ocean-wave guidance does not provide a validated harbor transformation. Useful for forecast continuity and as a fallback to 44099, not as a direct pier condition. |
| [CBOFS](https://tidesandcurrents.noaa.gov/ofs/cbofs/cbofs.html) | **Not a wave source.** NOAA lists only water level, currents, water temperature and salinity for this ROMS operational forecast system. No wave or swell variables are advertised. | Four cycles per day; model guidance. | It covers Chesapeake Bay hydrodynamics but cannot fill wave fields. Do not infer waves from its wind or current output and do not implement a CBOFS wave adapter. |
| Berth-local instrument supplied by the human | A directional wave gauge, pressure/velocity sensor, or qualified ship motion/wave sensor at or immediately adjacent to the pier could provide the actual short-period harbor wave field. Required minimum outputs are significant height, a defined mean or peak period, direction-from true, sampling/averaging details, quality flags and sensor position/depth. A spectrum is strongly preferred. | Unknown until a sensor/data owner is identified. The feed format, calibration history, datum/depth, rights and expected availability must be supplied. | Only candidate that can directly characterize Pier 12 shelter, locally generated wind sea, wakes and reflection. It is the best eventual primary source, but it does not exist in the material available to this project today. |

### Nearby source checked but not currently usable

[CBIBS/NDBC 44064 First Landing](https://www.ndbc.noaa.gov/station_page.php?station=44064)
is closer (about 22 km from Pier 12, near the bay entrance), and CBIBS exposes wave
parameter names through an API. The station was redeployed in 2022, but NDBC
currently says **No Recent Reports**. Historical records exist. It must remain
unavailable rather than silently substituting old data; it could become a useful
intermediate validation station if reliable real-time wave reporting resumes.

The former CBIBS Norfolk station 44059 was still closer (about 13 km), but NOAA says
it operated only from 2008 to 2016. Its history may help a later retrospective
transfer study, not a live adapter.

## Harbor penetration and required transfer assumption

Neither 44099, 44014 nor the GFS-Wave grid measures the Pier 12 wave climate. Long
ocean swell entering the Chesapeake is refracted, shoaled, dissipated and partly
blocked at the entrance; then Craney Island, Sewells Point, channel geometry and the
Elizabeth River further shelter Pier 12. Locally generated short-period wind waves,
vessel wakes, diffraction and pier reflection can matter even when offshore swell
does not. Therefore copying offshore significant height, period or direction to the
berth would fabricate precision.

Stage 2 needs either:

1. a validated nearshore/harbor wave transformation model using bathymetry,
   shoreline/structures, water level and local wind; or
2. an empirical, frequency-and-direction-dependent transfer function calibrated
   against simultaneous berth-local measurements and the offshore source.

Until one of those is validated, offshore wave data may be labeled only as an
**offshore boundary condition**. Berth wave fields must remain unavailable/limited,
with an explicit `NO_BERTH_WAVE_TRANSFER` reason. A single scalar attenuation factor
is not recommended because shelter depends strongly on frequency, direction and
water level.

## Recommendation and approval requested

Use **NDBC 44099 as the primary public offshore observation** and **GFS-Wave as the
forecast/fallback source**. Use 44014 as an independent offshore sanity check, not
the normal fallback, because it is much farther from the bay entrance. If a qualified
berth-local feed can be supplied, promote it to the primary berth source and use
44099 plus GFS-Wave as boundary/forecast inputs after calibrating the transfer.

Human decision required before Stage 2: approve that source order and choose whether
the first implementation should (a) expose offshore conditions while declaring berth
waves unavailable, or (b) wait for a berth-local feed and a validated transfer. The
latter is required before wave forcing can support a valid ship-motion conclusion at
Pier 12.

## Licensing and attribution

NOAA/NWS information is generally public domain unless a page identifies third-party
material. It may be used without charge, but must not be presented as this project's
own official government product or imply NOAA endorsement. Attribute displays and
artifacts with `Data source: NOAA/NDBC` or `Data source: NOAA/NCEP`, preserve station,
product, issue/valid times and retrieval time, and carry the applicable NOAA/NWS
disclaimer. Station 44099 is operated by Scripps/CDIP, so Stage 2 must also confirm
and retain any attribution attached to the downloaded record. No NOAA logos are
needed. A human-supplied local feed requires written redistribution and retention
terms before fixtures are committed.

## Verification sources

- [NDBC 44099 real-time products](https://www.ndbc.noaa.gov/station_realtime.php?station=44099)
- [NDBC 44014 real-time products](https://www.ndbc.noaa.gov/station_realtime.php?station=44014)
- [NDBC measurement definitions](https://www.ndbc.noaa.gov/faq/measdes.shtml)
- [NDBC wave calculations and partitions](https://www.ndbc.noaa.gov/faq/wavecalc.shtml)
- [CBIBS First Landing station](https://www.buoybay.noaa.gov/locations/first-landing)
- [CBIBS API fields and quality metadata](https://content.buoybay.noaa.gov/data/api)
- [CBOFS advertised variables](https://tidesandcurrents.noaa.gov/ofs/cbofs/cbofs.html)
- [NCEP GFS-Wave NOMADS filter](https://nomads.ncep.noaa.gov/gribfilter.php?ds=gfswave)
- [NWS data-use disclaimer](https://www.weather.gov/disclaimer)
