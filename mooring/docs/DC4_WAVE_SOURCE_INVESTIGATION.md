# DC4 Stage 1: wave and swell source investigation

**Decision gate:** the human approved the public-source order on 4 November 2026:
NDBC 44099 for observations, GFS-Wave for forecasts/fallback, and 44014 as an
independent check. Adapter implementation still waits for DC0 and the merged RM2
ingestion schema coordinated through RM0. Approval does not qualify an offshore
source as representative of Pier 12.

This note was checked on 4 November 2026 for the repository's mock NAVSTA Norfolk
Pier 12 location (`36.9585, -76.3305`). Distances below are approximate great-circle
distances to that point; they are not claims of hydrodynamic representativeness.

## Candidate sources

| Source | Verified coverage and products | Cadence and access | Distance and fitness for a sheltered pier |
| --- | --- | --- | --- |
| [NDBC 44099, Cape Henry](https://www.ndbc.noaa.gov/station_page.php?station=44099) | Active directional Waverider at `36.915, -75.722`, 15 m water depth. It reports significant wave height, dominant and average period, mean direction, separated swell and wind-wave height/period/direction, and directional spectral products. Preserve each field's period/direction definition; peak and mean quantities are not interchangeable. Do not assume NDBC's generic acquisition duration applies to this Scripps/CDIP instrument; confirm the selected product's time bounds and direction convention before filling metadata. | Recent text and spectral files, 45-day real-time data, and historical files are public. The displayed standard wave series is roughly 30 minutes at present, while some summary fields are documented as hourly; an adapter must use each record's timestamp rather than assume one cadence. | About 54 km from Pier 12 and seaward of the Chesapeake entrance. Approved primary public offshore observation, not a berth measurement. The amount and direction of energy reaching the mock pier have not been established by this investigation. |
| [NDBC 44014, Virginia Beach](https://www.ndbc.noaa.gov/station_page.php?station=44014) | Active directional buoy at `36.603, -74.837`, 64 nautical miles east of Virginia Beach. It supplies significant height, dominant/average period, mean direction and directional spectral products; its station page currently exposes wind-sea/swell partition products as well. | Near-real-time records are currently about 30 minutes apart, with public historical files. | About 139 km from Pier 12. It is an offshore regional boundary/reference and a useful independent fallback check, but is materially farther away than 44099 and cannot describe harbor wind waves or pier shelter. |
| [NCEP GFS-Wave / WAVEWATCH III guidance](https://nomads.ncep.noaa.gov/gribfilter.php?ds=gfswave) | NOMADS currently exposes gridded significant height (`HTSGW`), primary-wave direction/period, swell height/direction/period (up to three partitions), and wind-wave height/direction/period. NCEP lists multiple output grids, including Atlantic `atlocn.0p16` and global products. Stage 2 must pin a grid/file inventory and verify its land mask, wet-cell locations and resolution rather than infer coverage from the model name. | Scheduled cycles are 00, 06, 12 and 18 UTC, with GRIB subsetting by variable and region. A scheduled cycle is not necessarily published or complete. NOMADS provides recent cycles; long-term forecast archive coverage/retention is not verified here. Preserve reference/issue time, valid time, lead time and actual availability as described below. | These offshore grids do not resolve individual pier structures, and this investigation establishes no validated harbor transformation. Useful for forecast continuity and as a fallback to 44099, not as a direct pier condition. |
| [CBOFS](https://tidesandcurrents.noaa.gov/ofs/cbofs/cbofs.html) | **Not a wave source.** NOAA lists only water level, currents, water temperature and salinity for this ROMS operational forecast system. No wave or swell variables are advertised. | Four cycles per day; model guidance. | It covers Chesapeake Bay hydrodynamics but cannot fill wave fields. Do not infer waves from its wind or current output and do not implement a CBOFS wave adapter. |
| Berth-local instrument supplied by the human | A suitably calibrated local wave instrument could measure exposure at its location within its demonstrated bandwidth. Record supported height/period/direction/spectral fields, sampling/time bounds, quality flags and position/depth. A scalar pressure sensor need not resolve direction, and its depth response can limit short-wave recovery. Ship motion is not a direct wave observation without a qualified response/inversion. Keep unsupported fields unavailable; do not fabricate direction or a spectrum. | Unknown until a sensor/data owner is identified. The feed format, calibration history, datum/depth, rights and expected availability must be supplied. | Potential primary for the exposure it demonstrably measures, subject to placement, calibration and bandwidth review. A single local record does not automatically separate swell, chop, wake and reflection or represent the entire berth. No such qualified feed is available to this project today. |

### Nearby source: NDBC reporting gap; direct CBIBS availability unresolved

[CBIBS/NDBC 44064 First Landing](https://www.ndbc.noaa.gov/station_page.php?station=44064)
is closer (about 22 km from Pier 12, near the bay entrance), and CBIBS exposes wave
parameter names through an API. The station was redeployed in 2022, but NDBC
was reported as **No Recent Reports** in the original check. That establishes an
NDBC-channel gap, not that the independent CBIBS API is also offline. A timestamped
direct CBIBS wave/QC response has not been verified here. Treat that path as
unverified; do not substitute old data or claim a live fallback. It could be
evaluated as an intermediate validation station without changing the approved
source order.

The former CBIBS Norfolk station 44059 was still closer (about 13 km), but NOAA says
it operated only from 2008 to 2016. Its history may help a later retrospective
transfer study, not a live adapter.

## Separate berth-exposure components

The approved buoy/model pair describes offshore wave conditions. It must not collapse
three physically different berth exposures into one number.

### Ocean swell and offshore sea state

NDBC 44099 is the primary observation and GFS-Wave the forecast/fallback. NDBC's
detailed wave summary provides wind-sea and swell partitions derived from its measured
spectrum; the full significant height is a total sea state, not pure swell. Stage 2
must preserve whether a record is a total, a provider partition or a spectrum. It must
not apply a total spectrum and then add its swell or wind-sea partition again.

This component is worth building first after its dependencies merge because the
approved sources offer ingestion candidates. Buoy observation history and recent
model cycles are available; older forecast-as-of replay remains conditional on the
archive verification below. It remains an offshore boundary condition
until the transfer described below is validated.

### Wind-driven local chop

The [USACE Coastal Engineering Manual, EM 1110-2-1100 Part II (2002)](https://www.publications.usace.army.mil/Portals/76/Publications/EngineerManuals/EM_1110-2-1100_Part-02.pdf)
provides fetch- and duration-limited wind-wave growth methods. A later implementation
must record the exact equations and domain, convert the DC1/DC2 wind to the manual's
required averaging/reference-height basis once, and use water depth, wind duration and
directional effective fetch. Reporting cadence is not wind duration.

No qualified directional fetch geometry exists in this repository. DC6 chart and
shoreline work can provide a starting boundary, but pier structures and other local
obstructions still need review. Therefore local chop is currently **unavailable**, not
zero. Its future primary inputs should be verified berth wind plus reviewed directional
fetch geometry; there is no defensible independent fallback today. A berth wave gauge
would both supersede the estimate for observations and provide validation data.

### Ship and tug wake

The [USACE Vessel Wake Prediction Tool technical note CHETN-IV-121 (2020)](https://erdc-library.erdc.dren.mil/bitstreams/2d81c6ff-5889-441f-a08f-39bfa32c193b/download)
documents several low-order empirical wake-height/decay models. Their domains vary
substantially: restricted canals, inland vessels/tows, recreational craft and limited
Froude-number ranges. USACE describes the tool as a screening method and notes limited
validation. None is established here for Navy ships, Hampton Roads propagation or a
moored-ship forcing calculation.

Wake is an event with an arrival time and finite duration, not automatically a
stationary significant-height/period sea state. Modeling it would require at least a
real traffic feed, vessel identity/hull dimensions/draft, speed through water, sailing
line and closest approach, water depth, a domain-appropriate generation/propagation
model, and berth-side validation. DC7 can decode AIS but does not supply traffic. USCG
real-time NAIS access requires an approved request and data-sharing agreement and
restricts redistribution; public historical AIS does not provide a live fallback.

Ship/tug wake is therefore **unavailable with no supported fallback**. Do not infer it
from generic traffic, silently set it to zero, or treat surface wake as propeller wash.
It should be built only after an approved feed/model and local validation are supplied;
it must not block the independently approved offshore component.

## Harbor penetration and required transfer assumption

Neither 44099, 44014 nor the GFS-Wave grid measures the Pier 12 wave climate. This
investigation has not traced or validated a wave-propagation path to the mock pier
coordinate. Do not assume waves must travel along the Elizabeth River, or assign
attenuation to named islands/headlands, without chart/bathymetry and directional
propagation evidence for that coordinate. Refraction, shoaling, dissipation,
sheltering, local generation, diffraction and reflection are processes to evaluate,
not a quantified transfer derived here. Copying offshore height, period or direction
to the berth would fabricate precision.

Using offshore data as qualified berth forcing requires either:

1. a validated nearshore/harbor wave transformation model using bathymetry,
   shoreline/structures, water level and local wind; or
2. an empirical, frequency-and-direction-dependent transfer function calibrated
   against simultaneous berth-local measurements and the offshore source.

Until one of those is validated, offshore wave data may be labeled only as an
**offshore boundary condition**. Without a supported berth estimate, numeric berth
wave fields must remain unavailable, with an explicit `NO_BERTH_WAVE_TRANSFER`
reason. A limited-validity label alone does not authorize copying offshore values
into berth fields. An explicitly approved synthetic visualization surrogate must
remain separate from observed/predicted berth conditions. A single scalar attenuation factor
is not recommended because shelter depends strongly on frequency, direction and
water level.

## Adapter semantics and remaining verification gates

- **Sampling and timestamps:** retain provider-native sample bounds, timestamp meaning
  (start/end/center), publication/retrieval time and quality flags. CDIP's
  [product documentation](https://cdip.ucsd.edu/themes/cdip?d2=p20&fs=0&pb=1&u2=tab%3A1%3Adisplay%3Aaccess_instructions)
  and [wave dataset metadata](https://erddap.cdip.ucsd.edu/erddap/tabledap/wave_agg.html)
  describe sampling windows separately from transmission cadence. Confirm the
  station/product-specific duration; do not fill a guessed 20-minute default.
  A start-stamped observation cannot be available before its acquisition ends.
- **Spectral representation:** NDBC frequency-density and directional coefficient
  files are not interchangeable with a complete frequency-by-direction energy
  array. Preserve their native representation, units, frequency bins and QC.
  Reconstructing a directional spectrum needs a documented method and tests.
  Missing spectral/partition records must not be inferred from a product link.
- **Fallback:** GFS-Wave replacing a missing/stale buoy remains **model guidance**,
  never an observation. Record the switch reason and source, issue/valid times,
  location/grid, and applicable freshness policy; retain the observation outage.
  If model guidance is also unavailable/stale, return unavailable. The 44014 check
  is a comparison across distinct locations, not a substitution or an automatic
  truth label. Do not combine it as independent evidence without evaluating errors
  shared with the selected model/product.
- **Replay:** the [NOMADS listing](https://nomads.ncep.noaa.gov/gribfilter.php?ds=gfswave)
  inspected on 4 November showed recent daily directories, not a guaranteed
  long-term archive. Before promising forecast replay, verify a retained endpoint
  and interval, exact product/version, completeness and a retrievable issued-cycle
  sample. Record sample keys/checksums in the adapter PR. A hindcast or reanalysis
  is not an archived forecast. Select only cycles available at the replay decision
  time, accounting for publication lag; cycle time alone is insufficient. If
  historical availability cannot be established, label replay limited or unavailable.
- **Fixtures and rollout:** test buoy outage to explicitly labeled model fallback,
  both sources unavailable, start-stamped observations, unpublished forecast cycles,
  missing partitions, spectral representation/units, and offshore-versus-berth
  separation. Existing partition/overlap and unavailable-versus-zero checks in
  DC4/RM2 still apply. These are Stage 2 prerequisites, not adapters implemented by
  this Stage 1 note.

## Approved recommendation and build order

Use **NDBC 44099 as the primary public offshore observation** and **GFS-Wave as the
forecast/fallback source**. Use 44014 as an independent offshore sanity check, not
the normal fallback, because it is much farther from the bay entrance. If a qualified
berth-local feed can be supplied, promote it to the primary berth source and use
44099 plus GFS-Wave as boundary/forecast inputs after calibrating the transfer.

Implement the offshore observation/forecast component first once DC0 and the merged
RM2 schema exist. Expose it as an offshore boundary condition while declaring berth
wave exposure unavailable with `NO_BERTH_WAVE_TRANSFER`. Follow with local chop only
after reviewed fetch geometry exists. Leave wake unavailable until its feed, model and
validation blockers are resolved. A validated berth-local feed may later become the
primary observation for all components it actually measures.

This order permits honest ingestion and replay work without claiming that offshore
conditions drive qualified ship motion at Pier 12. A validated berth transfer or local
measurement remains mandatory before that claim.

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
- [NCEP wave-model overview and cycle paths](https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/wavemodels.php)
- [NCEP GFS-Wave output-grid/file inventory](https://www.nco.ncep.noaa.gov/pmb/products/gfs/)
- [NCEP GFS-Wave NOMADS filter](https://nomads.ncep.noaa.gov/gribfilter.php?ds=gfswave)
- [NWS data-use disclaimer](https://www.weather.gov/disclaimer)
- [USACE Coastal Engineering Manual listing](https://www.publications.usace.army.mil/USACE-Publications/Engineer-Manuals/)
- [USACE Vessel Wake Prediction Tool, CHETN-IV-121](https://erdc-library.erdc.dren.mil/bitstreams/2d81c6ff-5889-441f-a08f-39bfa32c193b/download)
- [USCG AIS data-sharing requirements](https://navcen.uscg.gov/ais-data-sharing-categories-requirements)
