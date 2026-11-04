"""Contract tests for the modeling mock server: every endpoint answers with its declared schema."""

import copy
import time
from datetime import UTC, datetime

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
from mooring.examples import EXAMPLES

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


def finish(accepted: dict, timeout_s: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout_s
    st = client.get(accepted["status_url"]).json()
    while st["state"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.01)
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
    assert r.headers["X-Mooring-Backend"] == "mixed"  # M2 and M3 real, the rest mock


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
        real = path.startswith("/loads/") or path in ("/mooring/analyze", "/mooring/envelope", "/mooring/tide-sweep", "/tugs/berthing-plan", "/tugs/hold-plan", "/windows/berthing", "/mooring/sequence")
        assert body["backend"] == ("real" if real else "mock")
        if real:
            assert body["validity"] is not None
            if not path.startswith(("/loads/", "/mooring/", "/tugs/hold")):
                return
            assert body["manifest"]["resolved_inputs_hash"].startswith("sha256:")
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


@pytest.mark.parametrize("hour", range(24))
def test_berthing_batch_and_series(monkeypatch, hour):
    from mooring.environment import mock as env_mock

    monkeypatch.setattr(env_mock, "utcnow", lambda: datetime(2026, 11, 4, hour, tzinfo=UTC))
    scenario = copy.deepcopy(EXAMPLES["scenario"])
    berth = client.get(f"{P}/berths/{scenario['berth_id']}").json()
    # Wind FROM the water side (berth +y) pushes onto the pier, independent of ship side-to.
    env = client.post(f"{P}/env/scenarios", json={
        "name": "Steady onto-pier berthing test", "kind": "steady",
        "wind_speed_kt": 10, "wind_gust_kt": 10,
        "wind_from_true_deg": (berth["face_bearing_true_deg"] + 270) % 360,
        "current_speed_kt": 0,
    })
    assert env.status_code == 201, env.text
    scenario["env_source"] = {"mode": "scenario", "env_scenario_id": env.json()["env_scenario_id"]}
    saved = client.post(f"{P}/scenarios", json=scenario)
    assert saved.status_code == 201, saved.text
    body = copy.deepcopy(EXAMPLES["berthing_simulate"])
    body["scenario_id"] = saved.json()["scenario_id"]
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
    assert {"bow", "stern", "spring_fwd", "spring_aft"} <= roles
    assert all(ln.length_ft >= 50 for ln in r.result.lines)
    # Real equilibrium: the single-part template is overloaded at a 30 kt off-pier gust (a physical finding, not an error).
    assert r.backend == "real" and r.validity.state == "limited" and r.validity.diagnostics.converged
    assert r.status == "RED" and any(f.rule_id == "LINE-WLL" and f.severity == "RED" for f in r.result.findings)


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
