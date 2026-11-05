# DC3 CBOFS reader and qualification limits

CBOFS runs four daily cycles and provides hourly guidance through 48 hours. This reader targets NOAA's
**regular-grid** NetCDF product, including `zetatomllw`; the FMRC native ROMS grid is not interchangeable.
A verified example is the NOAA THREDDS path
`NOAA/CBOFS/MODELS/2026/11/04/cbofs.t18z.20261104.regulargrid.f024.nc`.
Use the decoded time coordinate, not an inferred timestamp from the filename.

NOAA documents NAD83 coordinates. The selected cell's coordinates and standard depth are retained; they are not a
surveyed pier measurement. Required metadata declares degrees north/east, metres positive down, eastward/northward
velocity in m/s, and `zetatomllw` in metres relative to MLLW. The MSL `zeta` variable is never relabeled or converted.
The reader checks units, dimensions, finite coordinates, increasing depth/time coordinates and requested domain/layer
bounds. Current direction is the direction of flow, calculated from east/north components.

Selection is nearest wet cell within the supplied grid domain, then nearest declared standard layer. It does not move
to another cell or layer if that selection has missing current values. Missing/fill values omit that timestamp and are
listed in `omitted_times_utc`; an entirely missing selection is unavailable. Gaps must remain visible to a composing
forecast service. There is no spatial interpolation, pier-current correction or verified cell-to-berth applicability.

`issued_at` is caller-supplied and checked against `as_of`. This does **not** verify actual publication time. A cycle
initialization time is not proof that the forecast was available then; retain publication/retrieval evidence before
making a historical availability claim. Every output carries explicit model-guidance and issue-time limitations.

`open_subset` permits local files or NOAA HTTPS CBOFS datasets. Native HTTP operations have a 15-second timeout;
this is not a total acquisition deadline. Callers must close datasets and enforce a total worker deadline. Native NetCDF
access is restricted to a main-thread worker; do not call it in concurrent API threads. No retry/cache/stale fallback
or complete public forecast endpoint is implemented by this reader. Default environment behavior is unchanged.

Tests use synthetic in-memory datasets and a tiny local NetCDF round trip; no network. Temporary live pulls are kept
outside the repository. Comparison with a station can detect convention errors but cannot qualify pier guidance.

Live smoke, retrieved 2026-11-05 04:13 UTC, sampled a 3×3/16-layer subset of that file. At 36.96, -76.33,
valid 2026-11-05 18:00 UTC: surface current 0.320 kt toward 57.48°, water level 1.265 ft MLLW;
4 m and 6 m currents were unavailable. An explicitly requested neighboring cell at longitude -76.335 had
6 m current 0.207 kt toward 62.95°. These values establish reader conventions only, not pier applicability or a
complete forecast. The temporary decoded NetCDF subset has URL/retrieval-time/SHA256 provenance outside the repo.
Retrieval completion time was used as an availability upper bound, not claimed as the model's issue time.

Sources: [NOAA OFS FAQ](https://tidesandcurrents.noaa.gov/ofs/ofs_faq.html),
[CBOFS information](https://tidesandcurrents.noaa.gov/ofs/cbofs/cbofs_info.html),
[verified regular-grid metadata](https://opendap.co-ops.nos.noaa.gov/thredds/dodsC/NOAA/CBOFS/MODELS/2026/11/04/cbofs.t18z.20261104.regulargrid.f024.nc.das),
[Unidata native HTTP timeout configuration](https://docs.unidata.ucar.edu/netcdf-c/current/auth.html),
and [netCDF4 Python API/thread-safety guidance](https://unidata.github.io/netcdf4-python/).
