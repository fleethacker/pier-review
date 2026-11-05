"""CBOFS regular-grid guidance reader (DC3), not a qualified pier forecast provider.

Declared units/datum follow NOAA regular-grid metadata; see docs/DC3_CBOFS_FORECAST.md.
Network use is opt-in. Keep native NetCDF access in an isolated worker, not an API thread.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from math import atan2, degrees, hypot
from threading import current_thread, main_thread
from typing import Any
from urllib.parse import urlsplit

import netCDF4
import numpy as np
import xarray as xr

from .errors import ProviderError

MPS_TO_KT = 1.9438444924406
M_TO_FT = 3.2808398950131
HTTP_TIMEOUT_S = 15  # Transport policy, per native HTTP operation; not a total worker deadline.
METRES = {"m", "meter", "meters", "metre", "metres"}
VELOCITY_UNITS = {"m/s", "m s-1", "meters second-1", "meter second-1"}
LIMITATIONS = (
    "Model guidance at a nearest wet grid cell and standard layer; not a qualified pier measurement.",
    "Issue time is caller-supplied; historical availability is not independently verified by this reader.",
)


@dataclass(frozen=True)
class CBOFSForecast:
    valid_at_utc: datetime
    issued_at_utc: datetime
    current_speed_kt: float
    current_toward_true_deg: float
    water_level_mllw_ft: float
    depth_m: float
    grid_latitude: float
    grid_longitude: float
    source: str = "NOAA CBOFS regular grid"
    limitations: tuple[str, ...] = LIMITATIONS
    omitted_times_utc: tuple[datetime, ...] = ()


def _utc(value: Any) -> datetime:
    if np.isnat(value):
        raise ProviderError("malformed", "CBOFS contains an invalid time")
    stamp = np.datetime64(value, "us").astype(datetime)
    if not isinstance(stamp, datetime):
        raise ProviderError("malformed", "CBOFS time is outside supported datetime range")
    return stamp.replace(tzinfo=UTC)


def _read(variable):
    try:
        return np.asarray(variable)
    except (OSError, RuntimeError) as exc:
        raise ProviderError("unavailable", f"CBOFS variable {variable.name} could not be read") from exc


def _valid_value(value, variable) -> bool:
    # NOAA regular-grid metadata declares -99999; also honor any explicit fill encoding.
    if not np.isfinite(value) or value == -99999:
        return False
    for metadata in (variable.attrs, variable.encoding):
        for key in ("_FillValue", "missing_value"):
            if key in metadata and np.any(value == np.asarray(metadata[key])):
                return False
    return True


class CBOFSSampler:
    """Nearest wet cell within the supplied grid domain; no extrapolation beyond standard layers."""
    dimensions = {"Latitude": ("ny", "nx"), "Longitude": ("ny", "nx"), "mask": ("ny", "nx"),
                  "Depth": ("Depth",), "time": ("time",), "zetatomllw": ("time", "ny", "nx"),
                  "u_eastward": ("time", "Depth", "ny", "nx"), "v_northward": ("time", "Depth", "ny", "nx")}
    required = set(dimensions)

    def sample(self, dataset: xr.Dataset, latitude: float, longitude: float, *, depth_m: float,
               issued_at: datetime, as_of: datetime) -> list[CBOFSForecast]:
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and np.isfinite(depth_m) and depth_m >= 0):
            raise ValueError("latitude/longitude or requested depth is outside its valid range")
        missing = self.required.difference(dataset.variables)
        if missing:
            raise ProviderError("malformed", f"CBOFS dataset lacks variables: {', '.join(sorted(missing))}")
        for name, dims in self.dimensions.items():
            if dataset[name].dims != dims or any(dataset.sizes[d] == 0 for d in dims):
                raise ProviderError("malformed", f"CBOFS {name} has unsupported dimensions")
            if name != "time" and dataset[name].dtype.kind not in "fiub":
                raise ProviderError("malformed", f"CBOFS {name} must contain numeric values")
        units = {"Latitude": {"degrees_north"}, "Longitude": {"degrees_east"}, "Depth": METRES,
                 "zetatomllw": METRES, "u_eastward": VELOCITY_UNITS, "v_northward": VELOCITY_UNITS}
        for name, supported in units.items():
            if dataset[name].attrs.get("units") not in supported:
                raise ProviderError("malformed", f"CBOFS {name} units are missing or unsupported")
        if dataset.Depth.attrs.get("positive") != "down":
            raise ProviderError("malformed", "CBOFS standard depths must be positive down")
        if issued_at.tzinfo is None or as_of.tzinfo is None:
            raise ValueError("issued_at and as_of must be timezone-aware")
        issued = issued_at.astimezone(UTC)
        if issued > as_of.astimezone(UTC):
            raise ProviderError("unavailable", f"CBOFS cycle {issued.isoformat()} was issued after replay time")

        lat, lon = _read(dataset.Latitude), _read(dataset.Longitude)
        if (not np.isfinite(lat).all() or not np.isfinite(lon).all()
                or np.any(abs(lat) > 90) or np.any(abs(lon) > 180)):
            raise ProviderError("malformed", "CBOFS grid coordinates are invalid")
        if not (lat.min() <= latitude <= lat.max() and lon.min() <= longitude <= lon.max()):
            raise ProviderError("no_data", "Requested location lies outside the CBOFS subset domain")
        wet = _read(dataset["mask"]) == 1
        distance2 = (lat - latitude) ** 2 + ((lon - longitude) * np.cos(np.deg2rad(latitude))) ** 2
        distance2[~wet] = np.inf
        if not np.isfinite(distance2).any():
            raise ProviderError("no_data", "CBOFS subset contains no wet grid cell")
        y, x = np.unravel_index(np.argmin(distance2), distance2.shape)
        depths = _read(dataset.Depth).astype(float)
        if not np.isfinite(depths).all() or np.any(depths < 0) or np.any(np.diff(depths) <= 0):
            raise ProviderError("malformed", "CBOFS standard depths must be finite and strictly increasing")
        matches = np.flatnonzero(np.isclose(depths, depth_m, rtol=0, atol=1e-6))
        if len(matches) != 1:
            raise ProviderError(
                "no_data",
                "Requested depth does not exactly match one CBOFS standard layer; a nearby layer is not substituted",
            )
        z = int(matches[0])
        raw_times = _read(dataset.time)
        if raw_times.dtype.kind != "M":
            raise ProviderError("malformed", "CBOFS times must be decoded datetime coordinates")
        times = [_utc(t) for t in raw_times]
        if any(a >= b for a, b in zip(times, times[1:])):
            raise ProviderError("malformed", "CBOFS times must be unique and increasing")
        # Load each selected time series once, not one native network read per time/component.
        variables = [dataset[name].isel(Depth=z, ny=y, nx=x) for name in ("u_eastward", "v_northward")]
        variables.append(dataset.zetatomllw.isel(ny=y, nx=x))
        values = [_read(variable) for variable in variables]
        result, omitted = [], []
        for n, valid_at in enumerate(times):
            u, v, level = [float(series[n]) for series in values]
            if not all(_valid_value(value, variable) for value, variable in zip((u, v, level), variables)):
                omitted.append(valid_at)
                continue
            result.append(CBOFSForecast(valid_at_utc=valid_at, issued_at_utc=issued,
                current_speed_kt=hypot(u, v) * MPS_TO_KT,
                current_toward_true_deg=(degrees(atan2(u, v)) + 360) % 360,
                water_level_mllw_ft=level * M_TO_FT, depth_m=float(depths[z]),
                grid_latitude=float(lat[y, x]), grid_longitude=float(lon[y, x])))
        if not result:
            raise ProviderError("no_data", "CBOFS has no available values at the selected cell/layer")
        return [replace(row, omitted_times_utc=tuple(omitted)) for row in result]


def open_subset(url: str) -> xr.Dataset:
    """Open lazily; caller must close and enforce a total worker deadline.

    Native requests have a fixed timeout. No retries/cache/stale fallback are claimed.
    Do not run native NetCDF access from concurrent API threads (Unidata thread-safety guidance).
    """
    if current_thread() is not main_thread():
        raise ProviderError("unavailable", "CBOFS NetCDF access requires an isolated main-thread worker")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ProviderError("malformed", "CBOFS source URL is malformed") from exc
    if parsed.scheme:
        if (parsed.scheme != "https" or parsed.hostname != "opendap.co-ops.nos.noaa.gov"
                or port not in (None, 443) or parsed.username or parsed.password
                or not parsed.path.startswith(("/thredds/dodsC/NOAA/CBOFS/", "/threddsdev/dodsC/NOAA/CBOFS/"))):
            raise ProviderError("unavailable", "CBOFS remote source must be a NOAA HTTPS CBOFS dataset")
        netCDF4.rc_set("HTTP.TIMEOUT", str(HTTP_TIMEOUT_S))
    try:
        return xr.open_dataset(url, engine="netcdf4", drop_variables=["temp", "salt"], cache=True)
    except (OSError, ValueError) as exc:
        raise ProviderError("unavailable", f"CBOFS dataset could not be opened: {exc}") from exc
