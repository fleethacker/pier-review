"""S12: constrained plan search, checked against an independent brute force on a small synthetic fixture."""

import copy
import itertools
import time

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import EnvironmentSnapshot, MooringConfig, MooringLine
from mooring.examples import EXAMPLES
from mooring.fixtures import calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship
from mooring.moored import equilibrium as eq
from mooring.moored import search as S
from mooring.moored.envelopes_real import utilization
from mooring.rules.nstm582 import design_factor

client = TestClient(app)
P = "/api/v1"
SHIP, BERTH, SPEC = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
SPECS = {SPEC.spec_id: SPEC}
SLOTS = [S.Slot(1, "BITT-1@", "breast", 0.0), S.Slot(2, "BITT-4@", "breast", 0.0), S.Slot(3, "BITT-2@", "spring_aft", -60.0), S.Slot(4, "BITT-3@", "spring_fwd", 60.0)]


def off_pier_env(kt: float) -> EnvironmentSnapshot:
    # synthetic berth face bearing 90, starboard side to: heading 90, pier is to the south (bearing 180): wind from 180 pushes off? no:
    # wind FROM the pier side (bearing 180) blows toward the water.
    return calm_env().model_copy(update={"wind_speed_kt": kt, "wind_gust_kt": kt, "wind_from_true_deg": 180.0})


def run(cases, **kw):
    args = dict(side_to="starboard", ship_x_ft=400.0, loading="full_load", mst="II", neighbors=3, max_evals=5000, standoff_ft=10.0)
    args.update(kw)
    return S.search_plans(SHIP, BERTH, SPECS, SLOTS, cases, **args)


def brute_force(cases, neighbors=3):
    """Independent enumeration: every combination of the nearest fittings, evaluated directly with the solver."""
    out = S.Outcome  # noqa: F841
    sets = []
    for slot in SLOTS:
        bitt, opts = S._slot_options(SHIP, BERTH, slot, "starboard", 400.0, set(), neighbors, "S")
        sets.append((bitt, opts[:neighbors]))
    best = None
    df = design_factor("II")
    count_feasible = 0
    for (choice, pname) in itertools.product(itertools.product(*[o for _, o in sets]), S.PATTERNS):
        if len(set(choice)) != len(choice):
            continue
        lines = [MooringLine(line_number=s.line_number, role=s.role, spec_id=SPEC.spec_id, parts=S.PATTERNS[pname](s.role, s.line_number), ship_fitting_id=b.fitting_id, pier_fitting_id=pf)
                 for s, (b, _), pf in zip(SLOTS, sets, choice)]
        cfg = MooringConfig(side_to="starboard", ship_x_ft=400.0, standoff_ft=10.0, lines=lines)
        from mooring.core.geometry import line_geometry
        if any(line_geometry(l, SHIP, BERTH, cfg, 0.0).length_ft > S.MAX_LINE_FT or (l.role == "breast" and line_geometry(l, SHIP, BERTH, cfg, 0.0).horiz_angle_deg >= 45) for l in lines):
            continue
        worst, ok = 0.0, True
        for _, env in cases:
            sysm = eq.build_system(SHIP, BERTH, cfg, SPECS, env, loading="full_load", lines_wet=True, install_water_level_ft=0.0)
            sol = eq.solve(sysm)
            if not sol.converged:
                ok, worst = False, float("inf")
                break
            pct = max(p for _, p, _ in utilization(sysm, sol.pose, df))
            worst = max(worst, pct); ok = ok and pct <= 100
        count_feasible += ok
        key = (0 if ok else 1, worst)
        best = key if best is None or key < best else best
    return best, count_feasible


def test_exhaustive_search_matches_independent_brute_force_optimum_and_feasible_count():
    cases = [("calm+wind", off_pier_env(20.0))]
    o = run(cases)
    assert o.strategy == "exhaustive" and o.complete and o.evaluated > 10
    bf_best, bf_feasible = brute_force(cases)
    top = o.ranked[0]
    assert (top[0][0], top[0][1]) == pytest.approx(bf_best)
    assert sum(1 for r in o.ranked if r[2]["feasible"]) == bf_feasible


def test_objective_applies_only_after_feasibility_and_infeasible_plans_are_labeled():
    o = run([("storm", off_pier_env(160.0))])
    assert o.ranked and all(not r[2]["feasible"] for r in o.ranked)  # 160 kt off the pier overloads every synthetic plan
    ok = run([("light", off_pier_env(5.0))])
    assert ok.ranked[0][2]["feasible"] and ok.ranked[0][0][0] == 0


def test_inventory_counts_and_parts_are_enforced():
    o = run([("light", off_pier_env(5.0))], inventory={SPEC.spec_id: 5})
    for _, cfg, info in o.ranked:
        assert sum(l.parts for l in cfg.lines) <= 5          # four lines: all single or at most one 3-part... never 3-part everywhere
    assert run([("light", off_pier_env(5.0))], inventory={SPEC.spec_id: 0}).ranked == []
    none = run([("light", off_pier_env(5.0))], inventory={})
    assert none.ranked == [] and "No line inventory" in none.infeasible_reasons[0]


