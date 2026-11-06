"""Planar 3-DOF rigid-body dynamics with unilateral contact and event times (S15/S16).

State: berth-frame position (x, y) of the midships reference point, heading angle psi (CCW, same convention as
`ShipFrame`), and body-frame velocities (u surge, v sway to port, r yaw rate). Equations for a diagonal total mass matrix
M = diag(m11, m22, m33) when CG coincides with the reference (rigid body + added mass):

    m11 du/dt - m22 v r       = X
    m22 dv/dt + m11 u r       = Y
    m33 dr/dt + (m22 - m11) u v = N

with passive damping -(D_lin nu + D_quad |nu| nu) added to the external wrench. Integration is classical RK4 at a fixed
step, shortened near contact, with event times (contact start/end, line taut/slack) located by bisection. Output
sampling is independent of the integration step.

An explicitly offset CG adds the rigid-body coupling terms -m*yG and m*xG to
surge/yaw and sway/yaw, plus parallel-axis yaw inertia. Kirchhoff momentum
equations preserve power balance with the same diagonal added-mass inputs.

What this is not: a validated maneuvering model. Added mass and damping must come from a qualified source for a specific
hull; none is held in this repository, so no real vessel can be simulated here yet (the coefficients below are inputs).
Environmental loads enter as quasi-static M3 forces at the current heading; ship motion drag is carried only by the
damping terms, so relative-velocity wind/current effects are not modeled and nothing is double counted.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from .pose import Pose, ShipFrame

State = tuple[float, float, float, float, float, float]   # x, y, psi, u, v, r


@dataclass(frozen=True)
class BodyParams:
    mass_slug: float                 # rigid-body mass in slugs (lbf, ft, s units)
    izz_slug_ft2: float
    added_surge: float = 0.0       # added masses (slugs, slug ft^2)
    added_sway: float = 0.0
    added_yaw: float = 0.0
    damping_lin: tuple[float, float, float] = (0.0, 0.0, 0.0)    # lbf per ft/s, lbf per ft/s, ft.lbf per rad/s
    damping_quad: tuple[float, float, float] = (0.0, 0.0, 0.0)
    qualification: str = "synthetic"   # 'synthetic' (test inputs) or 'qualified' once coefficients are benchmarked
    cg_x_ft: float = 0.0
    cg_y_ft: float = 0.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.mass_slug, self.izz_slug_ft2, self.added_surge,
                self.added_sway, self.added_yaw, self.cg_x_ft, self.cg_y_ft, *self.damping_lin, *self.damping_quad)):
            raise ValueError("body parameters must be finite")
        for name in ("mass_slug", "izz_slug_ft2"):
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be positive")
        if min(self.added_surge, self.added_sway, self.added_yaw, *self.damping_lin, *self.damping_quad) < 0:
            raise ValueError("added mass and damping must be non-negative (passive)")

    @property
    def m(self) -> tuple[float, float, float]:
        return (self.mass_slug + self.added_surge, self.mass_slug + self.added_sway,
                self.izz_slug_ft2 + self.mass_slug * (self.cg_x_ft**2 + self.cg_y_ft**2) + self.added_yaw)

    def momentum(self, nu: tuple[float, float, float]) -> tuple[float, float, float]:
        """M nu about the ship origin; izz_slug_ft2 is centroidal inertia.

        Rigid-body mass matrix and Kirchhoff equations:
        https://www.fossen.biz/html/marineCraftModel.html (Kinetics).
        Our axes are x forward, y port, z up; added inertia is diagonal.
        """
        u, v, r = nu
        m11, m22, m33 = self.m
        a, b = -self.mass_slug*self.cg_y_ft, self.mass_slug*self.cg_x_ft
        return m11*u+a*r, m22*v+b*r, a*u+b*v+m33*r

    def acceleration(self, rhs: tuple[float, float, float]) -> tuple[float, float, float]:
        """Solve the symmetric positive-definite 3x3 mass matrix by its Schur complement."""
        m11, m22, m33 = self.m
        a, b = -self.mass_slug*self.cg_y_ft, self.mass_slug*self.cg_x_ft
        dr = (rhs[2]-a*rhs[0]/m11-b*rhs[1]/m22)/(m33-a*a/m11-b*b/m22)
        return (rhs[0]-a*dr)/m11, (rhs[1]-b*dr)/m22, dr


@dataclass
class Event:
    t: float
    name: str


@dataclass
class Trace:
    t: list[float] = field(default_factory=list)
    states: list[State] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    steps: int = 0


Forces = Callable[[float, State], tuple[float, float, float]]   # body-frame (X, Y, N) external wrench


def _deriv(p: BodyParams, s: State, w: tuple[float, float, float]) -> State:
    x, y, psi, u, v, r = s
    m11, m22, m33 = p.m
    nu = (u, v, r)
    fx = w[0] - p.damping_lin[0] * u - p.damping_quad[0] * abs(u) * u
    fy = w[1] - p.damping_lin[1] * v - p.damping_quad[1] * abs(v) * v
    fn = w[2] - p.damping_lin[2] * r - p.damping_quad[2] * abs(r) * r
    c, sn = math.cos(psi), math.sin(psi)
    if p.cg_x_ft == p.cg_y_ft == 0:
        # Preserve existing centered-body trajectories and their numerical ordering.
        acceleration = ((fx + m22 * v * r) / m11, (fy - m11 * u * r) / m22,
                        (fn - (m22 - m11) * u * v) / m33)
    else:
        px, py, _ = p.momentum(nu)
        acceleration = p.acceleration((fx+r*py, fy-r*px, fn+v*px-u*py))
    return (u * c - v * sn, u * sn + v * c, r, *acceleration)


def rk4(p: BodyParams, forces: Forces, t: float, s: State, dt: float) -> State:
    def f(tt, ss):
        return _deriv(p, ss, forces(tt, ss))
    k1 = f(t, s)
    k2 = f(t + dt / 2, tuple(a + dt / 2 * b for a, b in zip(s, k1)))
    k3 = f(t + dt / 2, tuple(a + dt / 2 * b for a, b in zip(s, k2)))
    k4 = f(t + dt, tuple(a + dt * b for a, b in zip(s, k3)))
    return tuple(a + dt / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(s, k1, k2, k3, k4))


def kinetic_energy(p: BodyParams, s: State) -> float:
    if p.cg_x_ft == p.cg_y_ft == 0:
        m11, m22, m33 = p.m
        return 0.5 * (m11 * s[3] ** 2 + m22 * s[4] ** 2 + m33 * s[5] ** 2)
    return 0.5 * sum(a*b for a,b in zip(s[3:], p.momentum(s[3:])))


def simulate(p: BodyParams, forces: Forces, s0: State, t_end: float, dt: float, *, sample_dt: float | None = None,
             events: dict[str, Callable[[float, State], float]] | None = None, gap: Callable[[State], float] | None = None,
             min_dt: float = 1e-5) -> Trace:
    """Integrate to `t_end`. `events` map a name to g(t, s); a sign change of g is an event whose time is found to ~1e-9 s.
    `gap(s)` (distance to the nearest contact change, ft) shortens the step so contact is not stepped over."""
    sample_dt = sample_dt or dt
    tr = Trace()
    t, s = 0.0, s0
    next_sample = 0.0
    sign = {k: (1 if g(0.0, s0) > 0 else -1) for k, g in (events or {}).items()}
    def sample():
        nonlocal next_sample
        while next_sample <= t + 1e-12:
            tr.t.append(next_sample); tr.states.append(s)
            next_sample += sample_dt
    sample()
    while t < t_end - 1e-12:
        h = min(dt, t_end - t)
        if gap is not None:
            speed = max(abs(s[3]), abs(s[4]), 1e-9)
            h = max(min(h, 0.25 * max(gap(s), 0.0) / speed), min_dt) if gap(s) < 5.0 * speed * dt else h
        s1 = rk4(p, forces, t, s, h)
        hit = None
        for name, g in (events or {}).items():
            new = 1 if g(t + h, s1) > 0 else -1
            if new != sign[name]:
                lo, hi = 0.0, h
                for _ in range(60):
                    mid = 0.5 * (lo + hi)
                    sm = rk4(p, forces, t, s, mid)
                    if (1 if g(t + mid, sm) > 0 else -1) == sign[name]:
                        lo = mid
                    else:
                        hi = mid
                    if hi - lo < 1e-9:
                        break
                if hit is None or hi < hit[0]:
                    hit = (hi, name, new)
        if hit is not None:
            hh, name, new = hit
            s1 = rk4(p, forces, t, s, hh)
            tr.events.append(Event(t + hh, name))
            sign[name] = new
            h = hh
            for other, g in (events or {}).items():     # simultaneous events at the same instant keep their order by name
                if other != name and (1 if g(t + h, s1) > 0 else -1) != sign[other] and abs(g(t + h, s1)) < 1e-9:
                    tr.events.append(Event(t + h, other))
                    sign[other] = -sign[other]
        t, s = t + h, s1
        tr.steps += 1
        sample()
    return tr


# ---------- moored configuration built from the equilibrium System ----------

class MooredBody:
    """Forces on a hull from the same lines, fenders, tugs and environment the static solver uses (consistency by construction).

    `system` is a `mechanics.equilibrium.System`. Contact and line events are exposed for `simulate`."""

    def __init__(self, system, params: BodyParams):
        self.system, self.params = system, params
        self.frame: ShipFrame = system.frame

    def pose(self, s: State) -> Pose:
        f = self.frame
        return Pose(s[0] - f.ref_x_ft, s[1] - f.ref_y_ft, s[2] - f.psi0)

    def state_at(self, pose: Pose, u=0.0, v=0.0, r=0.0) -> State:
        f = self.frame
        return (f.ref_x_ft + pose.dx_ft, f.ref_y_ft + pose.dy_ft, f.psi0 + pose.dyaw_rad, u, v, r)

    def forces(self, t: float, s: State) -> tuple[float, float, float]:
        pose = self.pose(s)
        w = self.system.total_wrench(pose)         # berth-frame force and moment about the reference point
        c, sn = math.cos(s[2]), math.sin(s[2])
        return (c * w.fx_lbf + sn * w.fy_lbf, -sn * w.fx_lbf + c * w.fy_lbf, w.mz_ftlbf)

    def fender_deflections(self, s: State) -> list[float]:
        return [d for _, d, _ in self.system.fender_loads(self.pose(s))]

    def contact_gap(self, s: State) -> float:
        """Smallest hull-to-fender distance (ft) over fenders in range; large when none is near."""
        pose, best = self.pose(s), 1e9
        for fr in self.system.fenders:
            hit = fr.model.hull_y(self.frame, pose, fr.hull_side_y, fr.half_len)
            if hit is not None:
                best = min(best, abs(hit[0] - fr.model.face_y_ft))
        return best

    def energy(self, s: State) -> float:
        """Kinetic + stored line and fender energy (conservative parts only)."""
        pose = self.pose(s)
        e = kinetic_energy(self.params, s)
        for fr, d, _ in self.system.fender_loads(pose):
            e += fr.model.energy(d)
        for rec, st, t in self.system.line_tensions(pose):
            strain = rec.model.strain(st.length_ft)
            if strain > 0:
                n = 400
                e += sum(rec.model.mbs_eff_lbf * rec.model.curve.fraction(strain * (i + 0.5) / n) * strain / n * rec.model.rest_length_ft for i in range(n))
        return e

    def events(self) -> dict[str, Callable[[float, State], float]]:
        out = {}
        for i, fr in enumerate(self.system.fenders):
            out[f"contact:{fr.model.fender_id}"] = (lambda t, s, fr=fr: self.system.fender_loads(self.pose(s))[i][1] - 1e-12)
        for rec in self.system.lines:
            n = rec.ln.line_number
            out[f"taut:line-{n}"] = (lambda t, s, rec=rec: rec.model.strain(self.system.line_state(rec, self.pose(s)).length_ft))
        return out
