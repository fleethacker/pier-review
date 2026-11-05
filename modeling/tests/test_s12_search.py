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
from mooring.mechanics import equilibrium as eq
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
        assert client.get(f"{P}/results/{c['analysis_result_id']}").status_code == 200
        assert 0 < c["cases_evaluated"] <= len(r["cases"])
        if c["feasible"]:
            assert c["cases_evaluated"] == len(r["cases"])
    if not any(c["feasible"] for c in r["candidates"]):
        assert j["status"] == "RED" and "NO_FEASIBLE_PLAN_FOUND" in {x["code"] for x in j["validity"]["reasons"]}


def test_api_empty_inventory_is_a_completed_red_result_not_an_error():
    j = recommend(available_lines=[{"spec_id": "NYLON-DB-7IN", "count": 0}])
    assert j["result"]["candidates"] == [] and j["status"] == "RED"
    assert "NO_CANDIDATE_GENERATED" in {x["code"] for x in j["validity"]["reasons"]}
    assert j["result"]["search"]["strategy"] == "none"


def test_budget_is_a_hard_bound_across_all_variants():
    assert run([('light', off_pier_env(5))], max_evals=1).evaluated <= 1


def test_search_checks_cancellation_inside_candidate_loop():
    from mooring.core.jobs import JobCancelled
    class Cancelled:
        def check_cancelled(self): raise JobCancelled()
    with pytest.raises(JobCancelled):
        run([('light', off_pier_env(5))], ctx=Cancelled())


def test_forecast_actual_tide_is_not_replaced_by_default_sensitivity_level():
    forecast = off_pier_env(5).model_copy(update={'water_level_mllw_ft': -7})
    cases = S.design_cases(BERTH, 'starboard', 'II', [forecast], [0], include_mst=False)
    assert {env.water_level_mllw_ft for _, env in cases} == {-7, 0}
    assert not any(label.startswith('MST') for label, _ in cases)


def test_forecast_only_requires_forecast_and_reports_restricted_basis():
    from mooring.core.schemas import RecommendRequest
    with pytest.raises(ValueError, match='forecast_only requires'):
        RecommendRequest(**EXAMPLES['mooring_recommend'], design_basis='forecast_only')
    j = recommend(design_basis='forecast_only', forecast_env=[EXAMPLES['mooring_analyze']['environment']], max_evaluations=50)
    assert all(not label.startswith('MST') for label in j['result']['cases'])
    assert any('does not establish MST' in a for a in j['assumptions'])


def test_tug_assignments_cannot_exceed_capacity_or_reuse_a_tug():
    from mooring import refdata
    from mooring.core.schemas import TugAssignment
    from mooring.tugs.validation import assignment_errors
    ship, fleet = refdata.ship('DDG-51-FIIA'), refdata.tugs()
    assignment = TugAssignment(tug_id=fleet[0].tug_id, push_point_id=ship.push_points[0].push_point_id,
                               mode='push', force_lbf=1)
    assert not assignment_errors(ship, [assignment], fleet)
    assert assignment_errors(ship, [assignment, assignment], fleet)
    assert assignment_errors(ship, [assignment.model_copy(update={'force_lbf': 1e9})], fleet)


def test_assisted_search_applies_same_tugs_to_each_evaluated_case(monkeypatch):
    from mooring.core.schemas import TugAssignment
    assignment = TugAssignment(tug_id='synthetic', push_point_id=SHIP.push_points[0].push_point_id, mode='push', force_lbf=100)
    original, seen = S.eq.build_system, []
    def tracked(*args, **kwargs):
        seen.append(kwargs.get('tugs'))
        return original(*args, **kwargs)
    monkeypatch.setattr(S.eq, 'build_system', tracked)
    out = run([('first', off_pier_env(5)), ('second', off_pier_env(6))], max_evals=2, tugs=[assignment])
    assert out.ranked and len(seen) >= 2 and all(t == [assignment] for t in seen)


