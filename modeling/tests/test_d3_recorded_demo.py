"""D3 recorded-real package coverage in the offline demonstration."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from scripts.build_recorded_replay import ROOT, render
from scripts.demo_check import verify_recorded_replay


BERTH = "NAVSTA-NORFOLK-P12-N"


def test_recorded_package_matches_its_offline_builder():
    rendered = render()
    assert rendered
    assert all(path.read_bytes() == data for path, data in rendered.items())
    assert all(path.is_relative_to(ROOT) for path in rendered)


def test_demo_replays_recorded_observations_with_component_provenance(monkeypatch):
    monkeypatch.setenv("MOORING_ENV_SOURCE", "mock")
    request = {
        "name": "demo-check recorded NOAA observations",
        "kind": "replay",
        "replay_start_utc": "2026-01-01T00:00:00Z",
        "replay_end_utc": "2026-01-01T00:30:00Z",
        "replay_source": "recorded_real",
    }
    with TestClient(app) as client:
        created = client.post("/api/v1/env/scenarios", json=request)
        assert created.status_code == 201
        scenario = created.json()
        response = client.get(
            "/api/v1/env/now",
            params={"berth_id": BERTH, "env_scenario_id": scenario["env_scenario_id"]},
        )
    assert response.status_code == 200
    detail = verify_recorded_replay(response.json(), scenario)
    assert "NOAA CO-OPS replay" in detail


def test_recorded_demo_package_contains_no_unarchived_nws_values():
    observations_path = next(path for path in render() if path.name == "observations.json")
    text = observations_path.read_text(encoding="utf-8")
    assert "NWS" not in text
    assert "wave_height" not in text


def test_recorded_values_and_interpolation_remain_limited_and_keep_original_times():
    from mooring.environment.replay import recorded_real_package
    from mooring.loads.validity import environment_findings

    source = recorded_real_package().source
    start, end = source.coverage
    at = start
    while at <= end:
        snapshot = source.at(at, now=at)
        findings = environment_findings(snapshot)
        assert not [reason for state, reason in findings if state == "invalid"], at
        assert any(state == "limited" for state, _ in findings)
        for component in snapshot.metadata.components:
            assert component.valid_from_utc <= at <= component.valid_to_utc
            assert any("alignment" in note for note in component.limitations)
        assert snapshot.metadata.original["current_t"].endswith(("02", "08", "14", "20", "26", "32", "38", "44", "50", "56"))
        if at not in {record.t for record in source.records}:
            assert "interpolation_upper_current_t" in snapshot.metadata.original
            assert all(any("Interpolated" in note for note in item.limitations) for item in snapshot.metadata.components)
        at += timedelta(minutes=1)


@pytest.mark.parametrize("at", ["2026-01-01T00:12:00Z", "2026-01-01T00:12:01Z", "2026-01-01T00:17:59Z"])
def test_recorded_replay_is_usable_as_limited_loads_input(at):
    from mooring import environment
    from mooring.core.schemas import LoadsRequest
    from mooring.loads import service

    snapshot = environment.replay_snapshot(BERTH, datetime.fromisoformat(at.replace("Z", "+00:00")))
    response = service.environmental(LoadsRequest(
        ship_class_id="DDG-51-FIIA", loading="full_load", heading_true_deg=105,
        water_depth_ft=46.8, environment=snapshot,
    ))
    assert response.validity.state == "limited"
    assert response.status == "AMBER"
    assert "ENVIRONMENT_COMPONENT_OUTSIDE_VALID_INTERVAL" not in {reason.code for reason in response.validity.reasons}


def test_interpolation_does_not_repair_an_invalid_source_interval():
    from mooring.environment.replay import ReplaySource, Unavailable

    observations_path = next(path for path in render() if path.name == "observations.json")
    raw = json.loads(observations_path.read_text())[:2]
    raw[0]["components"][0]["valid_from_utc"] = "2026-01-01T00:01:00Z"
    snapshot = ReplaySource(raw).at(datetime(2026, 1, 1, 0, 3, tzinfo=UTC))
    assert isinstance(snapshot, Unavailable)
    assert "valid endpoint intervals" in snapshot.reason
