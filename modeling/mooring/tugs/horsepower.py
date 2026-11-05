"""P5 (R5): minimum-total-horsepower tug assignment that is placement-feasible for a required wrench.

Placement feasibility: each tug takes at most one push point and each point one tug; a tug exerts a normal (ship +y)
force bounded by its catalog bollard pull (ahead to push, astern to pull, times efficiency) capped by the point rating.
The reachable (fy, mz/L) set for an assignment is a 2-D zonotope, so membership is tested exactly by the support
function over the generator-normal directions (no iterative solver). Normal forces cannot supply surge.

Objective: minimize the sum of catalog power_hp over the chosen tugs (horsepower is the stated objective; it is not
converted to force). Deterministic exhaustive search over tug subsets in ascending (hp, count, ids) order; the first
subset with a feasible placement wins. Within it, the feasible placement with least total force, then lexicographic
ids, is reported. Horsepower and bollard pull are catalog values (seed/synthetic unless published): validity limited.
"""

import math
from itertools import combinations, permutations

from mooring.core.schemas import PushPoint, ShipClass, TugSpec, WrenchLbf
from mooring.core.schemas.tugs import HorsepowerPlacement, HorsepowerPlan

from .allocation import TOL_FLOOR_LBF, TOL_REL, _bls, _bounds

Asg = list[tuple[TugSpec, PushPoint]]


def _gens_bounds(ship: ShipClass, asg: Asg, eff: float):
    g = [(1.0, p.x_ft / ship.lwl_ft) for _, p in asg]
    lo_hi = [_bounds(ship, t, p, eff) for t, p in asg]
    return g, [v[0] for v in lo_hi], [v[1] for v in lo_hi]


def _dirs(g):
    ds = [(1.0, 0.0), (0.0, 1.0)]
    ds += [(-gy, gx) for gx, gy in g]
    out = []
    for d in ds:
        n = math.hypot(*d)
        if n > 0:
            out += [(d[0] / n, d[1] / n), (-d[0] / n, -d[1] / n)]
    return out


def _support(d, g, lo, hi):
    s = 0.0
    for (gx, gy), l, h in zip(g, lo, hi):
        c = d[0] * gx + d[1] * gy
        s += max(c * l, c * h)
    return s


def scale_margin(g, lo, hi, b) -> float:
    """Largest s with s*b in the zonotope (inf if b is zero)."""
    best = math.inf
    for d in _dirs(g):
        nb = d[0] * b[0] + d[1] * b[1]
        if nb > 1e-12:
            best = min(best, _support(d, g, lo, hi) / nb)
    return best


def _inside(g, lo, hi, b, tol) -> bool:
    return all(d[0] * b[0] + d[1] * b[1] <= _support(d, g, lo, hi) + tol for d in _dirs(g))


def _solve_u(g, lo, hi, b) -> list[float]:
    """Feasible force vector with least total |force| among box vertices of the fiber; falls back to bounded LSQ."""
    n = len(g)
    best, best_key = None, None
    if n >= 2:
        for i, j in combinations(range(n), 2):
            fixed = [k for k in range(n) if k not in (i, j)]
            for bits in range(2 ** len(fixed)):
                u = [0.0] * n
                for m, k in enumerate(fixed):
                    u[k] = hi[k] if (bits >> m) & 1 else lo[k]
                r0 = b[0] - sum(u)
                r1 = b[1] - sum(g[k][1] * u[k] for k in fixed)
                if abs(g[i][1] - g[j][1]) < 1e-12:
                    continue
                ui = (r1 - g[j][1] * r0) / (g[i][1] - g[j][1])
                uj = r0 - ui
                if lo[i] - 1e-6 <= ui <= hi[i] + 1e-6 and lo[j] - 1e-6 <= uj <= hi[j] + 1e-6:
                    u[i], u[j] = min(max(ui, lo[i]), hi[i]), min(max(uj, lo[j]), hi[j])
                    key = sum(abs(v) for v in u)
                    if best is None or key < best_key - 1e-9:
                        best, best_key = u, key
    if best is None:
        best = _bls([gy for _, gy in g], lo, hi, b[0], b[1], 1.0)
    return best


