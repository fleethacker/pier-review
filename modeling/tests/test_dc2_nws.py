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


def test_ongoing_period_is_clipped_and_split_at_gust_and_direction_changes():
    grid = json.loads(json.dumps(GRID))
    props = grid["properties"]
    props["windSpeed"]["values"] = [{"validTime": "2026-11-05T00:00:00Z/P1DT30M", "value": 18.52}]
    props["windDirection"]["values"] = [
        {"validTime": "2026-11-05T00:00:00Z/PT1H30M", "value": 90},
        {"validTime": "2026-11-05T01:30:00Z/P1D", "value": 180},
    ]
    props["windGust"]["values"] = [
        {"validTime": "2026-11-05T00:00:00Z/PT1H", "value": 27.78},
        {"validTime": "2026-11-05T01:00:00Z/P1D", "value": 55.56},
    ]
    rows = adapter(grid).forecast(36, -76, as_of=datetime(2026, 11, 5, 0, 30, tzinfo=UTC), hours=2)
    assert [(row.valid_from_utc.hour, row.valid_from_utc.minute) for row in rows] == [(0, 30), (1, 0), (1, 30)]
    assert [row.speed_kt for row in rows] == pytest.approx([10, 10, 10])
    assert [row.gust_kt for row in rows] == pytest.approx([15, 30, 30])
    assert [row.from_true_deg for row in rows] == [90, 90, 180]
    assert rows[-1].valid_to_utc == datetime(2026, 11, 5, 2, 30, tzinfo=UTC)
    assert all(a.valid_to_utc == b.valid_from_utc for a, b in zip(rows, rows[1:]))


@pytest.mark.parametrize("field,value", [
    ("windSpeed", -1), ("windSpeed", float("nan")), ("windSpeed", True),
    ("windGust", float("inf")), ("windDirection", 361),
])
def test_invalid_component_values_fail_closed(field, value):
    grid = json.loads(json.dumps(GRID))
    grid["properties"][field]["values"][0]["value"] = value
    with pytest.raises(ProviderError, match="Invalid NWS"):
        adapter(grid).forecast(36, -76, as_of=datetime(2026, 11, 5, tzinfo=UTC))


@pytest.mark.parametrize("period", ["2026-11-05T00:00:00/PT1H", "2026-11-05T00:00:00Z/PT0H", "bad", "2026-11-05T00:00:00Z/P1M"])
def test_invalid_periods_are_provider_errors(period):
    grid = json.loads(json.dumps(GRID))
    grid["properties"]["windSpeed"]["values"][0]["validTime"] = period
    with pytest.raises(ProviderError):
        adapter(grid).forecast(36, -76, as_of=datetime(2026, 11, 5, tzinfo=UTC))


def test_missing_gust_field_remains_missing():
    grid = json.loads(json.dumps(GRID))
    del grid["properties"]["windGust"]
    rows = adapter(grid).forecast(36, -76, as_of=datetime(2026, 11, 5, tzinfo=UTC))
    assert rows and all(row.gust_kt is None for row in rows)


def test_overlapping_periods_are_rejected():
    grid = json.loads(json.dumps(GRID))
    grid["properties"]["windSpeed"]["values"].append(grid["properties"]["windSpeed"]["values"][0])
    with pytest.raises(ProviderError, match="Overlapping"):
        adapter(grid).forecast(36, -76, as_of=datetime(2026, 11, 5, tzinfo=UTC))


def test_direction_units_are_validated():
    grid = json.loads(json.dumps(GRID))
    grid["properties"]["windDirection"]["uom"] = "radians"
    with pytest.raises(ProviderError, match="direction units"):
        adapter(grid).forecast(36, -76, as_of=datetime(2026, 11, 5, tzinfo=UTC))


def test_stale_transport_provenance_is_preserved():
    class CachedClient:
        def get(self, url):
            point = "/points/" in url
            return HttpPayload(200, json.dumps(POINT if point else GRID).encode(), {}, stale=not point, age_s=20 if point else 70)
    rows = NWSGridpoint(client=CachedClient()).forecast(36, -76, as_of=datetime(2026, 11, 5, tzinfo=UTC))
    assert all(row.stale and row.cache_age_s == 70 for row in rows)
