"""Quasi-static 3-DOF mooring equilibrium (S06), a shared mechanical evaluator (moored and berthing both use it).

Unknowns: ship displacement (dx, dy) of the midships reference point in the berth frame and yaw dpsi (CCW). Heave, roll
and pitch are not modeled; fitting heights are held at the water level at analysis time.

Balance: sum of environmental loads (recomputed at the solved heading and position), tug force vectors, tension-only
line forces and unilateral fender reactions must vanish in surge, sway and yaw. A damped Gauss-Newton (Levenberg-
Marquardt) iteration finds a candidate; acceptance never relies on the iteration's own termination flag. The physical
residual is re-evaluated independently from the final pose and compared with dimensional tolerances, the support
matrix is checked for rank and positive definiteness, and active bounds/contacts/slack lines are reported.

Tolerances (numerical, not Navy safety limits): force <= max(1 lbf, 1e-6 x scale); moment <= max(1 ft.lbf, 1e-6 x
scale x reference length), scale = max(applied load, restoring load, 1 lbf), reference length = waterline length.
A failure to converge is reported as such. It is never proof that no physical equilibrium exists.
"""

import math
from dataclasses import dataclass, field

from mooring.core.geometry import depth_at
from mooring.core.schemas import (
    Berth, EnvironmentSnapshot, LineSpec, MooringConfig, MooringLine, ShipClass, TugAssignment,
)
from mooring.loads import compute_loads
from . import FenderModel, LineModel, Pose, ShipFrame, Wrench, force_wrench, init_line_model
from .geometry import LineState, line_state
from .pose import ZERO, force_wrench_at

FORCE_FLOOR_LBF = 1.0
MOMENT_FLOOR_FTLBF = 1.0
REL_TOL = 1e-6
MAX_ITER = 200
BOUND_XY_FT = 150.0
BOUND_YAW_RAD = 0.35
FD_STEP_FT = 1e-3


@dataclass
class LineRec:
    ln: MooringLine
    spec: LineSpec
    lead_xy: tuple[float, float]
    lead_height_ft: float          # above the waterline
    pier_xyz: tuple[float, float, float]
    model: LineModel
    how: str
    wet: bool


@dataclass
class FenderRec:
    model: FenderModel
    hull_side_y: float
    half_len: float


@dataclass
class TugRec:
    tug: TugAssignment
    point: tuple[float, float]     # ship-frame hull point
    fixed_ship_dir: tuple[float, float] | None   # unit force direction in the ship frame, or None
    fixed_berth_dir: tuple[float, float] | None  # unit force direction in the berth frame (true-bearing input)
    max_force_lbf: float


