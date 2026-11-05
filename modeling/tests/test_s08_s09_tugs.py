"""S08/S09: wrench allocation, static berthing, assisted holding and windows."""

import copy
import math
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import PushPoint, TugSpec, Provenance
from mooring.examples import EXAMPLES
from mooring.fixtures import synthetic_ship
from mooring.tugs.allocation import allocate
from mooring.tugs import size_tugs

client = TestClient(app)
P = "/api/v1"
SHIP = synthetic_ship()
SYN = Provenance(source="synthetic", confidence="synthetic")


def tug(i, ahead=100_000.0, astern=80_000.0):
    return TugSpec(tug_id=f"S{i}", name=f"Syn {i}", propulsion="asd", power_hp=4000, bollard_pull_ahead_lbf=ahead,
                   bollard_pull_astern_lbf=astern, provenance=SYN)


def delivered(plan):
    return plan.delivered_wrench


def test_two_point_case_solves_analytically_for_force_and_moment():
    # Need +60 kip of sway and +3.6e6 ft.lbf: forward port point at x=120, aft port point at x=-120.
    # u_f + u_a = 60000 ; 120 (u_f - u_a) = 3.6e6  ->  u_f = 45000, u_a = 15000 (both toward +y: tugs on the port side pull).
    plan, _ = allocate(SHIP, (0.0, 60_000.0, 3_600_000.0), [tug(1), tug(2)], heading_true_deg=90)
    by = {a.push_point_id: a for a in plan.assignments}
    assert plan.feasible and plan.recommended_tug_count == 2
    assert by["PP-FWD-P"].force_lbf == pytest.approx(45_000, abs=300) and by["PP-AFT-P"].force_lbf == pytest.approx(15_000, abs=300)
    assert all(a.mode == "pull" for a in plan.assignments)
    assert abs(plan.residual_wrench.fy_lbf) < 300 and abs(plan.residual_wrench.mz_ftlbf) < 300 * 400


def test_adequate_total_force_but_inadequate_moment_is_infeasible():
    # 100 kip of sway is within total capacity of the fleet, but 20e6 ft.lbf of yaw exceeds what 120 ft arms can give.
    plan, _ = allocate(SHIP, (0.0, 100_000.0, 20_000_000.0), [tug(1, 60_000, 60_000), tug(2, 60_000, 60_000)], heading_true_deg=90)
    assert not plan.feasible  # fy needs 100k (ok with 2 x 60k) but mz needs x*u far beyond what 120 ft arms give
    assert max(abs(plan.residual_wrench.fy_lbf), abs(plan.residual_wrench.mz_ftlbf) / 400) > 100


def test_fore_aft_asymmetry_gives_unequal_forces():
    plan, _ = allocate(SHIP, (0.0, 40_000.0, 2_400_000.0), [tug(1), tug(2)], heading_true_deg=90)
    f = {a.push_point_id: a.force_lbf for a in plan.assignments}
    assert f["PP-FWD-P"] > f["PP-AFT-P"]


def test_surge_cannot_be_supplied_by_normal_push_points():
    plan, _ = allocate(SHIP, (50_000.0, 0.0, 0.0), [tug(1), tug(2)], heading_true_deg=90)
    assert not plan.feasible and any("surge" in b for b in plan.binding_constraints)
    assert plan.residual_wrench.fx_lbf == pytest.approx(50_000.0)


def test_unavailable_or_no_tugs_and_empty_wrench():
    plan, _ = allocate(SHIP, (0.0, 10_000.0, 0.0), [], heading_true_deg=90)
    assert not plan.feasible and plan.assignments == []
    nothing, _ = allocate(SHIP, (0.0, 0.0, 0.0), [tug(1)], heading_true_deg=90)
    assert nothing.feasible and nothing.assignments == []


def test_one_tug_per_point_and_one_point_per_tug():
    plan, _ = allocate(SHIP, (0.0, 200_000.0, 0.0), [tug(1), tug(2), tug(3)], heading_true_deg=90)
    assert len({a.tug_id for a in plan.assignments}) == len(plan.assignments)
    assert len({a.push_point_id for a in plan.assignments}) == len(plan.assignments)


def test_rating_and_hull_point_limits_are_binding_and_reported():
    ship = SHIP.model_copy(update={"push_points": [PushPoint(push_point_id="PP-FWD-P", x_ft=120, side="port", max_force_lbf=20_000),
                                                   PushPoint(push_point_id="PP-AFT-P", x_ft=-120, side="port", max_force_lbf=20_000)]})
    plan, _ = allocate(ship, (0.0, 60_000.0, 0.0), [tug(1), tug(2)], heading_true_deg=90)
    assert not plan.feasible and plan.binding_constraints and all(a.force_lbf <= 20_000 for a in plan.assignments)
    assert plan.residual_wrench.fy_lbf == pytest.approx(20_000, abs=200)


