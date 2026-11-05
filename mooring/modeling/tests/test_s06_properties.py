"""Seeded randomized attacks on the equilibrium solver and the validity composition. Deterministic: fixed seeds, no clock."""

import copy
import math
import random

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import AnalyzeRequest
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship, tug
from mooring.mechanics import Pose, equilibrium as eq
from mooring.rules.nstm582 import design_factor

SHIP, BERTH, SPEC = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
client = TestClient(app)


def random_case(rng: random.Random, side="starboard"):
    env = calm_env(rng.uniform(-2, 3)).model_copy(update={
        "wind_speed_kt": rng.uniform(0, 45), "wind_from_true_deg": rng.uniform(0, 360), "current_speed_kt": rng.uniform(0, 1.2), "current_set_true_deg": rng.uniform(0, 360)})
    env = env.model_copy(update={"wind_gust_kt": env.wind_speed_kt * rng.uniform(1.0, 1.4)})
    cfg = breast_config(side, pretension=rng.choice([0.0, 500.0, 3000.0, 9000.0]), parts=rng.choice([1, 3]), pairs=(1, 2, 3, 4), springs=rng.random() < 0.7,
                        standoff=rng.choice([10.0, 12.0, 14.0]))
    tugs = []
    if rng.random() < 0.5:
        pt = rng.choice(["PP-FWD-P", "PP-AFT-P"])
        tugs = [tug(pt, rng.uniform(0, 60_000), rng.choice(["push", "pull"]))]
    return env, cfg, tugs


@pytest.mark.parametrize("seed", range(40))
def test_converged_means_an_independent_residual_within_tolerance_and_bounds(seed):
    rng = random.Random(seed)
    env, cfg, tugs = random_case(rng)
    s = eq.build_system(SHIP, BERTH, cfg, {SPEC.spec_id: SPEC}, env, loading="full_load", lines_wet=False, tugs=tugs)
    sol = eq.solve(s)
    r = s.total_wrench(sol.pose)                           # recomputed here, independent of the iteration
    ok = abs(r.fx_lbf) <= sol.force_tol_lbf and abs(r.fy_lbf) <= sol.force_tol_lbf and abs(r.mz_ftlbf) <= sol.moment_tol_ftlbf
    assert sol.converged == (ok and not sol.active_bounds)  # the flag never disagrees with the independent check
    if sol.converged:
        assert abs(sol.pose.dx_ft) < eq.BOUND_XY_FT and abs(sol.pose.dy_ft) < eq.BOUND_XY_FT and abs(sol.pose.dyaw_rad) < eq.BOUND_YAW_RAD
        assert sol.rank in (0, 1, 2, 3) and all(t >= 0 for _, _, t in s.line_tensions(sol.pose))   # lines never push
        assert all(fr.model.force(d) >= 0 for fr, d, _ in s.fender_loads(sol.pose))


@pytest.mark.parametrize("seed", range(25))
def test_solution_does_not_depend_on_the_starting_pose(seed):
    rng = random.Random(1000 + seed)
    env, cfg, tugs = random_case(rng)
    s = eq.build_system(SHIP, BERTH, cfg, {SPEC.spec_id: SPEC}, env, loading="full_load", lines_wet=False, tugs=tugs)
    a = eq.solve(s)
    b = eq.solve(s, Pose(rng.uniform(-8, 8), rng.uniform(-8, 8), rng.uniform(-0.05, 0.05)))
    if a.converged and b.converged and a.rank == 3 and b.rank == 3:
        assert (a.pose.dx_ft, a.pose.dy_ft, a.pose.dyaw_rad) == pytest.approx((b.pose.dx_ft, b.pose.dy_ft, b.pose.dyaw_rad), abs=5e-3)


