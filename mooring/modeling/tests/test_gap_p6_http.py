"""Gap: P6 ultimate gust through POST /api/v1/risk/ultimate-gust WITH a supplied SYNTHETIC capacity basis."""
import copy
import dataclasses

from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import UltimateGustResponse
from mooring.core.schemas.ultimate import UltimateGustRequest
from mooring.examples import EXAMPLES
from mooring.mechanics import equilibrium as eq
from mooring.moored import solver

P = "/api/v1"
client = TestClient(app)
BODY = EXAMPLES["mooring_analyze"]
RATIO = BODY["environment"]["wind_gust_kt"] / BODY["environment"]["wind_speed_kt"]
LINES = [ln["line_number"] for ln in BODY["config"]["lines"]]
HUGE = 1e12


def basis(caps=None):
    caps = caps or {}
    return {"basis_id": "SYNTHETIC-TEST", "evidence_status": "synthetic_test_fixture", "citation": "synthetic test fixture, not a source",
            "wind_basis": "test: as supplied",
            "lines": [{"line_number": n, "ultimate_capacity_lbf": caps.get(n, HUGE), "material_law_max_strain": 10.0, "factors": "none (test)"} for n in LINES]}


def tension_at(v, line):
    req = UltimateGustRequest(**BODY)
    system, sol0, _ = solver.solve_request(req)
    env = system.env.model_copy(update={"wind_speed_kt": v, "wind_gust_kt": v * RATIO})
    s = dataclasses.replace(system, env=env)
    sol = eq.solve(s, sol0.pose)
    assert sol.converged
    return {r.ln.line_number: t for r, st, t in s.line_tensions(sol.pose)}[line]


def post(b, **kw):
    body = copy.deepcopy(BODY)
    body.update(kw)
    if b is not None:
        body["capacity_basis"] = b
    return client.post(f"{P}/risk/ultimate-gust", json=body)


def test_http_threshold_found_with_governing_line():
    v0 = 30.0
    r = post(basis({3: tension_at(v0, 3)}), step_deg=90, tolerance_kt=0.1)
    assert r.status_code == 200, r.text
    m = UltimateGustResponse.model_validate(r.json())
    a = m.result.assessed
    assert a.outcome == "threshold_found" and a.governing_line == "line-3"
    lo, hi = a.bracket_kt
    assert hi - lo <= 0.1 + 1e-9 and lo - 0.05 <= v0 <= hi + 0.05
    assert m.result.basis_id == "SYNTHETIC-TEST" and m.result.validated_rupture_prediction is False
    assert m.validity.state == "limited" and "CAPACITY_BASIS_NOT_SOURCED" in {x.code for x in m.validity.reasons}


def test_http_governing_line_follows_supplied_capacity():
    a = UltimateGustResponse.model_validate(post(basis({4: tension_at(30.0, 4)}), step_deg=90).json()).result.assessed
    assert a.governing_line == "line-4" and abs(a.threshold_wind_kt - 30.0) < 0.5


def test_http_other_component_failed_first_is_indeterminate():
    r = post(basis(), step_deg=90)
    assert r.status_code == 200, r.text
    res = UltimateGustResponse.model_validate(r.json()).result
    assert res.outcome == "indeterminate" and res.governing is None
    fails = [d for d in res.directions if d.outcome == "indeterminate_component_failed_first"]
    assert fails and all(d.stop_elements and d.threshold_wind_kt is None for d in fails)


def test_http_invalid_requests_422():
    b = basis()
    assert post(b, step_deg=0).status_code == 422
    assert post(b, tolerance_kt=-1).status_code == 422
    bad = copy.deepcopy(b)
    bad["lines"][0]["ultimate_capacity_lbf"] = -5
    assert post(bad).status_code == 422
    bad2 = copy.deepcopy(b)
    del bad2["basis_id"]
    assert post(bad2).status_code == 422
    assert post(b, max_search_kt="fast").status_code == 422


def test_http_incomplete_basis_is_unavailable_200():
    b = basis()
    b["lines"] = b["lines"][:-1]
    r = post(b)
    assert r.status_code == 200
    m = UltimateGustResponse.model_validate(r.json())
    assert m.result.outcome == "unavailable" and m.validity.reasons[0].code == "ULTIMATE_CAPACITY_INCOMPLETE"
