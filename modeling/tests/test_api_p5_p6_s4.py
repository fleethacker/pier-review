"""HTTP exposure of P5 (horsepower plan), P6 (ultimate gust) and S4 (wave surrogate)."""

from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import HorsepowerPlan, UltimateGustResponse, WaveSurrogateResult
from mooring.examples import EXAMPLES

P = "/api/v1"
client = TestClient(app)


def test_horsepower_plan_ok_and_validated():
    ships = client.get(f"{P}/ships").json()
    sid = ships[0].get("class_id") or ships[0]["ship_class_id"]
    w = {"fx_lbf": 0, "fy_lbf": 1000, "mz_ftlbf": 0}
    r = client.post(f"{P}/tugs/horsepower-plan", json={"ship_class_id": sid, "required_wrench": w})
    assert r.status_code == 200, r.text
    assert HorsepowerPlan.model_validate(r.json()).validity == "limited"
    assert client.post(f"{P}/tugs/horsepower-plan", json={"ship_class_id": sid, "required_wrench": w, "available_tug_ids": ["NOPE"]}).status_code == 422
    assert client.post(f"{P}/tugs/horsepower-plan", json={"ship_class_id": sid, "required_wrench": {"fx_lbf": 0}}).status_code == 422
    assert client.post(f"{P}/tugs/horsepower-plan", json={"ship_class_id": "NOPE", "required_wrench": w}).status_code == 404


def test_ultimate_gust_without_basis_is_unavailable_200():
    r = client.post(f"{P}/risk/ultimate-gust", json=EXAMPLES["mooring_analyze"])
    assert r.status_code == 200, r.text
    m = UltimateGustResponse.model_validate(r.json())
    assert m.result.outcome == "unavailable" and m.result.governing is None
    assert m.validity.reasons[0].code == "ULTIMATE_CAPACITY_BASIS_MISSING"


def test_ultimate_gust_invalid_422():
    assert client.post(f"{P}/risk/ultimate-gust", json={}).status_code == 422


SPEC = {"kind": "total", "source": "test", "components": [{"label": "total_sea", "hs_ft": 3.0, "peak_period_s": 8.0}]}


def test_wave_surrogate_ok_deterministic_and_unavailable():
    body = {"seed": 3, "duration_s": 60, "dt_s": 0.5, "spectrum": SPEC}
    a, b = client.post(f"{P}/loads/wave-surrogate", json=body), client.post(f"{P}/loads/wave-surrogate", json=body)
    assert a.status_code == 200 and a.json() == b.json()
    w = WaveSurrogateResult.model_validate(a.json())
    assert w.state == "synthetic" and w.qualified is False
    u = client.post(f"{P}/loads/wave-surrogate", json={"seed": 1})
    assert u.status_code == 200 and u.json()["state"] == "unavailable" and u.json()["series"] is None


def test_wave_surrogate_bounds_422():
    for body in ({"seed": 1, "duration_s": 7200, "spectrum": SPEC}, {"seed": 1, "duration_s": 3600, "dt_s": 0.05, "spectrum": SPEC},
                 {"seed": -1, "spectrum": SPEC}, {"seed": 1, "spectrum": {**SPEC, "components": []}}):
        assert client.post(f"{P}/loads/wave-surrogate", json=body).status_code == 422, body