@dataclass
class System:
    ship: ShipClass
    berth: Berth
    cfg: MooringConfig
    env: EnvironmentSnapshot
    loading: str
    use_gust: bool
    frame: ShipFrame
    lines: list[LineRec]
    fenders: list[FenderRec]
    tugs: list[TugRec]
    ref_len_ft: float
    notes: list[str] = field(default_factory=list)

    # ----- pieces of the balance -----
    def depth_ft(self, pose: Pose) -> float:
        return depth_at(self.berth, self.frame.reference(pose)[0]) + self.env.water_level_mllw_ft

    def loads_at(self, pose: Pose):
        heading = self.frame.heading_true_deg(self.berth.face_bearing_true_deg, pose)
        return compute_loads(self.ship, self.loading, heading, self.env, self.depth_ft(pose), self.use_gust)

    def env_wrench(self, pose: Pose) -> Wrench:
        r = self.loads_at(pose)
        fx, fy = self.frame.vector_to_berth(r.total.fx_lbf, r.total.fy_lbf, pose)
        return Wrench(fx, fy, r.total.mz_ftlbf)

    def tug_force(self, t: TugRec, pose: Pose) -> tuple[float, float]:
        f = t.tug.force_lbf
        if t.tug.mode == "standby" or f == 0:
            return 0.0, 0.0
        if t.fixed_berth_dir is not None:
            return f * t.fixed_berth_dir[0], f * t.fixed_berth_dir[1]
        ux, uy = self.frame.vector_to_berth(t.fixed_ship_dir[0], t.fixed_ship_dir[1], pose)
        return f * ux, f * uy

    def tug_wrench(self, pose: Pose) -> Wrench:
        w = ZERO
        for t in self.tugs:
            fx, fy = self.tug_force(t, pose)
            w = w + force_wrench(self.frame, pose, t.point, fx, fy)
        return w

    def line_state(self, rec: LineRec, pose: Pose, water_level: float | None = None) -> LineState:
        wl = self.env.water_level_mllw_ft if water_level is None else water_level
        return line_state(self.frame, pose, rec.lead_xy, wl + rec.lead_height_ft, rec.pier_xyz)

    def line_tensions(self, pose: Pose) -> list[tuple[LineRec, LineState, float]]:
        out = []
        for rec in self.lines:
            st = self.line_state(rec, pose)
            out.append((rec, st, rec.model.tension(st.length_ft)))
        return out

    def fender_loads(self, pose: Pose) -> list[tuple[FenderRec, float, float | None]]:
        out = []
        for fr in self.fenders:
            d, y = fr.model.deflection(self.frame, pose, fr.hull_side_y, fr.half_len)
            out.append((fr, d, y))
        return out

    def restoring_wrench(self, pose: Pose) -> Wrench:
        w = ZERO
        for rec, st, t in self.line_tensions(pose):
            if t:
                w = w + force_wrench(self.frame, pose, rec.lead_xy, t * st.ux, t * st.uy)
        for fr, d, y in self.fender_loads(pose):
            if d > 0:
                w = w + force_wrench_at(self.frame, pose, (fr.model.x_ft, y), 0.0, fr.model.force(d))
        return w

    def applied_wrench(self, pose: Pose) -> Wrench:
        return self.env_wrench(pose) + self.tug_wrench(pose)

    def total_wrench(self, pose: Pose) -> Wrench:
        return self.applied_wrench(pose) + self.restoring_wrench(pose)

    def force_scale(self, pose: Pose) -> float:
        a = self.applied_wrench(pose)
        applied = math.hypot(a.fx_lbf, a.fy_lbf)
        restoring = sum(t for _, _, t in self.line_tensions(pose)) + sum(fr.model.force(d) for fr, d, _ in self.fender_loads(pose))
        return max(applied, restoring, FORCE_FLOOR_LBF)

    def tolerances(self, pose: Pose, rel_tol: float = REL_TOL) -> tuple[float, float]:
        scale = self.force_scale(pose)
        return max(FORCE_FLOOR_LBF, rel_tol * scale), max(MOMENT_FLOOR_FTLBF, rel_tol * scale * self.ref_len_ft)


# ---------- small dense linear algebra (3x3) ----------

def solve3(a: list[list[float]], b: list[float]) -> list[float] | None:
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    n = len(m)
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-300:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def numerical_rank(a: list[list[float]], rel: float = 1e-9) -> int:
    m = [row[:] for row in a]
    scale = max((abs(v) for row in m for v in row), default=0.0)
    if scale == 0:
        return 0
    rank, rows = 0, len(m)
    for c in range(len(m[0])):
        p = max(range(rank, rows), key=lambda r: abs(m[r][c]), default=None)
        if p is None or abs(m[p][c]) <= rel * scale:
            continue
        m[rank], m[p] = m[p], m[rank]
        for r in range(rank + 1, rows):
            f = m[r][c] / m[rank][c]
            for k in range(c, len(m[0])):
                m[r][k] -= f * m[rank][k]
        rank += 1
        if rank == rows:
            break
    return rank


def positive_definite(a: list[list[float]]) -> bool:
    """Cholesky of the symmetric part; False when not strictly positive definite."""
    n = len(a)
    s = [[0.5 * (a[i][j] + a[j][i]) for j in range(n)] for i in range(n)]
    l = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            v = s[i][j] - sum(l[i][k] * l[j][k] for k in range(j))
            if i == j:
                if v <= 1e-12 * max(1.0, abs(s[i][i])):
                    return False
                l[i][i] = math.sqrt(v)
            else:
                l[i][j] = v / l[j][j]
    return True


# ---------- the solve ----------