def test_excluded_or_missing_fittings_and_impossible_reach_generate_nothing():
    every = {f.fitting_id for f in BERTH.fittings}
    o = run([("x", calm_env())], excluded=every)
    assert o.ranked == [] and "No usable pier fitting" in o.infeasible_reasons[0]
    far = BERTH.model_copy(update={"fittings": [f for f in BERTH.fittings if f.x_ft >= 650]})
    o2 = S.search_plans(SHIP, far, SPECS, SLOTS, [("x", calm_env())], side_to="starboard", ship_x_ft=100.0, loading="full_load", mst="II", standoff_ft=10.0)
    assert o2.ranked == []   # every available bollard is farther than the reach bound from these bitts


def test_rope_size_must_fit_the_ship_fitting():
    ship = SHIP.model_copy(update={"fittings": [f.model_copy(update={"max_rope_circ_in": 6.0}) if f.kind == "bitt" else f for f in SHIP.fittings]})
    o = S.search_plans(ship, BERTH, SPECS, SLOTS, [("x", calm_env())], side_to="starboard", ship_x_ft=400.0, loading="full_load", mst="II", standoff_ft=10.0)
    assert o.ranked == [] and "rope size" in o.infeasible_reasons[0]   # the synthetic line is 8 in


def test_locked_lines_are_kept_and_a_locked_infeasible_plan_stays_infeasible():
    lock = MooringLine(line_number=1, role="breast", spec_id=SPEC.spec_id, parts=1, ship_fitting_id="BITT-1S", pier_fitting_id="B550", pretension_lbf=90_000.0)
    o = run([("light", off_pier_env(5.0))], locked=[lock])
    assert o.ranked and all(any(l.pier_fitting_id == "B550" and l.pretension_lbf == 90_000.0 for l in cfg.lines) for _, cfg, _ in o.ranked)
    assert all(not i["feasible"] for _, _, i in o.ranked)   # 90 kip pretension is far above the WLL


def test_every_mst_alternative_and_forecast_case_and_tide_level_is_evaluated():
    from mooring import refdata
    berth = refdata.berth("NAVSTA-NORFOLK-P12-N")
    iia = S.design_cases(berth, "starboard", "IIA", [], [0.0])
    assert [c[0] for c in iia][0].startswith("MST IIA design 50 kt") and len(iia) == 2   # (50 kt, 1.5 kt) and (64 kt, 1.0 kt), not their maximum
    forecast = EnvironmentSnapshot(wind_speed_kt=30, wind_gust_kt=45, wind_from_true_deg=200, current_speed_kt=0.5, current_set_true_deg=10, water_level_mllw_ft=0)
    cases = S.design_cases(berth, "starboard", "IIA", [forecast], [-1.0, 0.0, 2.0])
    assert len(cases) == 3 * 3 and any("forecast condition 1" in c[0] for c in cases) and {c[1].water_level_mllw_ft for c in cases} == {-1.0, 0.0, 2.0}


def test_unsafe_forecast_peak_makes_an_otherwise_feasible_plan_infeasible():
    mild = run([("design", off_pier_env(5.0))])
    both = run([("design", off_pier_env(5.0)), ("forecast peak", off_pier_env(160.0))])
    assert mild.ranked[0][2]["feasible"] and not both.ranked[0][2]["feasible"] and "forecast peak" in both.ranked[0][2]["worst_case"]


def test_bounded_search_says_it_is_incomplete_and_never_claims_infeasibility():
    o = run([("light", off_pier_env(5.0))], max_evals=5)
    assert o.strategy == "bounded_descent" and not o.complete and any("not proof" in n for n in o.notes) and o.evaluated <= 6


# ---------- API ----------

def wait(job, timeout=60):
    end = time.monotonic() + timeout
    st = client.get(job["status_url"]).json()
    while st["state"] in ("queued", "running") and time.monotonic() < end:
        time.sleep(0.02)
        st = client.get(job["status_url"]).json()
    assert st["state"] == "succeeded", st
    return st["result"]


def recommend(**kw):
    b = copy.deepcopy(EXAMPLES["mooring_recommend"])
    b.update(kw)
    r = client.post(f"{P}/mooring/recommend", json=b)
    assert r.status_code == 202, r.text
    return wait(r.json())


def test_api_returns_diagnostics_never_a_manufactured_green_and_resolvable_results():
    j = recommend(max_evaluations=300)
    r = j["result"]
    assert r["search"]["strategy"] in ("exhaustive", "bounded_descent") and r["search"]["evaluated"] <= 300 and r["cases"]
    assert j["backend"] == "real" and j["validity"]["state"] in ("limited", "invalid")
    for c in r["candidates"]:
        assert client.get(f"{P}/results/{c['analysis_result_id']}").status_code == 200 and c["cases_evaluated"] == len(r["cases"])
    if not any(c["feasible"] for c in r["candidates"]):
        assert j["status"] == "RED" and "NO_FEASIBLE_PLAN_FOUND" in {x["code"] for x in j["validity"]["reasons"]}


def test_api_empty_inventory_is_a_completed_red_result_not_an_error():
    j = recommend(available_lines=[{"spec_id": "NYLON-DB-7IN", "count": 0}])
    assert j["result"]["candidates"] == [] and j["status"] == "RED"
    assert "NO_CANDIDATE_GENERATED" in {x["code"] for x in j["validity"]["reasons"]}
    assert j["result"]["search"]["strategy"] == "none"
