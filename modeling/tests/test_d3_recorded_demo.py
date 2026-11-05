"""D3 recorded-real package coverage in the offline demonstration."""

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
