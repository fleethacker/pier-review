"""NWS gridpoint wind forecast adapter (DC2).

The adapter intentionally returns wind components, not an ``EnvironmentSnapshot``:
that schema also requires current and water level.  Composition belongs at the
provider boundary once CBOFS is available; absent components are never filled
with zeroes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

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


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ProviderError("malformed", f"NWS timestamp has no offset: {value}")
    return parsed.astimezone(UTC)


def _interval(value: str) -> tuple[datetime, datetime]:
    try:
        start_raw, duration = value.split("/", 1)
        if not duration.startswith("PT") or not duration.endswith("H"):
            raise ValueError
        hours = float(duration[2:-1])
    except (ValueError, TypeError):
        raise ProviderError("malformed", f"unsupported NWS validTime interval: {value}") from None
    start = _time(start_raw)
    return start, start + timedelta(hours=hours)


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
        point = self.client.get(f"{self.base_url}/points/{latitude:.4f},{longitude:.4f}").json()
        try:
            grid_url = point["properties"]["forecastGridData"]
        except (KeyError, TypeError):
            raise ProviderError("malformed", "NWS point response lacks forecastGridData") from None
        props = self.client.get(grid_url).json().get("properties")
        if not isinstance(props, dict):
            raise ProviderError("malformed", "NWS grid response lacks properties")
        issued = _time(props.get("updateTime", ""))
        cutoff = as_of.astimezone(UTC)
        if issued > cutoff:
            raise ProviderError("unavailable", f"NWS forecast issued {issued.isoformat()} after replay time {cutoff.isoformat()}")

        speed = _values(props, "windSpeed")
        direction = _values(props, "windDirection")
        gust = _values(props, "windGust")
        unit = props["windSpeed"].get("uom")
        gust_unit = props["windGust"].get("uom")
        if unit != "wmoUnit:km_h-1" or gust_unit != "wmoUnit:km_h-1":
            raise ProviderError("malformed", f"unsupported NWS wind units: {unit}, {gust_unit}")

        result: list[WindForecast] = []
        horizon = cutoff + timedelta(hours=hours)
        for item in speed:
            start, end = _interval(item.get("validTime", ""))
            if start < cutoff or start >= horizon or item.get("value") is None:
                continue
            direction_item = _at(direction, start)
            if direction_item is None or direction_item[0] is None:
                continue
            gust_item = _at(gust, start)
            speed_kmh = float(item["value"])
            gust_kmh = None if gust_item is None or gust_item[0] is None else float(gust_item[0])
            result.append(WindForecast(
                valid_from_utc=start,
                valid_to_utc=end,
                issued_at_utc=issued,
                speed_kt=speed_kmh / 1.852,
                gust_kt=None if gust_kmh is None else gust_kmh / 1.852,
                from_true_deg=float(direction_item[0]) % 360,
                source=f"NWS {props.get('gridId', 'gridpoint')}",
                original={
                    "wind_speed_km_h": speed_kmh,
                    "wind_direction_deg": float(direction_item[0]),
                    "wind_gust_km_h": "missing" if gust_kmh is None else gust_kmh,
                    "wind_speed_valid_time": item["validTime"],
                },
            ))
        if not result:
            raise ProviderError("no_data", "NWS returned no complete wind speed/direction periods in the requested horizon")
        return result
