"""D1 strict source selection, partial availability and recorded-real replay."""

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from modeling_api.main import app
from mooring import environment
from mooring.environment import live
from mooring.environment.coops import Fetcher, ProviderError
from mooring.environment.replay import ReplayError, load_recorded_real_package, recorded_real_package

FX = Path(__file__).parents[1] / "mooring/environment/fixtures/coops"
PACKAGE = (
    Path(__file__).parents[1]
    / "mooring/environment/fixtures/recorded_real/noaa-coops-norfolk-2026-01-01-v1"
)
BERTH = "NAVSTA-NORFOLK-P12-N"
NOW = datetime(2026, 1, 1, 0, 50, tzinfo=UTC)


def load(name):
    return json.loads((FX / name).read_text())


def recorded_transport(overrides=None, failure=None):
    files = {
        "wind": "wind_8638614.json",
        "water_level": "water_level_8638610.json",
        "currents": "currents_cb0402_bin4.json",
    }

    def transport(url, params, timeout):
        if failure == params["product"]:
            raise TimeoutError(f"{failure} down")
        return 200, json.dumps((overrides or {}).get(params["product"]) or load(files[params["product"]]))

    return transport


@pytest.fixture(autouse=True)
def reset_live():
    yield
    live.configure(None, None)


@pytest.mark.parametrize("value", [None, "", " ", " mock ", "AUTO", "autp", "live"])
def test_missing_blank_and_unknown_source_modes_fail_explicitly(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("MOORING_ENV_SOURCE", raising=False)
    else:
        monkeypatch.setenv("MOORING_ENV_SOURCE", value)
    with pytest.raises(environment.EnvironmentConfigurationError, match="MOORING_ENV_SOURCE"):
        environment.source_mode()


def test_invalid_source_prevents_application_startup(monkeypatch):
    monkeypatch.setenv("MOORING_ENV_SOURCE", "autp")
    with pytest.raises(environment.EnvironmentConfigurationError, match="unsupported"):
        with TestClient(app):
            pass


def test_explicit_mock_is_the_only_mode_that_uses_synthetic_now(monkeypatch):
    monkeypatch.setenv("MOORING_ENV_SOURCE", "mock")
    snapshot = environment.now(BERTH)
    assert snapshot.source == "mock"


def test_auto_falls_back_from_live_to_recorded_real_and_never_mock(monkeypatch):
    monkeypatch.setenv("MOORING_ENV_SOURCE", "auto")
    monkeypatch.setattr(environment, "live_snapshot", lambda *a, **k: (_ for _ in ()).throw(ProviderError("unavailable", "down")))
    monkeypatch.setattr(environment._mock, "now", lambda *a, **k: pytest.fail("auto called synthetic mock"))
    snapshot = environment.now(BERTH)
    assert snapshot.source == "replay" and snapshot.metadata.basis == "observation"
    assert snapshot.valid_at_utc == datetime(2026, 1, 1, 0, 54, tzinfo=UTC)


def test_auto_fails_after_live_and_recorded_rungs_without_mock(monkeypatch):
    monkeypatch.setenv("MOORING_ENV_SOURCE", "auto")
    monkeypatch.setattr(environment, "live_snapshot", lambda *a, **k: (_ for _ in ()).throw(ProviderError("unavailable", "live down")))
    monkeypatch.setattr(environment, "_recorded_latest", lambda *a, **k: (_ for _ in ()).throw(ProviderError("unavailable", "package bad")))
    monkeypatch.setattr(environment._mock, "now", lambda *a, **k: pytest.fail("auto called synthetic mock"))
    with pytest.raises(ProviderError, match="mock is disabled"):
        environment.now(BERTH)


def test_explicit_coops_failure_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("MOORING_ENV_SOURCE", "coops")
    monkeypatch.setattr(environment, "live_snapshot", lambda *a, **k: (_ for _ in ()).throw(ProviderError("unavailable", "live down")))
    monkeypatch.setattr(environment, "_recorded_latest", lambda *a, **k: pytest.fail("coops fell back to replay"))
    with pytest.raises(ProviderError, match="live down"):
        environment.now(BERTH)


@pytest.mark.parametrize(
    "failed,expected",
    [
        ("wind", {"wind": "unavailable", "current": "live", "water_level": "live"}),
        ("currents", {"wind": "live", "current": "unavailable", "water_level": "live"}),
        ("water_level", {"wind": "live", "current": "live", "water_level": "unavailable"}),
    ],
)
def test_each_single_component_outage_is_reported_without_hiding_the_others(failed, expected):
    fetcher = Fetcher(recorded_transport(failure=failed), clock=lambda: NOW, sleep=lambda _: None, retries=0, min_interval_s=0)
    live.configure(fetcher, clock=lambda: NOW)
    status = live.component_availability(BERTH, NOW)
    got = {item.component: item.state for item in status.components[:3]}
    assert got == expected
    assert not status.complete_snapshot_available


def test_stale_observations_remain_unavailable_and_never_become_predictions():
    late = NOW + timedelta(hours=5)
    fetcher = Fetcher(recorded_transport(), clock=lambda: late, sleep=lambda _: None, retries=0, min_interval_s=0)
    live.configure(fetcher, clock=lambda: late)
    status = live.component_availability(BERTH, late)
    current = status.components[:3]
    assert all(item.state == "unavailable" for item in current)
    assert all("stale" in item.reason for item in current)


def test_live_snapshot_never_selects_a_future_observation():
    fetcher = Fetcher(recorded_transport(), clock=lambda: NOW, sleep=lambda _: None, retries=0, min_interval_s=0)
    live.configure(fetcher, clock=lambda: NOW)
    snapshot = live.latest(BERTH)
    assert snapshot.valid_at_utc == datetime(2026, 1, 1, 0, 48, tzinfo=UTC)
    assert snapshot.valid_at_utc <= NOW


def test_stale_provider_cache_is_not_served_as_a_live_snapshot(monkeypatch):
    source = recorded_real_package().source
    monkeypatch.setattr(live, "_source", lambda *args: (source, [], True))
    live.configure(clock=lambda: NOW)
    with pytest.raises(ProviderError, match="stale cache"):
        live.latest(BERTH)


def test_auto_availability_reports_recorded_fallback_with_live_failure_reason(monkeypatch):
    monkeypatch.setenv("MOORING_ENV_SOURCE", "auto")
    late = NOW + timedelta(hours=5)
    fetcher = Fetcher(recorded_transport(), clock=lambda: late, sleep=lambda _: None, retries=0, min_interval_s=0)
    live.configure(fetcher, clock=lambda: late)
    monkeypatch.setattr("mooring.core.envelopes.utcnow", lambda: late)
    status = environment.availability(BERTH)
    assert status.complete_snapshot_available
    assert [item.state for item in status.components[:3]] == ["replay", "replay", "replay"]
    assert all(any("auto fallback from live" in note for note in item.limitations) for item in status.components[:3])


def test_recorded_package_hash_coverage_provenance_and_outside_failure(tmp_path):
    package = recorded_real_package()
    assert package.manifest["coverage"]["record_count"] == 10
    assert package.manifest["revision"].startswith("sha256:")
    snapshot = package.source.at(datetime(2026, 1, 1, 0, 12, tzinfo=UTC), now=datetime(2026, 1, 1, 0, 12, tzinfo=UTC))
    assert snapshot.source == "replay" and snapshot.metadata.basis == "observation"
    assert {item.component for item in snapshot.metadata.components} == {"wind", "current", "water_level"}
    with pytest.raises(ProviderError, match="outside the recorded horizon"):
        environment.replay_snapshot(BERTH, datetime(2025, 12, 31, 23, 59, tzinfo=UTC))

    corrupt = tmp_path / PACKAGE.name
    shutil.copytree(PACKAGE, corrupt)
    (corrupt / "observations.json").write_bytes((corrupt / "observations.json").read_bytes() + b" ")
    with pytest.raises(ReplayError, match="SHA-256"):
        load_recorded_real_package(corrupt)

    metadata_corrupt = tmp_path / f"{PACKAGE.name}-metadata"
    shutil.copytree(PACKAGE, metadata_corrupt)
    manifest_path = metadata_corrupt / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["applicable_berth_ids"].append("YOKOSUKA-FLEET-ACTIVITIES-1")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ReplayError, match="revision"):
        load_recorded_real_package(metadata_corrupt)


