# DC3 CBOFS forecast qualification

CBOFS runs at 00, 06, 12 and 18 UTC and publishes hourly forecast guidance to
48 hours. The adapter targets NOAA's regular-grid NetCDF product through
THREDDS/OPeNDAP. It reads the coordinate grids needed to locate the nearest wet
cell, then lazily reads only the selected point/layer data variables.

The product declares NAD83 latitude/longitude, standard depths in metres
positive down, `u_eastward` and `v_northward` in m/s, and `zetatomllw` in
metres relative to MLLW. Current direction is calculated by vector math as the
direction the current flows toward. The nearest wet grid cell and nearest
declared depth are selected and retained. A dataset without `zetatomllw` is
rejected; the MSL `zeta` variable is never relabeled or silently converted.

A cycle issued after the replay clock is rejected. Missing/fill values are
omitted, and an all-missing selection is unavailable. Tests use an in-memory
tiny NetCDF-equivalent dataset and never access the network.

CBOFS `zetatomllw` can be compared with Sewells Point MLLW values, while vector
direction is “toward” as used for cb0402. Those checks detect convention/datum
errors but do not make model guidance equivalent to a station or pier reading.

Sources: [NOAA OFS FAQ](https://tidesandcurrents.noaa.gov/ofs/ofs_faq.html) and
[CBOFS THREDDS catalog](https://opendap.co-ops.nos.noaa.gov/thredds/catalog/CBOFS/fmrc/catalog.html).
