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
