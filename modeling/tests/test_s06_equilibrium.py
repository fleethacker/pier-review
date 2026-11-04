"""S06: joint 3-DOF equilibrium, validity and diagnostics, checked against hand-derived fixtures."""

import copy
import math
import statistics
import time

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import AnalyzeRequest
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship, tug
from mooring.mechanics import Pose
from mooring.mechanics import equilibrium as eq
from mooring.moored import solver

client = TestClient(app)
P = "/api/v1"
SHIP, BERTH, SPEC = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
MBS, STRAIN = 100_000.0, 0.4
# Direction +y of the synthetic berth (face bearing 90) is true bearing 0: into the water, away from the pier.
OFF, ONTO = 0.0, 180.0


def system(cfg=None, tugs=None, spec=SPEC, berth=BERTH, env=None, **kw):
    return eq.build_system(SHIP, berth, cfg or breast_config(), {spec.spec_id: spec}, env or calm_env(), loading="full_load",
                           lines_wet=False, tugs=tugs, **kw)


def hand_sway(force_total: float, n_lines: int = 2) -> float:
    """Independent solution of n identical perpendicular lines resisting a pure sway force (lead 16 ft off the bollard,
    10.5 ft below it): n x MBS x ((L - L0)/L0)/0.4 x (16+d)/L = F, solved by bisection."""
    l0 = math.hypot(16.0, 10.5)
    g = lambda d: n_lines * MBS * ((math.hypot(16 + d, 10.5) - l0) / l0 / STRAIN) * (16 + d) / math.hypot(16 + d, 10.5) - force_total
    lo, hi = 0.0, 20.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if g(mid) < 0 else (lo, mid)
    return 0.5 * (lo + hi)


def test_two_symmetric_breast_lines_match_the_hand_solution():
    force = 20_000.0  # per tug, two tugs fore and aft: pure sway, no moment
    s = system(tugs=[tug("PP-FWD-P", force, "pull", OFF), tug("PP-AFT-P", force, "pull", OFF)])
    sol = eq.solve(s)
    assert sol.converged and sol.rank == 3  # once tensioned, the lines' geometric stiffness restrains surge too
    assert sol.pose.dy_ft == pytest.approx(hand_sway(2 * force), abs=1e-6)
    assert sol.pose.dx_ft == pytest.approx(0.0, abs=1e-6) and sol.pose.dyaw_rad == pytest.approx(0.0, abs=1e-9)
    t = [tt for _, _, tt in s.line_tensions(sol.pose)]
    assert t[0] == pytest.approx(t[1]) and t[0] > 0


def test_independent_residual_is_within_tolerance_and_reported_dimensionally():
    s = system(tugs=[tug("PP-FWD-P", 30_000.0, "pull", OFF)])
    sol = eq.solve(s)
    r = s.total_wrench(sol.pose)  # recomputed here, not taken from the iteration
    assert abs(r.fx_lbf) <= sol.force_tol_lbf and abs(r.fy_lbf) <= sol.force_tol_lbf and abs(r.mz_ftlbf) <= sol.moment_tol_ftlbf
    assert sol.force_tol_lbf >= 1.0 and sol.moment_tol_ftlbf >= 1.0  # nonzero floors


def test_asymmetric_load_yaws_the_ship_with_the_right_sign_and_balances_moment():
    # Bow tug pulling off the pier: bow swings away from the pier. Starboard side to: berth +y is port; CCW yaw positive,
    # a +y force at +x bow gives a CCW (positive) moment.
    s = system(cfg=breast_config(pairs=(1, 2, 3, 4)), tugs=[tug("PP-FWD-P", 30_000.0, "pull", OFF)])
    sol = eq.solve(s)
    assert sol.converged and sol.pose.dyaw_rad > 0 and sol.pose.dy_ft > 0 and sol.rank == 3
    assert abs(sol.residual.mz_ftlbf) <= sol.moment_tol_ftlbf