def locked_line(**updates):
    values = dict(line_number=1, role='breast', spec_id=SPEC.spec_id, parts=1,
                  ship_fitting_id='BITT-1S', pier_fitting_id='B550')
    return MooringLine(**(values | updates))


@pytest.mark.parametrize('problem', ['excluded', 'occupied', 'poor', 'not_bollard', 'missing_chock', 'oversize', 'missing_spec'])
def test_locked_lines_do_not_bypass_fitting_constraints(problem):
    berth, ship, specs = BERTH.model_copy(deep=True), SHIP.model_copy(deep=True), dict(SPECS)
    lock, excluded = locked_line(), set()
    fitting = next(f for f in berth.fittings if f.fitting_id == lock.pier_fitting_id)
    if problem == 'excluded': excluded.add(lock.pier_fitting_id)
    if problem == 'occupied': fitting.occupied_by = 'other ship'
    if problem == 'poor': fitting.condition = 'poor'
    if problem == 'not_bollard': fitting.kind = 'cleat'
    if problem == 'missing_chock': lock.chock_id = 'missing'
    if problem == 'oversize':
        next(f for f in ship.fittings if f.fitting_id == lock.ship_fitting_id).max_rope_circ_in = 1
    if problem == 'missing_spec': lock.spec_id = 'missing'
    result = S.search_plans(ship, berth, specs, SLOTS, [('calm', calm_env())],
        side_to='starboard', ship_x_ft=400, loading='full_load', mst='II', locked=[lock], excluded=excluded, standoff_ft=10)
    assert result.ranked == [] and result.evaluated == 0
    assert 'Locked lines violate' in result.infeasible_reasons[0]


def test_locked_mixed_spec_inventory_counts_each_spec():
    other = SPEC.model_copy(update={'spec_id':'other'})
    lock = locked_line(spec_id='other', parts=3)
    result = S.search_plans(SHIP, BERTH, SPECS | {'other':other}, SLOTS, [('calm', calm_env())],
        side_to='starboard', ship_x_ft=400, loading='full_load', mst='II', locked=[lock],
        inventory={SPEC.spec_id:100, 'other':2}, standoff_ft=10)
    assert not result.ranked and result.evaluated == 0


def test_unknown_or_duplicate_locked_line_number_is_never_silently_discarded():
    for locks in ([locked_line(line_number=99)], [locked_line(), locked_line()]):
        result = run([('calm', calm_env())], locked=locks)
        assert not result.ranked and 'no lock is silently discarded' in result.infeasible_reasons[0]


def test_search_request_rejects_ambiguous_duplicate_inventory_and_locks():
    from mooring.core.schemas import RecommendRequest
    with pytest.raises(ValueError, match='spec ids must be unique'):
        RecommendRequest(**(EXAMPLES['mooring_recommend'] | {'available_lines':[
            {'spec_id':SPEC.spec_id,'count':1}, {'spec_id':SPEC.spec_id,'count':20}]}))
    with pytest.raises(ValueError, match='line numbers must be unique'):
        RecommendRequest(**(EXAMPLES['mooring_recommend'] | {'locked_lines':[locked_line(),locked_line()]}))


def test_shallow_case_is_not_a_feasible_floating_plan_and_counts_only_assessed_cases():
    shallow = calm_env().model_copy(update={'water_level_mllw_ft':-50})
    result = run([('grounded', shallow), ('not reached', calm_env())], max_evals=10)
    assert result.ranked and all(not info['feasible'] for _, _, info in result.ranked)
    assert all(info['cases_evaluated'] == 1 for _, _, info in result.ranked)


def test_nonpositive_actual_water_depth_returns_an_input_error_not_server_failure():
    body = copy.deepcopy(EXAMPLES['mooring_analyze'])
    body['environment']['water_level_mllw_ft'] = -1000
    response = client.post(f'{P}/mooring/analyze', json=body)
    assert response.status_code == 422
    assert 'Actual water depth must be positive' in response.json()['detail']