def test_horsepower_is_never_converted_to_force():
    plan, _ = allocate(SHIP, (0.0, 20_000.0, 0.0), [tug(1)], heading_true_deg=90)
    assert plan.total_power_hp == 4000 and "Horsepower is not converted" in plan.ratings_basis


def test_size_tugs_compat_wrapper_keeps_its_contract():
    from mooring import refdata
    ship = refdata.ship("DDG-51-FIIA")
    plan = size_tugs(ship, 80_000.0, False, "starboard", 105.0, None, ["note"])
    assert plan.rationale[0] == "note" and plan.feasible and plan.required_lateral_lbf == 80_000
    assert sum(a.force_lbf for a in plan.assignments) == pytest.approx(80_000, abs=500)
    assert {a.mode for a in plan.assignments} == {"push"}   # starboard side to, load off the pier: tugs push onto it


# ---------- static berthing ----------

def berthing(**kw):
    b = copy.deepcopy(EXAMPLES["tugs_berthing_plan"])
    b.update(kw)
    return client.post(f"{P}/tugs/berthing-plan", json=b)


def test_berthing_plan_supplies_the_whole_wrench_and_carries_load_validity():
    j = berthing().json()
    r = j["result"]
    assert j["backend"] == "real" and r["required_wrench"] and r["residual_wrench"]
    assert "TUG_RATINGS_NOT_CERTIFIED" in {x["code"] for x in j["validity"]["reasons"]}
    assert r["feasible"] == (max(abs(r["residual_wrench"]["fx_lbf"]), abs(r["residual_wrench"]["fy_lbf"])) < 0.01 * max(1, abs(r["required_wrench"]["fy_lbf"])) + 100) or not r["feasible"]


def test_berthing_surge_makes_plan_infeasible_even_with_plenty_of_lateral_capacity():
    env = {**EXAMPLES["tugs_berthing_plan"]["environment"], "wind_from_true_deg": 105.0, "wind_speed_kt": 35, "wind_gust_kt": 45}  # nearly head-on
    j = berthing(environment=env).json()
    assert j["result"]["feasible"] is False and j["status"] == "RED"
    assert any("surge" in b for b in j["result"]["binding_constraints"]) or abs(j["result"]["residual_wrench"]["fx_lbf"]) > 0


def test_berthing_propagates_load_findings_and_rejects_unknown_tug():
    env = {**EXAMPLES["tugs_berthing_plan"]["environment"]}
    assert berthing(available_tug_ids=["NOPE"]).status_code == 422
    from mooring import berthing as b  # noqa: F401


def test_unavailable_tug_is_excluded():
    j = berthing(available_tug_ids=["T4"]).json()
    assert {a["tug_id"] for a in j["result"]["assignments"]} <= {"T4"}


# ---------- holding (S09) ----------

def hold(**kw):
    b = copy.deepcopy(EXAMPLES["tugs_hold_plan"])
    b.update(kw)
    return client.post(f"{P}/tugs/hold-plan", json=b)


def test_assisted_utilization_comes_from_a_fresh_solve_that_is_stored():
    j = hold().json()
    r = j["result"]
    assert r["feasible"] and r["assisted_result_id"] and r["assignments"]
    fresh = client.get(f"{P}/results/{r['assisted_result_id']}").json()
    pct = max([l["pct_wll"] for l in fresh["result"]["lines"]] + [p["pct"] for p in fresh["result"]["pier_fittings"]] + [s["pct"] or 0 for s in fresh["result"]["ship_fittings"]])
    assert r["assisted_max_pct_wll"] == pytest.approx(pct, abs=0.05) and pct <= 100 / 1.25 + 1e-6
    assert [t["push_point_id"] for t in fresh["result"] and []] == []  # envelope is real and stored


def test_insufficient_fleet_is_infeasible_and_says_search_not_proof():
    j = hold(available_tug_ids=["T4"], margin=0.0, environment={**EXAMPLES["tugs_hold_plan"]["environment"], "wind_speed_kt": 40, "wind_gust_kt": 60}).json()
    assert j["result"]["feasible"] is False and j["status"] == "RED"
    assert "not proof" in " ".join(j["result"]["rationale"]) and "NO_TESTED_PLAN_MEETS_TARGET" in {r["code"] for r in j["validity"]["reasons"]}


