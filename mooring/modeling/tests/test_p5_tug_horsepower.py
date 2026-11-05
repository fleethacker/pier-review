"""P5: minimum-horsepower placement-feasible tug assignment. All fleets here are SYNTHETIC test data, not real tugs.

The brute-force oracle is independent of the implementation: it enumerates tug subsets and point permutations and
tests feasibility by building the convex hull of the 2^n corner images of the force box (no support function).
"""

import itertools
import math
import random

import pytest

from mooring.core.schemas import Provenance, PushPoint, TugSpec
from mooring.fixtures import synthetic_ship
from mooring.tugs import minimize_horsepower

SYN = Provenance(source="synthetic", confidence="synthetic")
_BASE = synthetic_ship()
SHIP = _BASE.model_copy(update={"push_points": list(_BASE.push_points) + [
    PushPoint(push_point_id="PP-MID-P", x_ft=0.0, side="port", max_force_lbf=1e9),
    PushPoint(push_point_id="PP-MID-S", x_ft=0.0, side="starboard", max_force_lbf=1e9)]})   # synthetic midship points
L = SHIP.lwl_ft


def tug(tid, hp, ahead, astern=None):
    return TugSpec(tug_id=tid, name=f"Synthetic {tid}", propulsion="asd", power_hp=hp, bollard_pull_ahead_lbf=ahead,
                   bollard_pull_astern_lbf=astern if astern is not None else ahead, provenance=SYN)


def _hull(pts):
    pts = sorted(set(pts))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def _in_hull(pt, hull, tol):
    if len(hull) == 1:
        return math.dist(pt, hull[0]) <= tol
    if len(hull) == 2:
        a, b = hull
        d2 = max(1e-12, math.dist(a, b) ** 2)
        t = min(1.0, max(0.0, ((pt[0] - a[0]) * (b[0] - a[0]) + (pt[1] - a[1]) * (b[1] - a[1])) / d2))
        return math.dist(pt, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))) <= tol
    for a, b in zip(hull, hull[1:] + hull[:1]):
        ex, ey = b[0] - a[0], b[1] - a[1]
        n = math.hypot(ex, ey)
        if n and (ex * (pt[1] - a[1]) - ey * (pt[0] - a[0])) / n < -tol:   # hull is CCW: inside is on the left
            return False
    return True


def oracle(fleet, req, points=None, margin=0.0):
    fx, fy, mz = (v * (1 + margin) for v in req)
    tol = max(50.0, 0.005 * math.sqrt(fx**2 + fy**2 + (mz / L) ** 2))
    if abs(fx) > tol:
        return None
    points = points if points is not None else SHIP.push_points
    best = None
    for k in range(1, min(len(fleet), len(points)) + 1):
        for ts in itertools.combinations(fleet, k):
            hp = sum(t.power_hp for t in ts)
            for ps in itertools.permutations(points, k):
                corners = []
                for signs in itertools.product((0, 1), repeat=k):
                    fyv = mzv = 0.0
                    for s, t, p in zip(signs, ts, ps):
                        push = min(t.bollard_pull_ahead_lbf, p.max_force_lbf)
                        pull = min(t.bollard_pull_astern_lbf, p.max_force_lbf)
                        lo, hi = (-push, pull) if p.side == "port" else (-pull, push)
                        u = hi if s else lo
                        fyv += u
                        mzv += p.x_ft / L * u
                    corners.append((fyv, mzv))
                if _in_hull((fy, mz / L), _hull(corners), tol):
                    key = (hp, k, tuple(sorted(t.tug_id for t in ts)))
                    if best is None or key < best:
                        best = key
    return best


def run(fleet, req, **kw):
    return minimize_horsepower(SHIP, req, fleet, **kw)


def test_cheaper_small_tugs_beat_one_big_tug_when_placement_allows():
    big = tug("BIG", 6000, 120_000)
    s1, s2 = tug("S1", 1500, 40_000), tug("S2", 1500, 40_000)
    plan = run([big, s1, s2], (0, 60_000, 0))   # S1+S2 (3000 hp, 80k) beats BIG (6000 hp)
    assert plan.feasible and plan.total_power_hp == 3000
    assert sorted(p.tug_id for p in plan.placements) == ["S1", "S2"]
    assert plan.load_scale_margin == pytest.approx(80_000 / 60_000, abs=1e-3)
    assert plan.validity == "limited" and plan.objective == "minimize_total_horsepower"


def test_yaw_demand_forces_two_points_even_if_one_big_tug_has_force():
    big = tug("BIG", 5000, 500_000)
    a, b = tug("A", 2000, 60_000), tug("B", 2000, 60_000)
    # Pure yaw couple with zero sway: one tug cannot give moment without sway, so two tugs are required.
    plan = run([big, a, b], (0, 0, 3_000_000))
    assert plan.feasible and plan.tug_count == 2 and plan.total_power_hp == 4000
    assert abs(plan.residual_wrench.fy_lbf) < 300 and abs(plan.residual_wrench.mz_ftlbf) < 300 * L


