"""NWS gridpoint wind forecast adapter (DC2).

The adapter intentionally returns wind components, not an ``EnvironmentSnapshot``:
that schema also requires current and water level.  Composition belongs at the
provider boundary once CBOFS is available; absent components are never filled
with zeroes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from .errors import ProviderError
from .providers import ProviderHttpClient, provider_config

DEFAULT_BASE_URL = "https://api.weather.gov"


@dataclass(frozen=True)
class WindForecast:
    valid_from_utc: datetime
    valid_to_utc: datetime
    issued_at_utc: datetime
    speed_kt: float
    gust_kt: float | None
    from_true_deg: float
    source: str
    original: dict[str, float | str]
    stale: bool = False
    cache_age_s: float = 0.0


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, TypeError, AttributeError):
        raise ProviderError("malformed", f"Invalid timezone-aware NWS timestamp: {value}") from None


def _interval(value: str) -> tuple[datetime, datetime]:
    try:
        start_raw, duration = value.split("/", 1)
        # NWS validTime is ISO-8601; day/hour/minute/second durations are fixed-length here.
        match = re.fullmatch(r"P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?", duration)
        if match is None or not any(match.groups()):
            raise ValueError
        days, hours, minutes, seconds = (float(part or 0) for part in match.groups())
        delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        if delta.total_seconds() <= 0:
            raise ValueError
        start = _time(start_raw)
        return start, start + delta
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise ProviderError("malformed", f"unsupported NWS validTime interval: {value}") from None


def _number(value, name):
    try:
        if isinstance(value, bool):
            raise ValueError
        result = float(value)
        if not math.isfinite(result) or result < 0 or (name == "windDirection" and result > 360):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ProviderError("malformed", f"Invalid NWS {name} value") from None


def _values(properties: dict[str, Any], name: str) -> list[dict[str, Any]]:
    item = properties.get(name)
    if not isinstance(item, dict) or not isinstance(item.get("values"), list):
        raise ProviderError("malformed", f"NWS response lacks {name}.values")
    return item["values"]


def _at(values: list[dict[str, Any]], when: datetime) -> tuple[Any, str] | None:
    for item in values:
        start, end = _interval(item.get("validTime", ""))
        if start <= when < end:
            return item.get("value"), item["validTime"]
    return None


class NWSGridpoint:
    provider_id = "nws"

    def __init__(self, client: ProviderHttpClient | None = None, base_url: str | None = None):
        config = provider_config("nws", default_base_url=DEFAULT_BASE_URL)
        self.base_url = (base_url or config.base_url).rstrip("/")
        self.client = client or ProviderHttpClient("nws")

    def forecast(self, latitude: float, longitude: float, *, as_of: datetime, hours: int = 48) -> list[WindForecast]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if not (math.isfinite(latitude) and -90 <= latitude <= 90 and math.isfinite(longitude) and -180 <= longitude <= 180):
            raise ValueError("latitude/longitude must be finite and in range")
        if type(hours) is not int or not 1 <= hours <= 168:
            raise ValueError("hours must be an integer from 1 to 168")
        point_payload = self.client.get(f"{self.base_url}/points/{latitude:.4f},{longitude:.4f}")
        point = point_payload.json()
        try:
            grid_url = point["properties"]["forecastGridData"]
        except (KeyError, TypeError):
            raise ProviderError("malformed", "NWS point response lacks forecastGridData") from None
        if not isinstance(grid_url, str) or urlparse(grid_url).netloc != urlparse(self.base_url).netloc or urlparse(grid_url).scheme != urlparse(self.base_url).scheme:
            raise ProviderError("malformed", "NWS grid URL does not belong to the configured provider")
        grid_payload = self.client.get(grid_url)
        grid = grid_payload.json()
        props = grid.get("properties") if isinstance(grid, dict) else None
        if not isinstance(props, dict):
            raise ProviderError("malformed", "NWS grid response lacks properties")
        issued = _time(props.get("updateTime", ""))
        cutoff = as_of.astimezone(UTC)
        if issued > cutoff:
            raise ProviderError("unavailable", f"NWS forecast issued {issued.isoformat()} after replay time {cutoff.isoformat()}")

        speed = _values(props, "windSpeed")
        direction = _values(props, "windDirection")
        gust = _values(props, "windGust") if props.get("windGust") is not None else []
        unit = props["windSpeed"].get("uom")
        gust_unit = (props.get("windGust") or {}).get("uom")
        if unit != "wmoUnit:km_h-1" or (gust and gust_unit != "wmoUnit:km_h-1"):
            raise ProviderError("malformed", f"unsupported NWS wind units: {unit}, {gust_unit}")

        if props["windDirection"].get("uom") != "wmoUnit:degree_(angle)":
            raise ProviderError("malformed", "unsupported NWS wind direction units")
        result: list[WindForecast] = []
        horizon = cutoff + timedelta(hours=hours)
        boundaries = {cutoff, horizon}
        for items in (speed, direction, gust):
            intervals = []
            for item in items:
                if not isinstance(item, dict):
                    raise ProviderError("malformed", "NWS forecast period is not an object")
                start, end = _interval(item.get("validTime", ""))
                intervals.append((start, end))
                if end > cutoff and start < horizon:
                    boundaries.update((max(start, cutoff), min(end, horizon)))
            intervals.sort()
            if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
                raise ProviderError("malformed", "Overlapping NWS forecast periods are ambiguous")
        times = sorted(boundaries)
        for start, end in zip(times, times[1:]):
            speed_item = _at(speed, start)
            if speed_item is None or speed_item[0] is None:
                continue
            direction_item = _at(direction, start)
            if direction_item is None or direction_item[0] is None:
                continue
            gust_item = _at(gust, start)
            speed_kmh = _number(speed_item[0], "windSpeed")
            gust_kmh = None if gust_item is None or gust_item[0] is None else _number(gust_item[0], "windGust")
            direction_deg = _number(direction_item[0], "windDirection")
            result.append(WindForecast(
                valid_from_utc=start,
                valid_to_utc=end,
                issued_at_utc=issued,
                speed_kt=speed_kmh / 1.852,
                gust_kt=None if gust_kmh is None else gust_kmh / 1.852,
                from_true_deg=direction_deg % 360,
                source=f"NWS {props.get('gridId', 'gridpoint')}",
                original={
                    "wind_speed_km_h": speed_kmh,
                    "wind_direction_deg": direction_deg,
                    "wind_gust_km_h": "missing" if gust_kmh is None else gust_kmh,
                    "wind_speed_valid_time": speed_item[1],
                    "wind_direction_valid_time": direction_item[1],
                    "wind_gust_valid_time": gust_item[1] if gust_item else "missing",
                },
                stale=point_payload.stale or grid_payload.stale,
                cache_age_s=max(point_payload.age_s, grid_payload.age_s),
            ))
        if not result:
            raise ProviderError("no_data", "NWS returned no complete wind speed/direction periods in the requested horizon")
        return result