def test_recorded_real_scenario_requires_and_enforces_berth_applicability():
    from mooring.core.schemas import EnvScenarioCreate

    scenario = environment.create_scenario(EnvScenarioCreate(
        name="berth-bound recorded observations",
        kind="replay",
        replay_start_utc="2026-01-01T00:00:00Z",
        replay_end_utc="2026-01-01T00:30:00Z",
        replay_source="recorded_real",
    ))
    at = scenario.created_at_utc + timedelta(minutes=12)
    with pytest.raises(ProviderError, match="requires a berth_id"):
        environment.scenario_snapshot(scenario.env_scenario_id, at)
    with pytest.raises(ProviderError, match="not applicable"):
        environment.scenario_snapshot(scenario.env_scenario_id, at, "YOKOSUKA-FLEET-ACTIVITIES-1")
    assert environment.scenario_snapshot(scenario.env_scenario_id, at, BERTH).source == "replay"


@pytest.mark.parametrize(
    "query",
    [
        "speed=0&limit=1",
        "speed=nan&limit=1",
        "interval_s=-1&limit=1",
        "interval_s=nan&limit=1",
        "limit=-1",
        "interval_s=0&limit=0",
    ],
)
def test_env_websocket_rejects_invalid_or_unbounded_hot_loop_controls(query):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/ws/env?{query}") as socket:
                socket.receive_json()
    assert exc.value.code == 4400