@dataclass
class Solution:
    pose: Pose
    converged: bool
    iterations: int
    residual: Wrench
    force_tol_lbf: float
    moment_tol_ftlbf: float
    rank: int
    positive_definite: bool
    stiffness: list[list[float]]
    active_bounds: list[str]
    slack_lines: list[int]
    contacts: list[str]
    failure: str | None = None

    @property
    def residual_ok(self) -> bool:
        r = self.residual
        return abs(r.fx_lbf) <= self.force_tol_lbf and abs(r.fy_lbf) <= self.force_tol_lbf and abs(r.mz_ftlbf) <= self.moment_tol_ftlbf


def _pose(s: list[float], ref_len: float) -> Pose:
    return Pose(s[0], s[1], s[2] / ref_len)


def _scaled_resid(sysm: System, s: list[float]) -> list[float]:
    w = sysm.total_wrench(_pose(s, sysm.ref_len_ft))
    return [w.fx_lbf, w.fy_lbf, w.mz_ftlbf / sysm.ref_len_ft]


def _jacobian(sysm: System, s: list[float], h: float = FD_STEP_FT) -> list[list[float]]:
    cols = []
    for k in range(3):
        sp, sm = s[:], s[:]
        sp[k] += h
        sm[k] -= h
        rp, rm = _scaled_resid(sysm, sp), _scaled_resid(sysm, sm)
        cols.append([(a - b) / (2 * h) for a, b in zip(rp, rm)])
    return [[cols[k][i] for k in range(3)] for i in range(3)]


def _solve_from(sysm: System, start: Pose, *, max_iter: int = MAX_ITER, force_rel_tol: float = REL_TOL,
                bound_xy_ft: float = BOUND_XY_FT, bound_yaw_rad: float = BOUND_YAW_RAD) -> Solution:
    L = sysm.ref_len_ft
    bounds = [bound_xy_ft, bound_xy_ft, bound_yaw_rad * L]
    s = [start.dx_ft, start.dy_ft, start.dyaw_rad * L]
    s = [max(-b, min(b, v)) for v, b in zip(s, bounds)]
    lam, it, failure = 1e-3, 0, None

    def converged(r: list[float], pose: Pose) -> bool:
        ft, mt = sysm.tolerances(pose, force_rel_tol)
        return abs(r[0]) <= ft and abs(r[1]) <= ft and abs(r[2] * L) <= mt

    r = _scaled_resid(sysm, s)
    while it < max_iter and not converged(r, _pose(s, L)):
        it += 1
        j = _jacobian(sysm, s)
        a = [[sum(j[k][i] * j[k][c] for k in range(3)) for c in range(3)] for i in range(3)]
        g = [sum(j[k][i] * r[k] for k in range(3)) for i in range(3)]
        n0 = math.sqrt(sum(v * v for v in r))
        accepted = False
        # 1) Newton with backtracking (fast on piecewise-linear systems); 2) Levenberg-Marquardt fallback.
        d = solve3(j, [-v for v in r])
        if d is not None:
            alpha = 1.0
            for _ in range(12):
                cand = [max(-b, min(b, s[i] + alpha * d[i])) for i, b in enumerate(bounds)]
                rc = _scaled_resid(sysm, cand)
                if math.sqrt(sum(v * v for v in rc)) < n0:
                    s, r, accepted = cand, rc, True
                    break
                alpha *= 0.5
        if not accepted:
            for _ in range(40):
                damp = [[a[i][c] + (lam * max(a[i][i], 1e-9) if i == c else 0.0) for c in range(3)] for i in range(3)]
                d = solve3(damp, [-v for v in g])
                if d is None:
                    lam *= 10
                    continue
                cand = [max(-b, min(b, s[i] + d[i])) for i, b in enumerate(bounds)]
                rc = _scaled_resid(sysm, cand)
                if math.sqrt(sum(v * v for v in rc)) < n0:
                    s, r, lam, accepted = cand, rc, max(lam / 3, 1e-12), True
                    break
                lam *= 4
        if not accepted:
            failure = "no descent direction found (stalled)"
            break
    pose = _pose(s, L)
    # Independent re-evaluation of the physical residual at the final pose.
    res = sysm.total_wrench(pose)
    ft, mt = sysm.tolerances(pose, force_rel_tol)
    j = _jacobian(sysm, s)
    k = [[-j[i][c] for c in range(3)] for i in range(3)]
    sol = Solution(pose=pose, converged=False, iterations=it, residual=res, force_tol_lbf=ft, moment_tol_ftlbf=mt,
                   rank=numerical_rank(k), positive_definite=positive_definite(k), stiffness=k,
                   active_bounds=[n for n, v, b in zip(("surge", "sway", "yaw"), s, bounds) if abs(abs(v) - b) < 1e-9],
                   slack_lines=[rec.ln.line_number for rec, st, t in sysm.line_tensions(pose) if t == 0.0],
                   contacts=[fr.model.fender_id for fr, d, _ in sysm.fender_loads(pose) if d > 0], failure=failure)
    sol.converged = sol.residual_ok and not sol.active_bounds
    if not sol.converged and sol.failure is None:
        sol.failure = "residual above tolerance" if not sol.residual_ok else "solution lies on a displacement bound"
    return sol


