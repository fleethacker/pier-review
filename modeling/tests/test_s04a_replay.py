"""S04a: deterministic replay from recorded-format fixtures (synthetic values; no network, no wall clock)."""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from mooring.environment.replay import ReplayError, ReplaySource, Unavailable, circular_lerp_deg, parse_time

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def rec(minutes, **kw):
    base = dict(t=(T0 + timedelta(minutes=minutes)).isoformat(), wind_speed_kt=10.0, wind_gust_kt=14.0, wind_from_true_deg=180.0,
                current_speed_kt=0.5, current_set_true_deg=90.0, water_level_ft=2.0, quality="good")
    base.update(kw)
    return base


def test_recorded_fixture_file_replays_identically_across_clocks_and_runs():
    raw = json.loads((Path(__file__).parents[1] / "mooring" / "environment" / "fixtures" / "replay_sample.json").read_text())
    a = ReplaySource(raw).series(T0, T0 + timedelta(hours=1), timedelta(minutes=10), now=T0)
    b = ReplaySource(list(reversed(raw))).series(T0, T0 + timedelta(hours=1), timedelta(minutes=10), now=T0 + timedelta(minutes=30))
    strip = lambda s: [(t, x.model_dump(mode="json", exclude={"metadata"}) if not isinstance(x, Unavailable) else x.reason) for t, x in s]
    assert strip(a) == strip(b)   # input order and the clock do not change the values


def test_normal_interpolation_between_records():
    s = ReplaySource([rec(0, wind_speed_kt=10.0), rec(10, wind_speed_kt=20.0)])
    snap = s.at(T0 + timedelta(minutes=5))
    assert snap.wind_speed_kt == pytest.approx(15.0) and snap.source == "replay" and snap.metadata.basis == "observation"
    assert snap.metadata.vertical_datum == "MLLW" and snap.metadata.wind_averaging_s is None   # never inferred from the interval


def test_direction_interpolates_through_north():
    assert circular_lerp_deg(359.0, 1.0, 0.5) == pytest.approx(0.0, abs=1e-9)
    assert circular_lerp_deg(350.0, 20.0, 0.5) == pytest.approx(5.0)
    assert circular_lerp_deg(10.0, 350.0, 0.25) == pytest.approx(5.0)
    s = ReplaySource([rec(0, wind_from_true_deg=359.0), rec(10, wind_from_true_deg=1.0)])
    assert s.at(T0 + timedelta(minutes=5)).wind_from_true_deg == pytest.approx(0.0, abs=1e-6)


def test_non_utc_input_is_normalized_and_naive_input_is_rejected():
    est = timezone(timedelta(hours=-5))
    s = ReplaySource([rec(0, t=datetime(2026, 3, 1, 7, 0, tzinfo=est).isoformat()), rec(10)])
    assert s.records[0].t == T0
    with pytest.raises(ReplayError, match="no timezone"):
        ReplaySource([rec(0, t="2026-03-01T12:00:00")])


def test_duplicates_and_out_of_order_records():
    s = ReplaySource([rec(10), rec(0), rec(0), rec(10, wind_speed_kt=11.0, quality="suspect")])
    assert [r.t for r in s.records] == [T0, T0 + timedelta(minutes=10)]
    assert any("exact duplicate" in d for d in s.report.dropped)
    assert any("conflicting duplicate" in c for c in s.report.conflicts) and s.records[1].values["wind_speed_kt"] == 10.0  # kept the better quality


def test_missing_fields_and_bad_quality_are_excluded_and_reported():
    s = ReplaySource([rec(0), rec(5, wind_gust_kt=None), rec(10, quality="poor"), rec(15)])
    assert len(s.records) == 2 and len(s.report.dropped) == 2
    assert any("missing wind_gust_kt" in d for d in s.report.dropped) and any("poor quality" in d for d in s.report.dropped)


def test_datum_mismatch_is_rejected_unless_a_conversion_is_given():
    with pytest.raises(ReplayError, match="datum 'NAVD88'"):
        ReplaySource([rec(0, datum="NAVD88")])
    s = ReplaySource([rec(0, datum="NAVD88", water_level_ft=3.0), rec(10, datum="NAVD88", water_level_ft=3.0)], datum_offset_ft={"NAVD88": -0.4})
    assert s.at(T0).water_level_mllw_ft == pytest.approx(2.6)


def test_outage_gap_is_not_interpolated_and_no_synthetic_substitute():
    s = ReplaySource([rec(0), rec(120)], max_gap_s=1800)
    r = s.at(T0 + timedelta(minutes=60))
    assert isinstance(r, Unavailable) and "not interpolated" in r.reason
    grid = s.series(T0, T0 + timedelta(minutes=120), timedelta(minutes=60))
    assert [isinstance(x, Unavailable) for _, x in grid] == [False, True, False]


def test_partial_horizon_coverage_and_stale_cache():
    s = ReplaySource([rec(0), rec(10), rec(20)], stale_after_s=600)
    assert isinstance(s.at(T0 + timedelta(minutes=30)), Unavailable) and isinstance(s.at(T0 - timedelta(minutes=1)), Unavailable)
    assert not isinstance(s.at(T0 + timedelta(minutes=15)), Unavailable)
    stale = s.at(T0 + timedelta(minutes=15), now=T0 + timedelta(minutes=45))
    assert isinstance(stale, Unavailable) and "stale" in stale.reason


