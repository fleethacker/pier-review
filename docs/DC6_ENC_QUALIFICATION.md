# DC6 NOAA ENC qualification

The reader uses Fiona/GDAL's S-57 driver with updates enabled (GDAL's default).
It requires DSID/DSPM metadata and records the cell, edition, update number,
issue date, horizontal datum code and vertical/sounding datum code. Depth areas
come from `DEPARE.DRVAL1`; missing values are not treated as deep water.

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