def minimize_horsepower(ship: ShipClass, required: tuple[float, float, float], fleet: list[TugSpec], *,
                        efficiency: float = 1.0, margin: float = 0.0,
                        fleet_data_basis: str = "catalog (seed/synthetic unless published)") -> HorsepowerPlan:
    """Minimum-total-hp placement-feasible assignment for ship-frame wrench `required` (margin applied here)."""
    fx, fy, mz = (v * (1 + margin) for v in required)
    mag = math.sqrt(fx * fx + fy * fy + (mz / ship.lwl_ft) ** 2)
    tol = max(TOL_FLOOR_LBF, TOL_REL * mag)
    req = WrenchLbf(fx_lbf=fx, fy_lbf=fy, mz_ftlbf=mz)
    b = (fy, mz / ship.lwl_ft)
    assumptions = [f"Fleet horsepower and bollard pull: {fleet_data_basis}; not certified. Horsepower is the objective only.",
                   f"Efficiency factor {efficiency:g}; normal push-point forces only; tolerance {tol:,.0f} lbf."]
    plan = HorsepowerPlan(feasible=False, required_wrench=req, assumptions=assumptions)
    points = list(ship.push_points)
    if mag == 0:
        plan.feasible = True
        plan.delivered_wrench = WrenchLbf(fx_lbf=0, fy_lbf=0, mz_ftlbf=0)
        plan.residual_wrench = WrenchLbf(fx_lbf=0, fy_lbf=0, mz_ftlbf=0)
        plan.assumptions.append("Nothing to supply: zero tugs, zero horsepower.")
        return plan
    reasons: list[str] = []
    if not fleet:
        reasons.append("No tugs available.")
    if not points:
        reasons.append("Ship has no push points.")
    if abs(fx) > tol:
        reasons.append(f"Surge {fx:,.0f} lbf cannot be supplied: tugs push normal to the hull at push points.")
    if not fleet or not points:
        plan.infeasibility_reasons = reasons
        plan.residual_wrench = req
        return plan
    kmax = min(len(fleet), len(points))
    subsets = [s for k in range(1, kmax + 1) for s in combinations(fleet, k)]
    subsets.sort(key=lambda s: (sum(t.power_hp for t in s), len(s), tuple(t.tug_id for t in s)))
    evaluated = 0
    chosen = None
    for s in subsets:
        feas_here = []
        for pts in permutations(points, len(s)):
            evaluated += 1
            asg = list(zip(s, pts))
            g, lo, hi = _gens_bounds(ship, asg, efficiency)
            if _inside(g, lo, hi, b, tol):
                feas_here.append((asg, g, lo, hi))
        if feas_here and abs(fx) <= tol:
            scored = []
            for asg, g, lo, hi in feas_here:
                u = _solve_u(g, lo, hi, b)
                scored.append((sum(abs(v) for v in u), [(t.tug_id, p.push_point_id) for t, p in asg], asg, u, g, lo, hi))
            scored.sort(key=lambda r: (round(r[0], 6), r[1]))
            chosen = scored[0][2:]
            break
    plan.candidates_evaluated = evaluated
    best_scale = -1.0
    for ts in combinations(fleet, kmax):
        for pts in permutations(points, kmax):
            g, lo, hi = _gens_bounds(ship, list(zip(ts, pts)), efficiency)
            best_scale = max(best_scale, scale_margin(g, lo, hi, b))
    plan.fleet_scale_margin = None if math.isinf(best_scale) else round(best_scale, 4)
    if chosen is None:
        if abs(fx) <= tol:
            reasons.append(f"Fleet and push points cannot supply fy {fy:,.0f} lbf and mz {mz:,.0f} ft.lbf together: "
                           f"best-case full-fleet load scale {best_scale:.3f} (<1 means shortfall).")
        plan.infeasibility_reasons = reasons
        plan.residual_wrench = req
        return plan
    asg, u, g, lo, hi = chosen
    placements = []
    for (t, p), ui in zip(asg, u):
        push = (ui < 0) if p.side == "port" else (ui > 0)
        cap = min((t.bollard_pull_ahead_lbf if push else t.bollard_pull_astern_lbf) * efficiency, p.max_force_lbf)
        placements.append(HorsepowerPlacement(tug_id=t.tug_id, push_point_id=p.push_point_id, mode="push" if push else "pull",
                                              force_lbf=round(abs(ui), 3), capacity_lbf=cap,
                                              utilization=round(abs(ui) / cap, 4), power_hp=t.power_hp))
    dfy, dmz = sum(u), sum(p.x_ft * ui for (_, p), ui in zip(asg, u))
    sm = scale_margin(g, lo, hi, b)
    plan.feasible = True
    plan.total_power_hp = sum(t.power_hp for t, _ in asg)
    plan.tug_count = len(asg)
    plan.placements = sorted(placements, key=lambda r: (r.tug_id, r.push_point_id))
    plan.delivered_wrench = WrenchLbf(fx_lbf=0.0, fy_lbf=dfy, mz_ftlbf=dmz)
    plan.residual_wrench = WrenchLbf(fx_lbf=fx, fy_lbf=fy - dfy, mz_ftlbf=mz - dmz)
    plan.load_scale_margin = None if math.isinf(sm) else round(sm, 4)
    return plan