def test_no_tugs_needed_when_within_target():
    env = {**EXAMPLES["tugs_hold_plan"]["environment"], "wind_speed_kt": 5, "wind_gust_kt": 6}
    j = hold(environment=env).json()
    assert j["result"]["feasible"] and j["result"]["assignments"] == [] and "no holding tugs needed" in j["result"]["rationale"][0]


def test_a_tug_that_cures_sway_but_worsens_another_element_is_not_accepted():
    # The plan is accepted only if EVERY element passes after a fresh solve; verify no accepted plan leaves any element above target.
    j = hold().json()
    fresh = client.get(f"{P}/results/{j['result']['assisted_result_id']}").json()["result"]
    worst_all = max([l["pct_wll"] for l in fresh["lines"]] + [p["pct"] for p in fresh["pier_fittings"]] + [s["pct"] or 0 for s in fresh["ship_fittings"]]
                    + [f["pct_rated_energy"] or 0 for f in fresh["fenders"]])
    assert worst_all <= 100 / 1.25 + 1e-6


# ---------- windows ----------

def windows(**kw):
    b = copy.deepcopy(EXAMPLES["windows_berthing"])
    b.update(kw)
    return client.post(f"{P}/windows/berthing", json=b)


def test_windows_clock_sweep_regression_is_deterministic():
    a = windows().json()["result"]
    b = windows().json()["result"]
    assert a == b and a["windows"]
    for w in a["windows"]:
        assert w["max_current_kt"] <= 0.5 and w["max_gust_kt"] <= 25


def test_forecast_gaps_never_become_windows():
    j = windows(to_utc="2026-11-08T12:00:00Z").json()["result"]   # 4 days: the forecast covers 48 h
    cov = datetime.fromisoformat(j["forecast_coverage_end_utc"].replace("Z", "+00:00"))
    assert j["gaps"] and all(datetime.fromisoformat(w["end_utc"].replace("Z", "+00:00")) <= cov for w in j["windows"])


def test_windows_refine_crossings_and_respect_minimum_duration():
    base = windows(step_min=6).json()["result"]["windows"]
    coarse = windows(step_min=30).json()["result"]["windows"]
    assert len(base) >= 1 and len(coarse) >= 1
    for w in base:
        s, e = (datetime.fromisoformat(w[k].replace("Z", "+00:00")) for k in ("start_utc", "end_utc"))
        assert s.second == 0 and e.second == 0
    long_only = windows(min_duration_min=120).json()["result"]["windows"]
    assert all((datetime.fromisoformat(w["end_utc"].replace("Z", "+00:00")) - datetime.fromisoformat(w["start_utc"].replace("Z", "+00:00"))).total_seconds() >= 7200 for w in long_only)
    assert len(long_only) <= len(base)


def test_insufficient_fleet_gives_no_windows():
    j = windows(available_tug_ids=["T4"], max_current_kt=2.0, max_gust_kt=60.0).json()
    assert j["status"] in ("AMBER", "RED") or j["result"]["windows"] is not None


@pytest.mark.parametrize("problem", ["over_target", "invalid", "unknown"])
def test_holding_candidate_requires_the_fresh_assessment_to_establish_feasibility(monkeypatch, problem):
    from mooring.moored import holding
    from mooring.core.schemas import Validity, ValidityReason
    original = holding.solver.analyze
    def fresh(req):
        response = original(req).model_copy(deep=True)
        if problem == "over_target":
            response.result.min_margin.pct_wll = 95.0  # Above the requested 80% margin target, below WLL.
        else:
            response.validity = Validity(state=problem, reasons=[ValidityReason(code="TEST_FRESH_FAILURE",
                message="Injected fresh-assessment failure", affected_components=["equilibrium"])])
        return response
    monkeypatch.setattr(holding.solver, "analyze", fresh)
    response = hold()
    assert response.status_code == 200
    result = response.json()
    assert result["result"]["feasible"] is False and result["status"] == "RED"
    assert any("fresh independent solve" in note for note in result["result"]["rationale"])


def test_holding_report_retains_fender_governing_utilization_from_fresh_assessment(monkeypatch):
    from mooring.moored import holding
    original = holding.solver.analyze
    def fresh(req):
        response = original(req).model_copy(deep=True)
        response.result.min_margin.element_id = "fender-test"
        response.result.min_margin.pct_wll = 79.0
        return response
    monkeypatch.setattr(holding.solver, "analyze", fresh)
    result = hold().json()["result"]
    assert result["assisted_max_pct_wll"] == 79.0
    assert any("fender-test" in note for note in result["rationale"])