@pytest.mark.parametrize("seed", range(25))
def test_port_and_starboard_side_to_are_mirror_images_for_a_symmetric_ship_and_pier(seed):
    """Reflecting the whole scene in x maps the starboard-side-to problem onto the port-side-to problem, so utilizations match."""
    rng = random.Random(2000 + seed)
    env, cfg_s, _ = random_case(rng)
    cfg_p = breast_config("port", pretension=cfg_s.lines[0].pretension_lbf, parts=cfg_s.lines[0].parts, pairs=(1, 2, 3, 4),
                          springs=len(cfg_s.lines) > 4, standoff=cfg_s.standoff_ft)
    env_p = env.model_copy(update={"wind_from_true_deg": (-env.wind_from_true_deg) % 360, "current_set_true_deg": (-env.current_set_true_deg) % 360})
    sys_s = eq.build_system(SHIP, BERTH, cfg_s, {SPEC.spec_id: SPEC}, env, loading="full_load", lines_wet=False)
    sys_p = eq.build_system(SHIP, BERTH, cfg_p, {SPEC.spec_id: SPEC}, env_p, loading="full_load", lines_wet=False)
    a, b = eq.solve(sys_s), eq.solve(sys_p)
    assert a.converged == b.converged
    if a.converged and b.converged:
        df = design_factor("II")
        ua = sorted(round(p, 3) for _, p, _ in eq.utilization(sys_s, a.pose, df))
        ub = sorted(round(p, 3) for _, p, _ in eq.utilization(sys_p, b.pose, df))
        assert ua == pytest.approx(ub, abs=0.05)
        assert a.pose.dy_ft == pytest.approx(b.pose.dy_ft, abs=2e-3) and a.pose.dyaw_rad == pytest.approx(-b.pose.dyaw_rad, abs=2e-5)


def random_api_request(rng: random.Random) -> dict:
    b = copy.deepcopy(EXAMPLES["mooring_analyze"])
    b["environment"].update(wind_speed_kt=rng.uniform(0, 70), wind_gust_kt=rng.uniform(0, 90), wind_from_true_deg=rng.uniform(0, 360),
                            current_speed_kt=rng.uniform(0, 3), current_set_true_deg=rng.uniform(0, 360), water_level_mllw_ft=rng.uniform(-3, 4))
    b["environment"]["wind_gust_kt"] = max(b["environment"]["wind_gust_kt"], b["environment"]["wind_speed_kt"])
    for ln in b["config"]["lines"]:
        ln["parts"] = rng.choice([1, 2, 3])
        ln["pretension_lbf"] = rng.choice([None, 0, 2000, 15000])
    if rng.random() < 0.4:
        b["tugs"] = [{"tug_id": "T1", "push_point_id": rng.choice(["PP-FWD-P", "PP-AFT-P"]), "mode": rng.choice(["push", "pull"]), "force_lbf": rng.uniform(0, 120000)}]
    return b


@pytest.mark.parametrize("seed", range(30))
def test_no_path_reports_green_when_limited_invalid_or_over_a_limit(seed):
    b = random_api_request(random.Random(3000 + seed))
    j = client.post("/api/v1/mooring/analyze", json=b).json()
    assert j["validity"] is not None                            # every real analysis states its validity
    v, status, r = j["validity"], j["status"], j["result"]
    if v["state"] in ("limited", "invalid"):
        assert status != "GREEN" and v["reasons"]
    if v["state"] == "invalid":
        assert status == "RED"
    if any(l["pct_wll"] > 100 for l in r["lines"]) or any(p["pct"] > 100 for p in r["pier_fittings"]):
        assert status == "RED"                                  # physical utilization is never hidden by validity
    diag = v["diagnostics"]
    if diag["converged"] is False:
        assert v["state"] == "invalid" and any(x["code"] == "NO_EQUILIBRIUM_FOUND" for x in v["reasons"])
    assert all(abs(x["value"]) <= x["tolerance"] for x in diag["residuals"]) or diag["converged"] is False


def test_the_randomized_cases_are_not_vacuous():
    conv = full_rank = mirrored = 0
    for seed in range(40):
        env, cfg, tugs = random_case(random.Random(seed))
        s = eq.build_system(SHIP, BERTH, cfg, {SPEC.spec_id: SPEC}, env, loading="full_load", lines_wet=False, tugs=tugs)
        sol = eq.solve(s)
        conv += sol.converged
        full_rank += sol.converged and sol.rank == 3
    assert conv >= 32 and full_rank >= 20   # most cases solve and most are fully constrained, so the invariants above were really exercised