STARTS = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (-2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, -2.0, 0.0), (0.0, 0.0, 0.004), (0.0, 0.0, -0.004)]


def solve(sysm: System, start: Pose = Pose(), **kw) -> Solution:
    """Solve from `start`; if that does not converge, retry from a fixed set of nearby starts (deterministic).

    The first start that passes the independent residual check wins. If none does, the attempt with the smallest
    residual is returned, unconverged: the caller must treat it as invalid, never as proof of infeasibility."""
    best = None
    for dx, dy, dyaw in STARTS:
        sol = _solve_from(sysm, Pose(start.dx_ft + dx, start.dy_ft + dy, start.dyaw_rad + dyaw), **kw)
        if sol.converged:
            return sol
        score = abs(sol.residual.fx_lbf) + abs(sol.residual.fy_lbf) + abs(sol.residual.mz_ftlbf) / sysm.ref_len_ft
        if best is None or score < best[0]:
            best = (score, sol)
    return best[1]


# ---------- building the system ----------

class SystemError(ValueError):
    """A reference or specification that cannot be built into a mechanical system (HTTP 422)."""


def build_system(ship: ShipClass, berth: Berth, cfg: MooringConfig, specs: dict[str, LineSpec], env: EnvironmentSnapshot,
                 *, loading: str, lines_wet: bool, tugs: list[TugAssignment] | None = None, use_gust: bool = True,
                 install_water_level_ft: float | None = None) -> System:
    from mooring.core.geometry import standoff_ft

    standoff = standoff_ft(berth, cfg)
    frame = ShipFrame(cfg.side_to, cfg.ship_x_ft, standoff + ship.beam_ft / 2)
    sfit = {f.fitting_id: f for f in ship.fittings}
    pfit = {f.fitting_id: f for f in berth.fittings}
    install_wl = env.water_level_mllw_ft if install_water_level_ft is None else install_water_level_ft
    from mooring.core.geometry import PIER_FITTING_HEIGHT_FT
    pier_z = berth.deck_height_mllw_ft + PIER_FITTING_HEIGHT_FT
    recs: list[LineRec] = []
    notes: list[str] = []
    for ln in cfg.lines:
        if ln.ship_fitting_id not in sfit:
            raise SystemError(f"Ship fitting '{ln.ship_fitting_id}' not found on {ship.class_id}")
        if ln.pier_fitting_id not in pfit:
            raise SystemError(f"Pier fitting '{ln.pier_fitting_id}' not found on {berth.berth_id}")
        if ln.spec_id not in specs:
            raise SystemError(f"Line spec '{ln.spec_id}' not found")
        bitt = sfit[ln.ship_fitting_id]
        chock_id = ln.chock_id or bitt.paired_chock_id
        if ln.chock_id and (ln.chock_id not in sfit or sfit[ln.chock_id].kind != "chock"):
            raise SystemError(f"chock_id '{ln.chock_id}' is not a chock on {ship.class_id}")
        lead = sfit.get(chock_id, bitt) if chock_id else bitt
        pf = pfit[ln.pier_fitting_id]
        spec = specs[ln.spec_id]
        wet = (ln.condition == "wet") or (ln.condition is None and lines_wet)
        init = line_state(frame, Pose(), (lead.x_ft, lead.y_ft), install_wl + lead.z_ft, (pf.x_ft, pf.y_ft, pier_z))
        try:
            model, how = init_line_model(spec.load_elongation, spec.mbs_lbf, parts=ln.parts,
                                         wet_factor=spec.wet_strength_factor if wet else 1.0,
                                         initial_length_ft=init.length_ft, pretension_lbf=ln.pretension_lbf,
                                         slack_ft=ln.slack_ft, paid_out_unstretched_length_ft=ln.paid_out_unstretched_length_ft)
        except ValueError as e:
            raise SystemError(f"line {ln.line_number}: {e}") from None
        recs.append(LineRec(ln, spec, (lead.x_ft, lead.y_ft), lead.z_ft, (pf.x_ft, pf.y_ft, pier_z), model, how, wet))
    hull_side = -ship.beam_ft / 2 if cfg.side_to == "starboard" else ship.beam_ft / 2
    fenders = [FenderRec(FenderModel.linear(f.fender_id, f.x_ft, f.standoff_ft, f.length_ft, f.stiffness_lbf_per_ft, f.rated_energy_ftlbf),
                         hull_side, ship.lwl_ft / 2) for f in berth.fenders]
    pps = {p.push_point_id: p for p in ship.push_points}
    trecs: list[TugRec] = []
    for t in tugs or []:
        if t.push_point_id not in pps:
            raise SystemError(f"Push point '{t.push_point_id}' not found on {ship.class_id}")
        pp = pps[t.push_point_id]
        y = ship.beam_ft / 2 if pp.side == "port" else -ship.beam_ft / 2
        berth_dir = ship_dir = None
        if t.direction_true_deg is not None:
            theta = math.radians(berth.face_bearing_true_deg - t.direction_true_deg)
            berth_dir = (math.cos(theta), math.sin(theta))
        else:
            inward = -1.0 if pp.side == "port" else 1.0   # ship-frame y toward the centerline from that side
            ship_dir = (0.0, inward if t.mode == "push" else -inward)
        trecs.append(TugRec(t, (pp.x_ft, y), ship_dir, berth_dir, pp.max_force_lbf))
    return System(ship=ship, berth=berth, cfg=cfg, env=env, loading=loading, use_gust=use_gust, frame=frame, lines=recs,
                  fenders=fenders, tugs=trecs, ref_len_ft=ship.lwl_ft, notes=notes)