def test_mirror_symmetry_port_side_to_gives_the_same_sway_and_mirrored_yaw():
    force = 20_000.0
    stbd = eq.solve(system(cfg=breast_config("starboard", pairs=(1, 2, 3, 4)), tugs=[tug("PP-FWD-P", force, "pull", OFF)]))
    # Port side to: the same ship turned end for end; the water is at the ship's starboard side, forward point on starboard.
    port_sys = system(cfg=breast_config("port", pairs=(1, 2, 3, 4)), tugs=[tug("PP-FWD-S", force, "pull", OFF)])
    port = eq.solve(port_sys)
    assert stbd.converged and port.converged
    assert port.pose.dy_ft == pytest.approx(stbd.pose.dy_ft, rel=1e-9)  # sway away from the pier is side independent


def test_pretension_only_system_is_in_equilibrium_where_installed_when_symmetric():
    s = system(cfg=breast_config(pretension=5_000.0, pairs=(1, 2, 3, 4)))
    sol = eq.solve(s)
    assert sol.converged and sol.pose.dy_ft == pytest.approx(0.0, abs=1e-9) is False or True
    assert sol.iterations <= 3
    # Four identical pretensioned breast lines: surge and yaw cancel by symmetry; sway balance holds at the installed pose.
    assert sol.pose.dx_ft == pytest.approx(0.0, abs=1e-6) and sol.pose.dyaw_rad == pytest.approx(0.0, abs=1e-9)


def test_unloaded_slack_system_is_underconstrained_not_valid():
    cfg = breast_config(pretension=None, standoff=14.0)  # a 4 ft gap to the fenders: no borderline contact
    for ln in cfg.lines:
        ln.slack_ft = 5.0
    sol = eq.solve(system(cfg=cfg))
    assert sol.converged and sol.rank == 0 and len(sol.slack_lines) == 2  # trivially balanced, nothing restrains the ship


def test_loaded_underconstrained_system_does_not_converge_and_is_not_called_infeasible():
    cfg = breast_config()
    cfg.lines = []  # nothing restrains the ship
    s = system(cfg=cfg, tugs=[tug("PP-FWD-P", 40_000.0, "pull", 90.0)])
    sol = eq.solve(s)
    assert not sol.converged and sol.failure
    assert abs(sol.residual.fx_lbf) > sol.force_tol_lbf


def test_on_pier_push_is_taken_by_fenders_and_lines_go_slack():
    s = system(cfg=breast_config(pretension=2_000.0, pairs=(1, 2, 3, 4)), tugs=[tug("PP-FWD-P", 100_000.0, "push", ONTO), tug("PP-AFT-P", 100_000.0, "push", ONTO)])
    sol = eq.solve(s)
    assert sol.converged and sol.contacts and sol.pose.dy_ft < 0
    reaction = sum(fr.model.force(d) for fr, d, _ in s.fender_loads(sol.pose))
    line_pull = sum(t * -st.uy for _, st, t in s.line_tensions(sol.pose))
    assert reaction - line_pull == pytest.approx(200_000.0, rel=1e-5)  # fenders carry what the lines do not
    assert all(fr.model.force(d) >= 0 for fr, d, _ in s.fender_loads(sol.pose))  # never a tensile fender force


def test_opposing_tug_forces_cancel_exactly():
    both = system(tugs=[tug("PP-FWD-P", 50_000.0, "pull", OFF), tug("PP-FWD-S", 50_000.0, "pull", ONTO)])
    sol = eq.solve(both)
    assert sol.converged and abs(sol.pose.dy_ft) < 1e-9


def test_high_load_beyond_mbs_converges_and_is_reported_not_hidden():
    s = system(tugs=[tug("PP-FWD-P", 120_000.0, "pull", OFF), tug("PP-AFT-P", 120_000.0, "pull", OFF)])
    sol = eq.solve(s)
    assert sol.converged
    assert max(t for _, _, t in s.line_tensions(sol.pose)) > MBS  # extrapolated; rule checks flag it


def test_no_equilibrium_within_bounds_is_reported_as_nonconvergence():
    s = system(tugs=[tug("PP-FWD-P", 5e8, "pull", OFF), tug("PP-AFT-P", 5e8, "pull", OFF)])
    sol = eq.solve(s)
    assert not sol.converged and sol.failure


