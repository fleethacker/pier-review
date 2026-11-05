"""Tug wrench allocation (S08): supply a surge/sway/yaw wrench with a limited fleet of tugs on hull push points.

Each push point carries one tug at most and each tug serves one point. A tug exerts a force normal to the hull at its
push point (along the ship's y axis): pushing uses the ahead bollard pull and pulling the astern bollard pull from
the catalog, both capped by the push point's rating. Normal forces cannot supply surge: a surge component above
tolerance is reported as unmet and the plan is infeasible rather than silently ignored. Aggregate lateral capacity is
never called feasible unless the yaw moment and surge also meet the requirement.

Catalog bollard pulls are the numbers on file (seed data: placeholders), not certified ratings and not derived from
horsepower; the plan says so. Horsepower is reported, never converted to force. Numerical tolerances here are
engineering tolerances for reporting, not safety limits.

The magnitude problem for a fixed assignment is a small bounded least-squares problem solved by projected gradient;
assignments are enumerated exhaustively (fleets are small) and ranked: feasible first, then fewest tugs, then least
total force. The enumeration order is deterministic.
"""

import math
from dataclasses import dataclass
from itertools import combinations, permutations

from mooring.core.schemas import PushPoint, PushPointForce, ShipClass, TugAssignment, TugPlanResult, TugSpec, WrenchLbf

TOL_FLOOR_LBF = 50.0
TOL_REL = 0.005


@dataclass
class Candidate:
    assignment: list[tuple[TugSpec, PushPoint]]
    u: list[float]               # signed force along ship +y at each point
    residual: tuple[float, float, float]
    binding: list[str]

    @property
    def total_force(self) -> float:
        return sum(abs(v) for v in self.u)


def _bounds(ship: ShipClass, tug: TugSpec, pp: PushPoint, push_scale: float) -> tuple[float, float]:
    push = min(tug.bollard_pull_ahead_lbf * push_scale, pp.max_force_lbf)
    pull = min(tug.bollard_pull_astern_lbf * push_scale, pp.max_force_lbf)
    return (-push, pull) if pp.side == "port" else (-pull, push)


def _bls(x: list[float], lo: list[float], hi: list[float], fy: float, mz_over_l: float, ref_len: float) -> list[float]:
    """min (sum u - fy)^2 + (sum x_i u_i / L - mz/L)^2 over the box; projected gradient with momentum."""
    n = len(x)
    a = [[1.0] * n, [xi / ref_len for xi in x]]
    b = [fy, mz_over_l]
    lip = sum(a[0][i] ** 2 + a[1][i] ** 2 for i in range(n)) * 1.0 + 1e-12
    u = [min(max(0.0, lo[i]), hi[i]) for i in range(n)]
    y, t = u[:], 1.0
    for _ in range(300):
        r = [sum(a[k][i] * y[i] for i in range(n)) - b[k] for k in range(2)]
        g = [a[0][i] * r[0] + a[1][i] * r[1] for i in range(n)]
        un = [min(max(y[i] - g[i] / lip, lo[i]), hi[i]) for i in range(n)]
        tn = 0.5 * (1 + math.sqrt(1 + 4 * t * t))
        y = [un[i] + (t - 1) / tn * (un[i] - u[i]) for i in range(n)]
        delta = max(abs(un[i] - u[i]) for i in range(n))
        u, t = un, tn
        if delta < 1e-5:
            break
    return u


def allocate(ship: ShipClass, required: tuple[float, float, float], tugs: list[TugSpec], *, heading_true_deg: float,
             efficiency: float = 1.0, margin: float = 0.0) -> tuple[TugPlanResult, list[Candidate]]:
    """Best plan for the ship-frame wrench `required` = (fx, fy, mz) the tugs must supply (margin applied here)."""
    fx, fy, mz = (v * (1 + margin) for v in required)
    mag = math.sqrt(fx * fx + fy * fy + (mz / ship.lwl_ft) ** 2)
    tol = max(TOL_FLOOR_LBF, TOL_REL * mag)
    points = list(ship.push_points)
    candidates: list[Candidate] = []
    best: Candidate | None = None
    if mag == 0 or not tugs or not points:
        pass
    else:
        kmax = min(len(tugs), len(points))
        # Quick screen: a tug at zero force is always allowed, so the full fleet is the best case. If it cannot meet the
        # wrench, no smaller set can, and the smaller sets need not be enumerated.
        screened = _enumerate(ship, kmax, tugs, points, fx, fy, mz, efficiency)
        if not any(_norm(c.residual, ship.lwl_ft) <= tol for c in screened):
            candidates = screened
            best = min(screened, key=lambda c: (_norm(c.residual, ship.lwl_ft), c.total_force))
            return _result(ship, (fx, fy, mz), best, tol, heading_true_deg, efficiency, margin), candidates
        for k in range(1, kmax + 1):
            found_k = _enumerate(ship, k, tugs, points, fx, fy, mz, efficiency)
            candidates += found_k
            ok = [c for c in found_k if _norm(c.residual, ship.lwl_ft) <= tol]
            if ok:
                best = min(ok, key=lambda c: (c.total_force, [(t.tug_id, p.push_point_id) for t, p in c.assignment]))
                break
        if best is None and candidates:
            best = min(candidates, key=lambda c: (_norm(c.residual, ship.lwl_ft), c.total_force))
    return _result(ship, (fx, fy, mz), best, tol, heading_true_deg, efficiency, margin), candidates


