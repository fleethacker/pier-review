"""CBOFS regular-grid forecast sampling (DC3)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import atan2, degrees, hypot
from typing import Any

import numpy as np
import xarray as xr

from .errors import ProviderError

MPS_TO_KT = 1.9438444924406
M_TO_FT = 3.2808398950131


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


def _utc(value: Any) -> datetime:
    stamp = np.datetime64(value, "ns").astype("datetime64[us]").astype(datetime)
    return stamp.replace(tzinfo=UTC)


class CBOFSSampler:
    """Sample the nearest wet regular-grid cell and declared standard layer."""
    required = {"Latitude", "Longitude", "mask", "Depth", "time", "zetatomllw", "u_eastward", "v_northward"}

    def sample(self, dataset: xr.Dataset, latitude: float, longitude: float, *, depth_m: float,
               issued_at: datetime, as_of: datetime) -> list[CBOFSForecast]:
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and np.isfinite(depth_m) and depth_m >= 0):
            raise ValueError("latitude/longitude or requested depth is outside its valid range")
        missing = self.required.difference(dataset.variables)
        if missing:
            raise ProviderError("malformed", f"CBOFS dataset lacks variables: {', '.join(sorted(missing))}")
        if issued_at.tzinfo is None or as_of.tzinfo is None:
            raise ValueError("issued_at and as_of must be timezone-aware")
        issued = issued_at.astimezone(UTC)
        if issued > as_of.astimezone(UTC):
            raise ProviderError("unavailable", f"CBOFS cycle {issued.isoformat()} was issued after replay time")

        lat, lon = np.asarray(dataset["Latitude"]), np.asarray(dataset["Longitude"])
        wet = np.asarray(dataset["mask"]) == 1
        distance2 = (lat - latitude) ** 2 + ((lon - longitude) * np.cos(np.deg2rad(latitude))) ** 2
        distance2[~wet] = np.inf
        if not np.isfinite(distance2).any():
            raise ProviderError("no_data", "CBOFS subset contains no wet grid cell")
        y, x = np.unravel_index(np.argmin(distance2), distance2.shape)
        depths = np.asarray(dataset["Depth"], dtype=float)
        z = int(np.argmin(abs(depths - depth_m)))

        result = []
        for n, time_value in enumerate(np.asarray(dataset["time"])):
            u = float(dataset["u_eastward"].isel(time=n, Depth=z, ny=y, nx=x))
            v = float(dataset["v_northward"].isel(time=n, Depth=z, ny=y, nx=x))
            level = float(dataset["zetatomllw"].isel(time=n, ny=y, nx=x))
            if not all(np.isfinite(value) and value > -90000 for value in (u, v, level)):
                continue
            result.append(CBOFSForecast(
                valid_at_utc=_utc(time_value), issued_at_utc=issued,
                current_speed_kt=hypot(u, v) * MPS_TO_KT,
                current_toward_true_deg=(degrees(atan2(u, v)) + 360) % 360,
                water_level_mllw_ft=level * M_TO_FT, depth_m=float(depths[z]),
                grid_latitude=float(lat[y, x]), grid_longitude=float(lon[y, x]),
            ))
        if not result:
            raise ProviderError("no_data", "CBOFS has no qualified values at the selected cell/layer")
        return result


def open_subset(url: str) -> xr.Dataset:
    """Open OPeNDAP lazily; selection loads coordinate grids, then only the chosen data point/layer."""
    return xr.open_dataset(url, engine="netcdf4", drop_variables=["temp", "salt"], cache=True)