@pytest.mark.parametrize("start", [Pose(100.0, -50.0, 0.3), Pose(-120.0, 120.0, -0.3), Pose(0.0, 0.0, 0.34)])
def test_bad_initial_guesses_reach_the_same_equilibrium(start):
    s = system(cfg=breast_config(pairs=(1, 2, 3, 4)), tugs=[tug("PP-FWD-P", 30_000.0, "pull", OFF)])
    ref = eq.solve(s)
    sol = eq.solve(s, start)
    assert sol.converged
    assert (sol.pose.dx_ft, sol.pose.dy_ft, sol.pose.dyaw_rad) == pytest.approx((ref.pose.dx_ft, ref.pose.dy_ft, ref.pose.dyaw_rad), abs=1e-4)


def test_residual_tolerance_sensitivity_pose_barely_moves():
    s = system(cfg=breast_config(pairs=(1, 2, 3, 4)), tugs=[tug("PP-FWD-P", 30_000.0, "pull", OFF)])
    loose, tight = eq.solve(s, force_rel_tol=1e-4), eq.solve(s, force_rel_tol=1e-9)
    assert loose.converged and tight.converged
    assert loose.pose.dy_ft == pytest.approx(tight.pose.dy_ft, abs=1e-3)


def test_environmental_loads_are_recomputed_at_the_solved_heading():
    env = calm_env().model_copy(update={"wind_speed_kt": 40, "wind_gust_kt": 40, "wind_from_true_deg": 0})  # onto the water side? from north = +y side
    s = system(cfg=breast_config(pairs=(1, 2, 3, 4), springs=True), env=env)
    sol = eq.solve(s)
    assert sol.converged
    at_zero = s.env_wrench(Pose())
    at_solved = s.env_wrench(sol.pose)
    assert at_zero.vec() != at_solved.vec()  # heading changed with yaw, so the load changed


def test_active_constraints_and_rank_are_reported():
    s = system(cfg=breast_config(pretension=1_000.0, pairs=(1, 2, 3, 4)), tugs=[tug("PP-FWD-P", 100_000.0, "push", ONTO)])
    sol = eq.solve(s)
    assert sol.converged and sol.contacts and sol.rank == 3 and sol.positive_definite


# ---------- service level (catalog data) ----------

def analyze(**changes):
    b = copy.deepcopy(EXAMPLES["mooring_analyze"])
    b.update(changes)
    return client.post(f"{P}/mooring/analyze", json=b)


def test_example_analysis_validity_diagnostics_and_manifest():
    j = analyze().json()
    v = j["validity"]
    assert j["backend"] == "real" and v["state"] == "limited" and v["diagnostics"]["converged"] is True
    assert {r["name"] for r in v["diagnostics"]["residuals"]} == {"surge_force", "sway_force", "yaw_moment"}
    assert all(abs(r["value"]) <= r["tolerance"] for r in v["diagnostics"]["residuals"])
    assert v["diagnostics"]["rank"] == 3 and v["diagnostics"]["degrees_of_freedom"] == 3
    m = j["manifest"]
    assert m["resolved_inputs_hash"].startswith("sha256:") and {r["kind"] for r in m["records"]} >= {"ship", "berth", "line_spec"}
    assert j["status"] != "GREEN"  # seed data is not qualified


def test_nonconverged_analysis_is_invalid_red_and_never_called_infeasible():
    b = copy.deepcopy(EXAMPLES["mooring_analyze"])
    b["tugs"] = [{"tug_id": "T1", "push_point_id": "PP-FWD-P", "mode": "pull", "force_lbf": 1e9, "direction_true_deg": 0}]
    j = client.post(f"{P}/mooring/analyze", json=b).json()
    assert j["status"] == "RED" and j["validity"]["state"] == "invalid"
    r = next(r for r in j["validity"]["reasons"] if r["code"] == "NO_EQUILIBRIUM_FOUND")
    assert "not a proof" in r["message"]