@pytest.mark.parametrize("minute,anchor", [(43, 36), (49, 42), (55, 48)])
def test_availability_and_now_agree_when_latest_component_times_differ(monkeypatch, minute, anchor):
    checked = NOW.replace(minute=minute)
    live.configure(Fetcher(recorded_transport(), clock=lambda: checked, sleep=lambda _: None,
                           retries=0, min_interval_s=0), clock=lambda: checked)
    monkeypatch.setenv("MOORING_ENV_SOURCE", "auto")
    monkeypatch.setattr("mooring.core.envelopes.utcnow", lambda: checked)
    status = environment.availability(BERTH)
    snapshot = environment.now(BERTH)
    assert status.complete_snapshot_available
    assert [row.state for row in status.components[:3]] == ["live"] * 3
    assert snapshot.source == "live"
    assert snapshot.valid_at_utc == NOW.replace(minute=anchor)
    # A joined wind time before the cutoff must not hide a future current row.
    for field in ("wind_t", "current_t", "level_t"):
        observed = datetime.strptime(snapshot.metadata.original[field], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        assert observed <= checked


def test_fresh_independent_components_need_not_form_a_complete_snapshot():
    documents = {
        "wind": load("wind_8638614.json"),
        "water_level": load("water_level_8638610.json"),
        "currents": load("currents_cb0402_bin4.json"),
    }
    for component, document in documents.items():
        record = document["data"][0]
        record["t"] = "2026-01-01 00:40" if component == "currents" else "2026-01-01 00:48"
        document["data"] = [record]
    live.configure(Fetcher(recorded_transport(overrides=documents), clock=lambda: NOW,
                           sleep=lambda _: None, retries=0, min_interval_s=0), clock=lambda: NOW)
    status = live.component_availability(BERTH, NOW)
    assert [row.state for row in status.components[:3]] == ["live"] * 3
    assert not status.complete_snapshot_available
    assert all(any("Complete snapshot unavailable" in note for note in row.limitations) for row in status.components[:3])
    with pytest.raises(ProviderError, match="no usable joined"):
        live.latest(BERTH)


def test_auto_replay_age_is_real_but_explicit_historical_replay_keeps_its_clock(monkeypatch):
    from mooring.moored.risk import alert_for

    checked = datetime(2026, 11, 5, 12, tzinfo=UTC)
    monkeypatch.setenv("MOORING_ENV_SOURCE", "auto")
    monkeypatch.setattr("mooring.core.envelopes.utcnow", lambda: checked)
    monkeypatch.setattr(environment, "live_snapshot", lambda *a, **k: (_ for _ in ()).throw(ProviderError("unavailable", "offline")))
    snapshot = environment.now(BERTH)
    assert snapshot.metadata.age_s == (checked - snapshot.valid_at_utc).total_seconds()
    assert alert_for(snapshot, None).stale
    historical = environment.replay_snapshot(BERTH, snapshot.valid_at_utc)
    assert historical.metadata.age_s == 0
    assert not alert_for(historical, None).stale


def test_availability_preserves_acquisition_timestamp_instead_of_reconstructing_it():
    from types import SimpleNamespace

    acquired = NOW - timedelta(minutes=4)
    files = {"wind": "wind_8638614.json", "water_level": "water_level_8638610.json",
             "currents": "currents_cb0402_bin4.json"}

    class Cached:
        def get(self, params):
            return SimpleNamespace(doc=load(files[params["product"]]), stale=False,
                                   age_s=1, retrieved_at_utc=acquired)

    live.configure(Cached(), clock=lambda: NOW)
    first = live.component_availability(BERTH, NOW)
    second = live.component_availability(BERTH, NOW + timedelta(seconds=30))
    assert all(row.retrieved_at_utc == acquired for row in first.components[:3] + second.components[:3])


def test_recorded_availability_age_uses_observation_time_not_alignment_bounds(monkeypatch):
    checked = datetime(2026, 11, 5, 12, tzinfo=UTC)
    monkeypatch.setenv("MOORING_ENV_SOURCE", "replay")
    monkeypatch.setattr("mooring.core.envelopes.utcnow", lambda: checked)
    status = environment.availability(BERTH)
    current = next(row for row in status.components if row.component == "current")
    assert current.valid_to_utc == datetime(2026, 1, 1, 0, 56, tzinfo=UTC)
    assert current.age_s == (checked - current.valid_to_utc).total_seconds()


@pytest.mark.parametrize("bad_component,override", [
    ("wind", {"data": [None]}),
    ("current", {"data": [{"t": "2026-01-01 00:50", "s": "0.3", "d": "90", "b": "1"}]}),
])
def test_malformed_or_wrong_bin_component_preserves_other_availability(bad_component, override):
    product = "currents" if bad_component == "current" else bad_component
    live.configure(Fetcher(recorded_transport(overrides={product: override}), clock=lambda: NOW,
                           sleep=lambda _: None, retries=0, min_interval_s=0), clock=lambda: NOW)
    status = live.component_availability(BERTH, NOW)
    for row in status.components[:3]:
        assert row.state == ("unavailable" if row.component == bad_component else "live")
    assert not status.complete_snapshot_available
    with pytest.raises(ProviderError):
        live.latest(BERTH)