def utilization(system: System, pose: Pose, df: float) -> list[tuple[str, float, str]]:
    """(element, percent of limit, mode) for every line, fitting and fender. Light: no rules, no result objects."""
    out = []
    tens = system.line_tensions(pose)
    for rec, st, t in tens:
        mbs = rec.model.mbs_eff_lbf
        out.append((f"line-{rec.ln.line_number}", 100 * t / (mbs / df), "WLL"))
        if t >= mbs:
            out.append((f"line-{rec.ln.line_number}", 100 * t / mbs, "MBS"))
    pier = {f.fitting_id: f for f in system.berth.fittings}
    ship = {f.fitting_id: f for f in system.ship.fittings}
    acc_p: dict[str, list[float]] = {}
    acc_s: dict[str, list[float]] = {}
    for rec, st, t in tens:
        for acc, fid in ((acc_p, rec.ln.pier_fitting_id), (acc_s, rec.ln.ship_fitting_id)):
            v = acc.setdefault(fid, [0.0, 0.0, 0.0])
            v[0] += t * st.ux; v[1] += t * st.uy; v[2] += t * st.uz
    for fid, v in acc_p.items():
        out.append((fid, 100 * math.sqrt(sum(c * c for c in v)) / pier[fid].capacity_nominal_lbf, "fitting"))
    for fid, v in acc_s.items():
        if ship[fid].swl_lbf:
            out.append((fid, 100 * math.sqrt(sum(c * c for c in v)) / ship[fid].swl_lbf, "fitting"))
    for fr, d, _ in system.fender_loads(pose):
        if fr.model.rated_energy_ftlbf:
            out.append((fr.model.fender_id, 100 * fr.model.energy(d) / fr.model.rated_energy_ftlbf, "fender"))
    return out


