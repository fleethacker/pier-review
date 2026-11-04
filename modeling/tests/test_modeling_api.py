"""Contract tests for the modeling mock server: every endpoint answers with its declared schema."""

import copy

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import (
    AnalyzeResponse,
    ApproachSimResponse,
    BerthingSimResponse,
    ExceedanceResponse,
    RecommendResponse,
    TimelineResponse,
)
from mooring.mock.examples import EXAMPLES

P = "/api/v1"
client = TestClient(app)

JOB_RESULT_MODELS = {
    "mooring.recommend": RecommendResponse,
    "risk.exceedance": ExceedanceResponse,
    "risk.timeline": TimelineResponse,
    "berthing.simulate": BerthingSimResponse,
    "approach.simulate": ApproachSimResponse,
}


def scenario_id() -> str:
    r = client.post(f"{P}/scenarios", json=EXAMPLES["scenario"])
    assert r.status_code == 201, r.text
    return r.json()["scenario_id"]


def finish(accepted: dict) -> dict:
    st = client.get(accepted["status_url"]).json()
    assert st["state"] == "succeeded", st
    JOB_RESULT_MODELS[accepted["kind"]].model_validate(st["result"])
    return st["result"]


@pytest.mark.parametrize("path", [
    "/ships", "/ships/DDG-51-FIIA", "/lines", "/lines/NYLON-DB-7IN", "/berths", "/berths/NAVSTA-NORFOLK-P12-N",
    "/tugs", "/rules", "/health", "/version", "/env/gust-model",
    "/env/now?berth_id=NAVSTA-NORFOLK-P12-N&heading_true_deg=105",
    "/env/forecast?berth_id=NAVSTA-NORFOLK-P12-N&hours=6",
    "/env/history?station=8638614&start_utc=2026-11-01T00:00:00Z&end_utc=2026-11-01T06:00:00Z",
])
def test_gets(path):
    r = client.get(P + path)
    assert r.status_code == 200, r.text
    assert r.headers["X-Mooring-Backend"] == "mock"


SYNC_POSTS = {
    "env_scenario": "/env/scenarios",
    "loads_environmental": "/loads/environmental",
    "loads_polar": "/loads/polar",
    "mooring_analyze": "/mooring/analyze",
    "mooring_envelope": "/mooring/envelope",
    "mooring_tide_sweep": "/mooring/tide-sweep",
    "mooring_sequence": "/mooring/sequence",
    "tugs_berthing_plan": "/tugs/berthing-plan",
    "tugs_hold_plan": "/tugs/hold-plan",
    "windows_berthing": "/windows/berthing",
    "approach_route": "/approach/route",
    "approach_ukc": "/approach/ukc",
    "telemetry_batch": "/telemetry/batch",
}


@pytest.mark.parametrize("name,path", SYNC_POSTS.items())
def test_sync_posts(name, path):
    r = client.post(P + path, json=EXAMPLES[name])
    assert r.status_code in (200, 201, 202), r.text
    body = r.json()
    if "result_id" in body:
        assert body["backend"] == "mock"
        assert client.get(f"{P}/results/{body['result_id']}").status_code == 200


@pytest.mark.parametrize("name,path", [
    ("mooring_recommend", "/mooring/recommend"),
    ("risk_exceedance", "/risk/exceedance"),
    ("risk_timeline", "/risk/timeline"),
    ("approach_simulate", "/approach/simulate"),
])
def test_jobs(name, path):
    r = client.post(P + path, json=EXAMPLES[name])
    assert r.status_code == 202, r.text
    finish(r.json())
    with client.stream("GET", r.json()["events_url"]) as s:
        text = "".join(s.iter_text())
    assert "event: done" in text


def test_berthing_batch_and_series():
    body = copy.deepcopy(EXAMPLES["berthing_simulate"])
    body["scenario_id"] = scenario_id()
    r = client.post(f"{P}/berthing/simulate", json=body)
    assert r.status_code == 202, r.text
    result = finish(r.json())
    assert result["result"]["contact"] is not None
    series = client.get(result["result"]["series_url"]).json()
    assert len(series["frames"]) > 10


def test_interactive_session_ws():
    body = copy.deepcopy(EXAMPLES["berthing_session"])
    body["scenario_id"] = scenario_id()
    sess = client.post(f"{P}/berthing/sessions", json=body).json()
    with client.websocket_connect(sess["ws_url"] + "?limit=3") as ws:
        ws.send_json({"type": "tug_command", "tug_id": "T1", "force_lbf": 50000, "direction_rel_deg": 90})
        frames = [ws.receive_json() for _ in range(3)]
    assert any(f["tugs"] for f in frames)


def test_env_ws():
    with client.websocket_connect("/ws/env?berth_id=NAVSTA-NORFOLK-P12-N&interval_s=0&limit=2") as ws:
        a, b = ws.receive_json(), ws.receive_json()
    assert "wind_speed_kt" in a and "water_level_mllw_ft" in b


def test_alerts_ws():
    sid = scenario_id()
    with client.websocket_connect(f"/ws/alerts?scenario_id={sid}&interval_s=0&limit=1") as ws:
        alert = ws.receive_json()
    assert alert["element_id"].startswith("line-")


def test_analyze_example_is_plausible():
    r = AnalyzeResponse.model_validate(client.post(f"{P}/mooring/analyze", json=EXAMPLES["mooring_analyze"]).json())
    roles = {ln.role for ln in r.result.lines}
    assert {"bow", "breast", "stern", "spring_fwd", "spring_aft"} <= roles
    assert all(ln.length_ft >= 50 for ln in r.result.lines)
    assert r.status in ("GREEN", "AMBER")


def test_unknown_ship_is_404():
    assert client.get(f"{P}/ships/NOPE").status_code == 404


def test_bad_fitting_is_422():
    body = copy.deepcopy(EXAMPLES["mooring_analyze"])
    body["config"]["lines"][0]["pier_fitting_id"] = "NOPE"
    r = client.post(f"{P}/mooring/analyze", json=body)
    assert r.status_code == 422 and "NOPE" in r.text


def test_typo_field_is_rejected():
    body = copy.deepcopy(EXAMPLES["mooring_analyze"])
    body["environment"]["wind_speed_kts"] = 10
    assert client.post(f"{P}/mooring/analyze", json=body).status_code == 422
