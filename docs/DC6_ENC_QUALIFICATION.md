# DC6 NOAA ENC reader and qualification boundary

The reader uses Fiona/GDAL's S-57 driver with updates enabled (GDAL's default).
It requires DSID/DSPM metadata and records the cell, edition, update number,
issue date, horizontal datum, separate vertical/sounding datum codes and depth units. Depth areas
come from `DEPARE.DRVAL1`; missing identity/datum metadata fails ingestion and
missing depth values are not treated as deep water.

Route code supplies a swept vessel-corridor polygon in the ENC coordinate
reference system. Evaluation unions depth-area coverage, rejects any uncovered
part, and returns the shallowest intersecting depth—including a patch between
deep endpoints or at the corridor edge. Waypoint-only checks are insufficient.

No NOAA cell is committed: current cells and numbered updates must be obtained
from NOAA for an opt-in qualification run, with cell identity recorded.
Existing berth YAML geometry remains explicitly notional; ENC depth/shoreline
evidence cannot establish fitting/fender positions or ratings. A survey or
approved berth plan is still required.

Sources: [NOAA ENC FAQ](https://nauticalcharts.noaa.gov/learn/faq.html),
[NOAA chart updates](https://nauticalcharts.noaa.gov/charts/chart-updates.html),
and [GDAL S-57 driver](https://gdal.org/en/stable/drivers/vector/s57.html).

## Reviewed reader boundary (4 November evening)

GDAL exposes DSID, DSSI and DSPM together in the **DSID** layer, using prefixed names
such as `DSID_EDTN` and `DSPM_SDAT`. The reader retains the dataset's own identity,
including when the local file is renamed. Vertical datum and sounding datum are
separate: DEPARE depths use SDAT, not VDAT. The depth reader currently accepts only
HDAT=2 (WGS84), DUNI=1 (metres), SDAT=12 (MLLW) and EPSG:4326 geometry. Other units,
datums or local M_SDAT overrides are explicit errors; no conversion is inferred.
Unknown depths/geometries, nonfinite/reversed bounds and invalid polygons fail closed.

An opt-in real-data smoke used NOAA `US5ORFCC` (Elizabeth River, 1:12000), base plus
updates .001–.005. Fiona read edition 1/update 5, issue date 20260930, HDAT=2,
VDAT=16, SDAT=12 and DUNI=1; all 141 DEPARE polygons passed the reader guards.
Source: [NOAA cell download](https://www.charts.noaa.gov/ENCs/US5ORFCC.zip), selected
from the [Virginia catalog](https://charts.noaa.gov/ENCs/VA_ENCProdCat_19115.xml).
Raw chart files, retrieval time and SHA256 provenance remain in temporary local
storage, outside git. Tests use the observed metadata structure and synthetic polygons;
they make no network requests.

This is **not an operationally qualified chart/UKC pipeline**. The result carries
limitations: DEPARE lower bounds alone do not evaluate SOUNDG points, wrecks,
obstructions, survey quality or later notices. Coverage does not establish chart currency,
route clearance, a berth survey or fitting/fender locations. Approach/UKC wiring remains
separate. Datum meaning follows [IHO S-57](https://iho.int/en/s-57-standards-in-force);
see also the [IHO vertical datum register](https://registry.iho.int/fdd/view3.do?idx=1408&ispreorsuc=successor&type=3).