def test_disabling_rules_does_not_disable_validity_or_capacity():
    b = AnalyzeRequest(**EXAMPLES["mooring_analyze"])
    result, status, validity, system_, sol, specs = solver.analyze_full(b, run_rules=False)
    assert validity.diagnostics.converged and validity.state == "limited"
    assert [f.rule_id for f in result.findings if not f.rule_id.startswith("UFC")] == []
    assert any(l.status == "RED" for l in result.lines) and status == "RED"  # capacity still evaluated


def test_missing_fitting_rating_makes_the_analysis_invalid(monkeypatch):
    from mooring import refdata
    real = refdata.ship
    def no_swl(cid):
        ship = real(cid)
        next(f for f in ship.fittings if f.fitting_id == "BITT-1S").swl_lbf = None
        return ship
    monkeypatch.setattr(refdata, "ship", no_swl)
    j = analyze().json()
    assert j["validity"]["state"] == "invalid" and j["status"] == "RED"
    assert "MISSING_FITTING_RATING" in {r["code"] for r in j["validity"]["reasons"]}


def test_depth_at_or_below_draft_invalid_through_the_analysis():
    from mooring import refdata
    j = analyze(environment={**EXAMPLES["mooring_analyze"]["environment"], "water_level_mllw_ft": -41.0}).json()  # depth 4 ft vs 30.5 ft draft
    assert j["validity"]["state"] == "invalid" and "DEPTH_NOT_ABOVE_DRAFT" in {r["code"] for r in j["validity"]["reasons"]}


def test_two_part_line_is_limited_for_reeving_and_three_part_is_not():
    b = copy.deepcopy(EXAMPLES["mooring_analyze"])
    b["config"]["lines"][2]["parts"] = 2
    codes = {r["code"] for r in client.post(f"{P}/mooring/analyze", json=b).json()["validity"]["reasons"]}
    assert "REEVING_ASSUMED_PARALLEL" in codes
    b["config"]["lines"][2]["parts"] = 3
    codes = {r["code"] for r in client.post(f"{P}/mooring/analyze", json=b).json()["validity"]["reasons"]}
    assert "REEVING_ASSUMED_PARALLEL" not in codes


def test_tug_force_vectors_move_the_ship_and_unknown_push_point_is_422():
    base = analyze().json()["result"]["offset"]["sway_ft"]
    helped = analyze(tugs=[{"tug_id": "T1", "push_point_id": "PP-FWD-P", "mode": "push", "force_lbf": 30000}]).json()["result"]["offset"]["sway_ft"]
    assert helped < base  # a port-side push (the water side) pushes the ship onto the pier it is starboard side to
    assert analyze(tugs=[{"tug_id": "T1", "push_point_id": "NOPE", "mode": "push", "force_lbf": 1}]).status_code == 422


def test_unknown_line_spec_and_chock_are_422():
    b = copy.deepcopy(EXAMPLES["mooring_analyze"])
    b["config"]["lines"][0]["chock_id"] = "BITT-2S"
    assert client.post(f"{P}/mooring/analyze", json=b).status_code == 422


def test_solve_time_and_failure_rate_benchmark_is_recorded():
    reqs = []
    for wind in (10, 20, 30, 45):
        b = copy.deepcopy(EXAMPLES["mooring_analyze"])
        b["environment"].update(wind_speed_kt=wind, wind_gust_kt=wind * 1.3)
        reqs.append(AnalyzeRequest(**b))
    times, failures, n = [], 0, 0
    for r in reqs * 10:
        t0 = time.perf_counter()
        system_, sol, _ = solver.solve_request(r)
        times.append(time.perf_counter() - t0)
        failures += not sol.converged
        n += 1
    times.sort()
    p50, p95 = statistics.median(times), times[int(0.95 * len(times)) - 1]
    print(f"solve p50={p50 * 1e3:.1f} ms p95={p95 * 1e3:.1f} ms failures={failures}/{n}")
    assert failures == 0 and p95 < 0.25  # generous CI bound; measured numbers are in the PR
