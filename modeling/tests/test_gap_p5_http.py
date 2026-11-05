"""Gap: P5 horsepower plan through POST /api/v1/tugs/horsepower-plan (catalog tugs, real ship catalog)."""
import itertools

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import HorsepowerPlan

P = "/api/v1"
URL = f"{P}/tugs/horsepower-plan"
client = TestClient(app)
SHIP = "DDG-51-FIIA"
SWAY = {"fx_lbf": 0, "fy_lbf": 1000, "mz_ftlbf": 0}


def plan(wrench=SWAY, ship=SHIP, **kw):
    r = client.post(URL, json={"ship_class_id": ship, "required_wrench": wrench, **kw})
    return r


def test_unknown_ship_is_404_and_does_not_leak_a_plan():
    r = plan(ship="NOT-A-SHIP")
    assert r.status_code == 404
    assert "placements" not in r.json()


def test_feasible_plan_is_valid_and_limited():
    r = plan()
    assert r.status_code == 200, r.text
    p = HorsepowerPlan.model_validate(r.json())
    assert p.feasible and p.placements and p.infeasibility_reasons == [] and p.validity == "limited"
    assert p.total_power_hp > 0 and p.tug_count == len(p.placements)
    assert p.load_scale_margin >= 1


@pytest.mark.parametrize("wrench,fragment", [
    ({"fx_lbf": 0, "fy_lbf": 5e6, "mz_ftlbf": 0}, "cannot supply"),
    ({"fx_lbf": 0, "fy_lbf": 1000, "mz_ftlbf": 5e9}, "cannot supply"),
    ({"fx_lbf": 50000, "fy_lbf": 0, "mz_ftlbf": 0}, "Surge"),
])
def test_infeasible_cases_report_reasons_over_http(wrench, fragment):
    r = plan(wrench)
    assert r.status_code == 200, r.text   # infeasibility is a result, not an error
    p = HorsepowerPlan.model_validate(r.json())
    assert not p.feasible and p.placements == [] and p.total_power_hp == 0 and p.tug_count == 0
    assert any(fragment in x for x in p.infeasibility_reasons)
    if fragment == "cannot supply":
        assert p.fleet_scale_margin is not None and p.fleet_scale_margin < 1


def test_restricting_the_fleet_can_make_a_feasible_case_infeasible():
    assert plan({"fx_lbf": 0, "fy_lbf": 150_000, "mz_ftlbf": 0}).json()["feasible"] is True
    r = plan({"fx_lbf": 0, "fy_lbf": 150_000, "mz_ftlbf": 0}, available_tug_ids=["T4"])
    assert r.status_code == 200 and r.json()["feasible"] is False and r.json()["infeasibility_reasons"]


def test_same_request_twice_is_identical():
    base = plan().json()
    assert plan().json() == base
    assert plan(available_tug_ids=["T3", "T2"]).json() == plan(available_tug_ids=["T3", "T2"]).json()


XFAIL_ORDER = ("BUG: documented tie-break is lexicographic (tug_id, push_point_id) but the chosen placement depends on the "
               "order of available_tug_ids: equal-hp mirror assignments T2@PP-AFT-P+T3@PP-FWD-P vs T2@PP-FWD-P+T3@PP-AFT-P")


@pytest.mark.xfail(strict=True, reason=XFAIL_ORDER)
def test_fleet_order_does_not_matter():
    results = []
    for perm in itertools.permutations(["T2", "T3", "T4"]):
        r = plan(available_tug_ids=list(perm))
        assert r.status_code == 200
        results.append(r.json())
    assert all(x == results[0] for x in results)


@pytest.mark.xfail(strict=True, reason=XFAIL_ORDER)
def test_equal_horsepower_tie_is_broken_by_documented_rule_deterministically():
    # T2 and T3 are both 4000 hp. Whatever the request order, the same plan is chosen, and it is stable on repeat.
    a = plan(available_tug_ids=["T2", "T3"]).json()
    b = plan(available_tug_ids=["T3", "T2"]).json()
    assert a == b and plan(available_tug_ids=["T2", "T3"]).json() == a
    assert "lexicographic" in a["tie_break"] and a["tie_break"].startswith("lowest total hp")
    if a["feasible"]:
        ids = [p["tug_id"] for p in a["placements"]]
        assert ids == sorted(ids)


def test_validation_errors_422():
    assert plan(available_tug_ids=["NOPE"]).status_code == 422
    assert plan({"fx_lbf": 0}).status_code == 422
    assert plan(efficiency=0).status_code == 422
    assert plan(margin=2).status_code == 422
    assert plan(available_tug_ids=[f"T{i}" for i in range(9)]).status_code == 422