def test_matches_independent_bruteforce_on_seeded_synthetic_fleets():
    rng = random.Random(20260505)
    n_feas = n_infeas = 0
    for case in range(60):
        n = rng.randint(2, 4)
        fleet = [tug(f"T{i}", rng.choice([1000, 1500, 2000, 3000, 4500]), rng.choice([20e3, 35e3, 50e3, 80e3]),
                     rng.choice([15e3, 30e3, 50e3, 70e3])) for i in range(n)]
        req = (0.0, rng.uniform(-250e3, 250e3), rng.uniform(-30e6, 30e6))
        expected = oracle(fleet, req)
        plan = run(fleet, req)
        if expected is None:
            assert not plan.feasible, (case, req)
            assert plan.infeasibility_reasons
            n_infeas += 1
        else:
            assert plan.feasible, (case, req, expected)
            assert plan.total_power_hp == expected[0], (case, req)
            assert plan.tug_count == expected[1]
            assert tuple(sorted(p.tug_id for p in plan.placements)) == expected[2]
            assert plan.load_scale_margin >= 0.95   # accepted within reporting tolerance, so slightly below 1 is possible
            n_feas += 1
    assert n_feas >= 10 and n_infeas >= 5


def test_tie_break_is_deterministic_and_input_order_independent():
    fleet = [tug("B", 2000, 100_000), tug("A", 2000, 100_000), tug("C", 2000, 100_000)]
    p1 = run(fleet, (0, 50_000, 0))
    p2 = run(list(reversed(fleet)), (0, 50_000, 0))
    assert p1.feasible and [x.tug_id for x in p1.placements] == ["A"]
    assert p1.model_dump() == p2.model_dump()


def test_equal_hp_prefers_fewer_tugs():
    fleet = [tug("X1", 1000, 60_000), tug("X2", 1000, 60_000), tug("Y", 2000, 60_000)]
    plan = run(fleet, (0, 50_000, 0))   # X1+X2 and Y both 2000 hp, but X1 alone (1000 hp) is cheapest and enough
    assert plan.tug_count == 1 and plan.total_power_hp == 1000
    fleet2 = [tug("X1", 1000, 30_000), tug("X2", 1000, 30_000), tug("Y", 2000, 60_000)]
    plan2 = run(fleet2, (0, 50_000, 0))   # X1+X2 = 60k at 2000 hp ties Y (60k, 2000 hp): fewer tugs -> Y
    assert plan2.total_power_hp == 2000 and [p.tug_id for p in plan2.placements] == ["Y"]


def test_pure_sway_single_tug_utilization():
    plan = run([tug("A", 1000, 90_000), tug("B", 1000, 90_000)], (0, 40_000, 0))
    assert plan.tug_count == 1
    assert plan.placements[0].utilization == pytest.approx(40_000 / 90_000, abs=1e-3)


def test_infeasible_by_force_reports_reason_and_fleet_scale_below_one():
    plan = run([tug("A", 1000, 20_000), tug("B", 1000, 20_000)], (0, 200_000, 0))
    assert not plan.feasible and plan.placements == [] and plan.total_power_hp == 0
    assert plan.fleet_scale_margin < 1 and any("cannot supply" in r for r in plan.infeasibility_reasons)


def test_infeasible_by_moment_despite_enough_total_force():
    fleet = [tug("A", 3000, 80_000), tug("B", 3000, 80_000)]
    plan = run(fleet, (0, 100_000, 20_000_000))
    assert not plan.feasible and oracle(fleet, (0, 100_000, 20_000_000)) is None


def test_surge_is_infeasible_with_reason():
    plan = run([tug("A", 1000, 90_000)], (50_000, 0, 0))
    assert not plan.feasible and any("Surge" in r for r in plan.infeasibility_reasons)


def test_placement_limits_point_rating_and_moment_arm():
    ship = SHIP.model_copy(update={"push_points": [PushPoint(push_point_id="ONLY", x_ft=0.0, side="port", max_force_lbf=30_000)]})
    assert not minimize_horsepower(ship, (0, 50_000, 0), [tug("A", 1000, 90_000)]).feasible   # point caps at 30k
    ok = minimize_horsepower(ship, (0, 25_000, 0), [tug("A", 1000, 90_000)])
    assert ok.feasible and ok.placements[0].capacity_lbf == 30_000
    assert not minimize_horsepower(ship, (0, 0, 1_000_000), [tug("A", 1000, 90_000)]).feasible  # zero arm


def test_more_tugs_than_points_and_empty_cases():
    fleet = [tug(f"T{i}", 1000 + i, 40_000) for i in range(6)]
    assert run(fleet, (0, 30_000, 0)).tug_count == 1
    assert not run([], (0, 1_000, 0)).feasible
    zero = run(fleet, (0, 0, 0))
    assert zero.feasible and zero.total_power_hp == 0 and zero.tug_count == 0


def test_margin_and_efficiency_apply():
    fleet = [tug("A", 1000, 40_000)]
    assert run(fleet, (0, 35_000, 0)).feasible
    assert not run(fleet, (0, 35_000, 0), margin=0.25).feasible     # 43.75k > 40k
    assert not run(fleet, (0, 35_000, 0), efficiency=0.8).feasible  # 32k capacity