def _enumerate(ship, k, tugs, points, fx, fy, mz, efficiency) -> list[Candidate]:
    out = []
    for tug_set in combinations(tugs, k):
        for pt_set in permutations(points, k):
            asg = list(zip(tug_set, pt_set))
            lo, hi = zip(*[_bounds(ship, t, p, efficiency) for t, p in asg])
            u = _bls([p.x_ft for _, p in asg], list(lo), list(hi), fy, mz / ship.lwl_ft, ship.lwl_ft)
            res = (fx, fy - sum(u), mz - sum(p.x_ft * ui for (_, p), ui in zip(asg, u)))
            binding = [f"{t.tug_id}@{p.push_point_id} at rating/point limit" for (t, p), ui, l, h in zip(asg, u, lo, hi)
                       if abs(ui - l) < 1e-6 or abs(ui - h) < 1e-6]
            out.append(Candidate(asg, u, res, binding))
    return out


def _norm(res: tuple[float, float, float], ref_len: float) -> float:
    return math.sqrt(res[0] ** 2 + res[1] ** 2 + (res[2] / ref_len) ** 2)


def _result(ship: ShipClass, req: tuple[float, float, float], best: Candidate | None, tol: float, heading: float,
            efficiency: float, margin: float) -> TugPlanResult:
    rationale = [f"Supply fx {req[0]:,.0f} lbf, fy {req[1]:,.0f} lbf, mz {req[2]:,.0f} ft.lbf"
                 + (f" (margin {margin:.0%} included)" if margin else "") + "; normal push-point forces only."]
    basis = ("Catalog bollard pull (seed/estimated unless published); ahead for pushing, astern for pulling, capped by the "
             f"push point rating; efficiency factor {efficiency:g}. Not certified ratings. Horsepower is not converted to force.")
    zero = (0.0, 0.0, 0.0)
    if best is None:
        feasible = max(abs(v) for v in req) == 0
        res = req if not feasible else zero
        return TugPlanResult(required_lateral_lbf=round(abs(req[1])), required_by_point=[], assignments=[], total_bollard_pull_lbf=0,
                             total_power_hp=0, recommended_tug_count=0, feasible=feasible,
                             rationale=rationale + (["Nothing to supply."] if feasible else ["No tug or push point is available."]),
                             required_wrench=WrenchLbf(fx_lbf=req[0], fy_lbf=req[1], mz_ftlbf=req[2]),
                             delivered_wrench=WrenchLbf(fx_lbf=0, fy_lbf=0, mz_ftlbf=0),
                             residual_wrench=WrenchLbf(fx_lbf=res[0], fy_lbf=res[1], mz_ftlbf=res[2]), ratings_basis=basis)
    assignments, by_point, bp, hp = [], [], 0.0, 0.0
    for (tug, pp), u in zip(best.assignment, best.u):
        if abs(u) < 1e-6:
            continue
        push = (u < 0) if pp.side == "port" else (u > 0)
        toward = (heading - 90) % 360 if u > 0 else (heading + 90) % 360   # bearing of the force on the ship (+y is to port)
        assignments.append(TugAssignment(tug_id=tug.tug_id, push_point_id=pp.push_point_id, mode="push" if push else "pull",
                                         force_lbf=round(abs(u)), direction_true_deg=round(toward, 1)))
        by_point.append(PushPointForce(push_point_id=pp.push_point_id, force_lbf=round(abs(u)), mode="push" if push else "pull"))
        bp += tug.bollard_pull_ahead_lbf if push else tug.bollard_pull_astern_lbf
        hp += tug.power_hp
    delivered = (0.0, sum(best.u), sum(p.x_ft * ui for (_, p), ui in zip(best.assignment, best.u)))
    feasible = _norm(best.residual, ship.lwl_ft) <= tol
    binding = [b for b in best.binding]
    if abs(best.residual[0]) > tol:
        binding.append("surge: normal push-point forces cannot supply a longitudinal force")
    if not feasible:
        rationale.append(f"Residual fx {best.residual[0]:,.0f} lbf, fy {best.residual[1]:,.0f} lbf, mz {best.residual[2]:,.0f} ft.lbf "
                         f"exceeds tolerance {tol:,.0f}: not feasible with the available tugs and points.")
    return TugPlanResult(
        required_lateral_lbf=round(abs(req[1])), required_by_point=by_point, assignments=assignments, total_bollard_pull_lbf=round(bp),
        total_power_hp=round(hp), recommended_tug_count=len(assignments), feasible=feasible, rationale=rationale,
        required_wrench=WrenchLbf(fx_lbf=req[0], fy_lbf=req[1], mz_ftlbf=req[2]),
        delivered_wrench=WrenchLbf(fx_lbf=delivered[0], fy_lbf=delivered[1], mz_ftlbf=delivered[2]),
        residual_wrench=WrenchLbf(fx_lbf=best.residual[0], fy_lbf=best.residual[1], mz_ftlbf=best.residual[2]),
        binding_constraints=binding, ratings_basis=basis)
