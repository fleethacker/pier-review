from datetime import UTC, datetime
import json

import pytest

from mooring.environment.errors import ProviderError
from mooring.environment.nws import NWSGridpoint
from mooring.environment.providers import HttpPayload, HttpPolicy, ProviderHttpClient


POINT = {"properties": {"forecastGridData": "https://api.weather.gov/gridpoints/AKQ/88,56"}}
GRID = {"properties": {
    "gridId": "AKQ/88,56", "updateTime": "2026-11-04T23:38:07+00:00",
    "windSpeed": {"uom": "wmoUnit:km_h-1", "values": [
        {"validTime": "2026-11-05T00:00:00+00:00/PT1H", "value": 18.52},
        {"validTime": "2026-11-05T01:00:00+00:00/PT1H", "value": 37.04}]},
    "windDirection": {"uom": "wmoUnit:degree_(angle)", "values": [
        {"validTime": "2026-11-05T00:00:00+00:00/PT2H", "value": 359}]},
    "windGust": {"uom": "wmoUnit:km_h-1", "values": [
        {"validTime": "2026-11-05T00:00:00+00:00/PT1H", "value": 27.78},
        {"validTime": "2026-11-05T01:00:00+00:00/PT1H", "value": None}]},
}}


def adapter(grid=GRID):
    def transport(url, params, timeout, headers):
        body = POINT if "/points/" in url else grid
        return HttpPayload(200, json.dumps(body).encode(), {})
    client = ProviderHttpClient("nws", policy=HttpPolicy(retries=0, min_interval_s=0), transport=transport)
    return NWSGridpoint(client=client)


def test_gridpoint_parses_units_times_and_missing_gust():
    rows = adapter().forecast(36.9585, -76.3305, as_of=datetime(2026, 11, 5, tzinfo=UTC), hours=2)
    assert len(rows) == 2
    assert rows[0].speed_kt == pytest.approx(10)
    assert rows[0].gust_kt == pytest.approx(15)
    assert rows[0].from_true_deg == 359
    assert rows[1].gust_kt is None
    assert rows[0].original["wind_speed_km_h"] == 18.52


def test_replay_rejects_forecast_issued_in_the_future():
    with pytest.raises(ProviderError, match="after replay time"):
        adapter().forecast(36.9585, -76.3305, as_of=datetime(2026, 11, 4, 23, tzinfo=UTC))


def test_missing_direction_does_not_create_a_value():
    grid = json.loads(json.dumps(GRID))
    grid["properties"]["windDirection"]["values"][0]["value"] = None
    with pytest.raises(ProviderError, match="no complete wind"):
        adapter(grid).forecast(36.9585, -76.3305, as_of=datetime(2026, 11, 5, tzinfo=UTC))


def test_unknown_units_are_rejected():
    grid = json.loads(json.dumps(GRID))
    grid["properties"]["windSpeed"]["uom"] = "wmoUnit:kn"
    with pytest.raises(ProviderError, match="unsupported NWS wind units"):
        adapter(grid).forecast(36.9585, -76.3305, as_of=datetime(2026, 11, 5, tzinfo=UTC))


@pytest.mark.parametrize("value", [-1, "NaN", "not-a-number"])
def test_invalid_wind_values_are_provider_errors(value):
    grid = json.loads(json.dumps(GRID))
    grid["properties"]["windSpeed"]["values"][0]["value"] = value
    with pytest.raises(ProviderError, match="wind speed"):
        adapter(grid).forecast(36.9585, -76.3305, as_of=datetime(2026, 11, 5, tzinfo=UTC))


def test_invalid_issue_time_is_a_provider_error():
    grid = json.loads(json.dumps(GRID))
    grid["properties"]["updateTime"] = "not-a-time"
    with pytest.raises(ProviderError, match="invalid NWS timestamp"):
        adapter(grid).forecast(36.9585, -76.3305, as_of=datetime(2026, 11, 5, tzinfo=UTC))
