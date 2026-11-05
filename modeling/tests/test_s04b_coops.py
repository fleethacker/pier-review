"""S04b: CO-OPS adapter against recorded real responses (fixtures/coops, fetched 4 Nov 2026) and synthetic edge cases.
No network, no wall clock: transport, clock and sleep are injected."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.environment import coops, live
from mooring.environment.coops import Fetcher, ProviderError
from mooring.environment.replay import ReplaySource
from mooring.environment.providers import BreakerState

FX = Path(__file__).parents[1] / "mooring" / "environment" / "fixtures" / "coops"
T0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
END = T0 + timedelta(hours=1)


def L(name):
    return json.loads((FX / name).read_text())


# ---------- request building ----------

def test_request_params_follow_the_documented_api():
    p = coops.request_params("water_level", "8638610", T0, END, datum="MLLW")
    assert p["datum"] == "MLLW" and p["time_zone"] == "gmt" and p["units"] == "english" and p["format"] == "json" and p["begin_date"] == "20260101 00:00"
    c = coops.request_params("currents", "cb0402", T0, END, bin=4)
    assert c["bin"] == "4" and "datum" not in c
    assert coops.request_params("currents_predictions", "cb0402", T0, END, bin=4)["vel_type"] == "speed_dir"


@pytest.mark.parametrize("kw,msg", [
    (dict(product="water_level", station="x", begin=T0, end=END), "requires a datum"),
    (dict(product="water_level", station="x", begin=T0, end=END, datum="NAVD"), "only MLLW"),
    (dict(product="currents", station="x", begin=T0, end=END), "requires a bin"),
    (dict(product="wind", station="x", begin=T0, end=T0), "after begin"),
    (dict(product="wind", station="x", begin=T0, end=T0 + timedelta(days=40)), "limited to 31 days"),
    (dict(product="wind", station="x", begin=T0.replace(tzinfo=None), end=END), "timezone"),
    (dict(product="nope", station="x", begin=T0, end=END), "unsupported product"),
])
def test_invalid_requests_are_rejected_before_any_call(kw, msg):
    with pytest.raises(ProviderError, match=msg) as e:
        coops.request_params(kw.pop("product"), kw.pop("station"), kw.pop("begin"), kw.pop("end"), **kw)
    assert e.value.kind == "invalid_request"


def test_non_utc_begin_end_are_converted_to_gmt():
    from datetime import timezone
    est = timezone(timedelta(hours=-5))
    p = coops.request_params("wind", "8638614", datetime(2025, 12, 31, 19, 0, tzinfo=est), datetime(2025, 12, 31, 20, 0, tzinfo=est))
    assert p["begin_date"] == "20260101 00:00" and p["end_date"] == "20260101 01:00"


# ---------- parsing real fixtures ----------

def test_recorded_responses_parse():
    w = coops.parse_wind(L("wind_8638614.json"))
    assert len(w) == 11 and w[0]["t"] == T0 and w[0]["wind_speed_kt"] == 7.78 and w[0]["wind_from_true_deg"] == 202.0 and w[0]["wind_gust_kt"] == 9.14 and w[0]["quality"] == "good"
    lv = coops.parse_water_level(L("water_level_8638610.json"))
    assert lv[0]["water_level_ft"] == 1.627 and lv[0]["preliminary"] is False
    cu = coops.parse_currents(L("currents_cb0402_bin4.json"))
    assert cu[0]["t"] == T0 + timedelta(minutes=2) and cu[0]["bin"] == "4"
    pr = coops.parse_predictions(L("predictions_8638610.json"))
    assert pr[0]["water_level_ft"] == 1.767
    cp = coops.parse_current_predictions(L("currents_predictions_cb0402_bin4.json"))
    assert cp[0]["current_speed_kt"] == 0.358 and cp[0]["current_set_true_deg"] == 353.0 and cp[0]["depth_ft"] == 21.0


@pytest.mark.parametrize("name,kind", [("error_no_data.json", "no_data"), ("error_missing_datum.json", "bad_request"), ("error_bad_bin.json", "bad_request")])
def test_provider_error_bodies_are_classified(name, kind):
    with pytest.raises(ProviderError) as e:
        coops.parse_wind(L(name))
    assert e.value.kind == kind


def test_bad_quality_missing_fields_and_malformed_rows():
    doc = {"data": [{"t": "2026-01-01 00:00", "s": "5", "d": "10", "g": "7", "f": "0,1"}, {"t": "2026-01-01 00:06", "s": "", "d": "10", "g": "7", "f": "0,0"}]}
    w = coops.parse_wind(doc)
    assert w[0]["quality"] == "suspect" and w[1]["wind_speed_kt"] is None
    for bad in ({"data": [{"t": "garbage", "s": "1"}]}, {"data": [{"t": "2026-01-01 00:00", "s": "abc"}]}, {"nodata": []}, {"data": [{"t": "2026-01-01 00:00", "s": "1", "f": "x"}]}):
        with pytest.raises(ProviderError) as e:
            coops.parse_wind(bad)
        assert e.value.kind == "malformed"


def test_water_level_flags_mark_suspect_and_preliminary_is_disclosed():
    doc = {"data": [{"t": "2026-01-01 00:00", "v": "1.0", "f": "0,0,1,0", "q": "p"}, {"t": "2026-01-01 00:06", "v": "1.1", "f": "0,0,0,0", "q": "p"}]}
    lv = coops.parse_water_level(doc)
    assert [r["quality"] for r in lv] == ["suspect", "good"] and lv[1]["preliminary"] is True


# ---------- joining ----------

def joined():
    w, lv, cu = (coops.parse_wind(L("wind_8638614.json")), coops.parse_water_level(L("water_level_8638610.json")), coops.parse_currents(L("currents_cb0402_bin4.json")))
    return coops.assemble(w, lv, cu, wind_station="8638614", level_station="8638610", current_station="cb0402", bin=4, bin_depth_ft=20.6)


def test_series_are_joined_by_nearest_timestamp_and_the_two_minute_offset_is_tolerated():
    recs, notes = joined()
    assert len(recs) == 10 and recs[0]["current_bin"] == "4" and recs[0]["current_depth_ft"] == 20.6
    assert "cb0402 bin 4" in recs[0]["source"] and "assumed" in recs[0]["source"]
    assert len(notes) == 1 and "2026-01-01T01:00:00" in notes[0]       # the last wind sample has no current sample within tolerance


def test_missing_component_or_gap_drops_the_timestamp_never_interpolates():
    w, lv, cu = coops.parse_wind(L("wind_8638614.json")), coops.parse_water_level(L("water_level_8638610.json")), coops.parse_currents(L("currents_cb0402_bin4.json"))
    gappy = [r for r in cu if not (T0 + timedelta(minutes=20) < r["t"] < T0 + timedelta(minutes=40))]
    recs, notes = coops.assemble(w, lv, gappy, wind_station="a", level_station="b", current_station="c", bin=4)
    dropped = {n[11:16] for n in notes}
    assert {"00:24", "00:30", "00:36"} <= dropped and all("current" in n for n in notes if "00:24" in n)
    assert coops.assemble(w, [], cu, wind_station="a", level_station="b", current_station="c", bin=4)[0] == []


def test_wind_averaging_duration_is_not_inferred_from_the_reporting_interval():
    recs, _ = joined()
    snap = ReplaySource(recs, source_kind="live").at(T0 + timedelta(minutes=12), now=T0 + timedelta(minutes=12))
    assert snap.metadata.wind_averaging_s is None and snap.metadata.gust_duration_s is None and snap.source == "live"
    assert snap.metadata.current_bin == "4" and snap.metadata.current_depth_ft == 20.6 and snap.metadata.vertical_datum == "MLLW"
    assert snap.metadata.original["wind_s"] == "9.52" and snap.metadata.original["current_b"] == "4"


# ---------- fetcher: retries, rate limit, cache, stale policy ----------

class Clock:
    def __init__(self):
        self.t = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += timedelta(seconds=s)


def fetcher(responses, **kw):
    clock = Clock()
    calls = []
    def transport(url, params, timeout):
        calls.append((params, timeout))
        r = responses.pop(0) if len(responses) > 1 else responses[0]
        if isinstance(r, Exception):
            raise r
        return r
    f = Fetcher(transport, clock=clock.now, sleep=clock.sleep, **kw)
    return f, clock, calls


OK = (200, json.dumps({"data": []}))
P = {"product": "wind", "station": "x"}


def test_retries_with_backoff_then_succeeds_and_passes_the_timeout():
    f, clock, calls = fetcher([TimeoutError("slow"), (503, ""), OK], retries=2, backoff_s=1.0, min_interval_s=0.0, timeout_s=7.0)
    assert f.get(P).doc == {"data": []} and len(calls) == 3 and calls[0][1] == 7.0 and clock.slept == [1.0, 2.0]


def test_retry_limit_then_unavailable_with_no_synthetic_fallback():
    f, _, calls = fetcher([TimeoutError("down")], retries=2, min_interval_s=0.0)
    with pytest.raises(ProviderError) as e:
        f.get(P)
    assert e.value.kind == "unavailable" and len(calls) == 3 and "no usable cached data" in str(e.value)


def test_api_error_body_is_not_retried_or_cached():
    f, _, calls = fetcher([(200, json.dumps({"error": {"message": "No data was found."}}))], retries=3, min_interval_s=0.0)
    assert f.get(P).doc["error"] and len(calls) == 1 and not f.cache


def test_minimum_interval_between_calls_is_enforced():
    f, clock, _ = fetcher([OK], min_interval_s=0.5, cache_ttl_s=0.0)
    f.get({"station": "a"}); f.get({"station": "b"})
    assert clock.slept == [0.5]


def test_cache_hit_within_ttl_skips_the_network_and_stale_cache_is_flagged_only_during_an_outage():
    f, clock, calls = fetcher([OK, TimeoutError("down")], cache_ttl_s=300.0, max_stale_s=3600.0, retries=0, min_interval_s=0.0)
    f.get(P)
    assert f.get(P).stale is False and len(calls) == 1
    clock.t += timedelta(seconds=900)                                   # past the TTL, provider now down
    got = f.get(P)
    assert got.stale is True and got.age_s == pytest.approx(900.0)
    clock.t += timedelta(seconds=7200)                                  # beyond max_stale_s
    with pytest.raises(ProviderError) as e:
        f.get(P)
    assert e.value.kind == "unavailable"


def test_non_json_response_is_malformed():
    f, _, _ = fetcher([(200, "<html>")], min_interval_s=0.0)
    with pytest.raises(ProviderError) as e:
        f.get(P)
    assert e.value.kind == "malformed"


def test_coops_fetcher_uses_shared_circuit_breaker():
    f, clock, calls = fetcher([TimeoutError("down"), OK], retries=0, min_interval_s=0.0,
                              breaker_failures=1, breaker_reset_s=30)
    with pytest.raises(ProviderError):
        f.get(P)
    assert f.breaker.state == BreakerState.OPEN
    with pytest.raises(ProviderError, match="circuit breaker"):
        f.get(P)
    assert len(calls) == 1
    clock.t += timedelta(seconds=30)
    assert f.get(P).doc == {"data": []} and f.breaker.state == BreakerState.CLOSED


# ---------- service wiring ----------

client = TestClient(app)
NOW = datetime(2026, 1, 1, 0, 50, tzinfo=UTC)


def recorded_transport(docs=None, fail=False):
    files = {"wind": "wind_8638614.json", "water_level": "water_level_8638610.json", "currents": "currents_cb0402_bin4.json"}
    def t(url, params, timeout):
        if fail:
            raise TimeoutError("provider down")
        return 200, json.dumps((docs or {}).get(params["product"]) or L(files[params["product"]]))
    return t


@pytest.fixture
def coops_mode(monkeypatch):
    monkeypatch.setenv("MOORING_ENV_SOURCE", "coops")
    yield
    live.configure(None, None)


def configure(transport, now=NOW):
    live.configure(Fetcher(transport, clock=lambda: now, sleep=lambda s: None, retries=0, min_interval_s=0.0), clock=lambda: now)


def test_env_now_serves_the_latest_recorded_observation_with_metadata(coops_mode):
    configure(recorded_transport())
    r = client.get("/api/v1/env/now?berth_id=NAVSTA-NORFOLK-P12-N&heading_true_deg=105")
    assert r.status_code == 200
    j = r.json()
    assert j["source"] == "live" and j["metadata"]["current_bin"] == "4" and j["wind_rel_ship_deg"] is not None
    assert j["valid_at_utc"].startswith("2026-01-01T00:54") and j["wind_speed_kt"] > 0
    # CO-OPS supplied an observation time, not an independent publication/issue timestamp.
    assert j["metadata"]["issued_at_utc"] is None and j["metadata"]["age_s"] >= 0


def test_stale_data_is_a_503_not_synthetic_data(coops_mode):
    configure(recorded_transport(), now=NOW + timedelta(hours=5))
    r = client.get("/api/v1/env/now?berth_id=NAVSTA-NORFOLK-P12-N")
    assert r.status_code == 503 and "stale" in r.json()["detail"]


def test_outage_is_a_503_and_no_forecast_provider_is_a_503(coops_mode):
    configure(recorded_transport(fail=True))
    assert client.get("/api/v1/env/now?berth_id=NAVSTA-NORFOLK-P12-N").status_code == 503
    r = client.get("/api/v1/env/forecast?berth_id=NAVSTA-NORFOLK-P12-N&hours=6")
    assert r.status_code == 503 and "not synthesized" in r.json()["detail"]


def test_provider_error_bodies_map_to_service_errors(coops_mode):
    configure(recorded_transport(docs={"wind": L("error_no_data.json")}))
    assert client.get("/api/v1/env/now?berth_id=NAVSTA-NORFOLK-P12-N").status_code == 503
    configure(recorded_transport(docs={"water_level": L("error_missing_datum.json")}))
    assert client.get("/api/v1/env/now?berth_id=NAVSTA-NORFOLK-P12-N").status_code == 502


def test_history_joins_the_three_products_and_rejects_unknown_stations_and_long_windows(coops_mode):
    configure(recorded_transport())
    r = client.get("/api/v1/env/history?station=8638614&start_utc=2026-01-01T00:00:00Z&end_utc=2026-01-01T01:00:00Z")
    assert r.status_code == 200 and len(r.json()["series"]) == 10
    assert client.get("/api/v1/env/history?station=9999999&start_utc=2026-01-01T00:00:00Z&end_utc=2026-01-01T01:00:00Z").status_code == 422
    assert client.get("/api/v1/env/history?station=8638614&start_utc=2025-10-01T00:00:00Z&end_utc=2026-01-01T01:00:00Z").status_code == 422


def test_ws_env_reports_provider_failure_and_does_not_synthesize(coops_mode):
    configure(recorded_transport(fail=True))
    with client.websocket_connect("/ws/env?berth_id=NAVSTA-NORFOLK-P12-N&interval_s=0&limit=1") as ws:
        msg = ws.receive_json()
    assert msg["error"] == "unavailable" and "unavailable" in msg["detail"]


def test_ws_replay_uses_bundled_fixture_with_explicit_synthetic_basis(monkeypatch):
    monkeypatch.delenv("MOORING_ENV_SOURCE", raising=False)
    with client.websocket_connect(
        "/ws/env?berth_id=NAVSTA-NORFOLK-P12-N&mode=replay&replay_start_utc=2026-03-01T12:00:00Z&interval_s=0&limit=1"
    ) as ws:
        msg = ws.receive_json()
    assert msg["source"] == "replay" and msg["metadata"]["source"] == "synthetic recorded-format fixture"
    assert msg["metadata"]["basis"] == "scenario"


def test_version_reports_provider_modes(coops_mode):
    modules = client.get("/api/v1/version").json()["modules"]
    assert modules["Provider NOAA CO-OPS"] == "live"
    assert modules["Provider NWS"].startswith("unavailable")


def test_default_mode_stays_offline_and_deterministic():
    r = client.get("/api/v1/env/now?berth_id=NAVSTA-NORFOLK-P12-N")
    assert r.status_code == 200 and r.json()["source"] == "mock"


def test_malformed_json_is_not_retained_in_provider_cache():
    f, _, calls = fetcher([(200, '<html>'), OK], retries=0, min_interval_s=0)
    with pytest.raises(ProviderError, match='JSON'): f.get(P)
    assert not f.get(P).stale and len(calls) == 2


def test_replay_rejects_naive_time_without_guessing_a_timezone():
    from mooring.environment import replay_snapshot
    with pytest.raises(ProviderError, match='timezone'):
        replay_snapshot('NAVSTA-NORFOLK-P12-N', datetime(2026, 3, 1, 12))


def test_historical_provider_snapshot_is_labeled_replay(coops_mode):
    from mooring.environment import replay_snapshot
    configure(recorded_transport())
    snapshot = replay_snapshot('NAVSTA-NORFOLK-P12-N', datetime(2026, 1, 1, 0, 30, tzinfo=UTC))
    assert snapshot.source == 'replay'
    assert snapshot.metadata.basis == 'observation'
    assert 'NOAA CO-OPS' in snapshot.metadata.source