def test_averaging_and_height_come_from_metadata_only():
    s = ReplaySource([rec(0, wind_averaging_s=60, gust_duration_s=5, wind_reference_height_m=10, source="station X"), rec(10, wind_averaging_s=60, gust_duration_s=5, wind_reference_height_m=10)])
    m = s.at(T0 + timedelta(minutes=2)).metadata
    assert (m.wind_averaging_s, m.gust_duration_s, m.wind_reference_height_m, m.source) == (60, 5, 10, "station X")


def test_empty_or_unusable_series_is_unavailable_not_an_error():
    s = ReplaySource([rec(0, quality="poor")])
    assert isinstance(s.at(T0), Unavailable) and s.coverage is None


def test_snapshots_feed_the_loads_model_without_conversion_surprises():
    from mooring import refdata
    from mooring.loads import compute_loads
    s = ReplaySource([rec(0, wind_averaging_s=60, wind_reference_height_m=10), rec(10, wind_averaging_s=60, wind_reference_height_m=10)])
    snap = s.at(T0 + timedelta(minutes=5))
    r = compute_loads(refdata.ship("DDG-51-FIIA"), "full_load", 90, snap, 46.8)
    assert r.total.fy_lbf == r.total.fy_lbf   # finite


# ---------- replay scenarios from the recorded fixture ----------

def test_replay_scenario_from_the_recorded_fixture_is_deterministic_and_never_loops():
    from fastapi.testclient import TestClient
    from modeling_api.main import app
    from mooring import environment
    from mooring.core.schemas import EnvScenarioCreate
    c = TestClient(app)
    body = {"name": "fixture replay", "kind": "replay", "replay_start_utc": "2026-03-01T12:00:00Z", "replay_end_utc": "2026-03-01T12:30:00Z", "replay_source": "recorded_fixture"}
    sc = c.post("/api/v1/env/scenarios", json=body)
    assert sc.status_code == 201 and sc.json()["replay_source"] == "recorded_fixture"
    created = datetime.fromisoformat(sc.json()["created_at_utc"].replace("Z", "+00:00"))
    sid = sc.json()["env_scenario_id"]
    a = environment.scenario_snapshot(sid, created + timedelta(minutes=12))
    b = environment.scenario_snapshot(sid, created + timedelta(minutes=12))
    assert a == b and a.source == "replay" and a.valid_at_utc == datetime(2026, 3, 1, 12, 12, tzinfo=UTC)
    direct = ReplaySource(json.loads((Path(__file__).parents[1] / "mooring" / "environment" / "fixtures" / "replay_sample.json").read_text()))
    assert a.wind_speed_kt == pytest.approx(direct.at(datetime(2026, 3, 1, 12, 12, tzinfo=UTC), now=datetime(2026, 3, 1, 12, 12, tzinfo=UTC)).wind_speed_kt)
    from mooring.environment.coops import ProviderError
    with pytest.raises(ProviderError, match="exhausted"):
        environment.scenario_snapshot(sid, created + timedelta(minutes=45))


def test_replay_scenario_outside_the_fixture_or_misused_is_422_and_default_is_unchanged():
    from fastapi.testclient import TestClient
    from modeling_api.main import app
    c = TestClient(app)
    base = {"name": "x", "kind": "replay", "replay_start_utc": "2026-03-01T12:00:00Z", "replay_end_utc": "2026-03-01T12:30:00Z"}
    assert c.post("/api/v1/env/scenarios", json={**base, "replay_start_utc": "2025-01-01T00:00:00Z", "replay_end_utc": "2025-01-01T01:00:00Z", "replay_source": "recorded_fixture"}).status_code == 422
    assert c.post("/api/v1/env/scenarios", json={"name": "steady", "kind": "steady", "replay_source": "recorded_fixture"}).status_code == 422
    legacy = c.post("/api/v1/env/scenarios", json=base)
    assert legacy.status_code == 201 and "replay_source" not in legacy.json()   # inactive addition omitted on the wire


def test_replay_scenario_through_env_now_serves_the_fixture_from_the_scenario_start():
    from fastapi.testclient import TestClient
    from modeling_api.main import app
    c = TestClient(app)
    body = {"name": "r", "kind": "replay", "replay_start_utc": "2026-03-01T12:00:00Z", "replay_end_utc": "2026-03-01T12:10:00Z", "replay_source": "recorded_fixture"}
    sid = c.post("/api/v1/env/scenarios", json=body).json()["env_scenario_id"]
    r = c.get(f"/api/v1/env/now?berth_id=NAVSTA-NORFOLK-P12-N&env_scenario_id={sid}")   # replay time = start + time since creation
    assert r.status_code == 200 and r.json()["source"] == "replay" and r.json()["valid_at_utc"].startswith("2026-03-01T12:00")


@pytest.mark.parametrize('minute', [0, 5])
def test_record_time_does_not_invent_provider_issuance(minute):
    source = ReplaySource([rec(0), rec(10)])
    sample = source.at(T0+timedelta(minutes=minute))
    assert sample.metadata.issued_at_utc is None
    assert sample.valid_at_utc == T0+timedelta(minutes=minute)
    assert sample.metadata.valid_from_utc == T0
    assert sample.metadata.valid_to_utc == T0+timedelta(minutes=10 if minute else 0)
    assert sample.metadata.age_s == minute*60
