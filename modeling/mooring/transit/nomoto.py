"""Linearised steering dynamics of a vessel and its first-order Nomoto approximation (used by the heading autopilot).

Derivation. Linearise the sway-yaw equations of hull.py about steady ahead motion u = U, v = r = 0, with the engine
delivering the thrust that balances resistance, T = R(U) (the ship is in speed equilibrium, which is what the autopilot
holds on a leg). With x = (v, r), the control delta (rudder angle, + to port) and M the 2x2 inertia matrix
[[m22, m23], [m32, m33]]:

    M x' = A x + b delta
    A = [[Y_v,  Y_r - m U],      Y_v = U yv + dY_rud/dv,   Y_r = U yr L + dY_rud/dr
         [N_v,  N_r      ]]      N_v = U nv + dN_rud/dv,   N_r = U nr L + dN_rud/dr
    b = [dY_rud/ddelta, dN_rud/ddelta]

The rudder derivatives are central finite differences of `Propulsion.rudder_forces` at (delta, v, r) = 0, so they carry
the race, wake, MMG hull-interaction terms and the twin-rudder count exactly as simulated. Cross-flow drag has zero slope
at the origin and drops out. The transfer function from rudder to yaw rate is

    r/delta = (n1 s + n0) / (a s^2 + b1 s + c),  a = det M,  c = det(-A)... (see below)

with a = det(M), b1 = -(M11 A22 + M22 A11 - M12 A21 - M21 A12)  and  c = det(A)  [A11 = Y_v etc., M indices as the matrix above],
n0 = A21 b1' - A11 b2 ... computed by the explicit adjugate in `_tf`. The first-order Nomoto approximation matches the
low-frequency behaviour:

    K = n0 / c  (steady yaw rate per unit rudder, 1/s),   T = b1/c - n1/n0  (s),   T r' + r = K delta.

c = det(A) is the Clarke stability index (positive: straight-line stable). With c < 0 the ship is course-unstable: K and T
are then both negative (r grows exponentially, there is no steady turn at fixed rudder), and the same pole-placement
formulas in autopilot.py remain valid with those signs. The index is reported for the hull alone (Clarke's criterion on the
hull derivatives) and with the rudder in the loop (rudder fixed amidships adds lateral damping through v_R).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

KT = 0.5144444


@dataclass(frozen=True)
class Linear:
    U: float
    K: float                 # 1/s
    T: float                 # s (negative: course-unstable)
    c_hull: float            # det(A) with hull derivatives only
    c_total: float           # det(A) with the rudder (fixed amidships) included
    stable_hull: bool
    stable_total: bool


def _tf(M, A, b):
    """Return (n1, n0, a, b1, c) of r/delta = (n1 s + n0)/(a s^2 + b1 s + c)."""
    (m11, m12), (m21, m22) = M
    (a11, a12), (a21, a22) = A
    # (sM - A) x = b delta ; solve for x2 via Cramer's rule
    # det [[m11 s - a11, m12 s - a12], [m21 s - a21, m22 s - a22]]
    a = m11 * m22 - m12 * m21
    b1 = -(m11 * a22 + m22 * a11 - m12 * a21 - m21 * a12)
    c = a11 * a22 - a12 * a21
    # x2 numerator: det [[m11 s - a11, b1'], [m21 s - a21, b2']] = (m11 s - a11) b2 - (m21 s - a21) b1'
    n1 = m11 * b[1] - m21 * b[0]
    n0 = -a11 * b[1] + a21 * b[0]
    return n1, n0, a, b1, c


def linearise(hull, prop, U: float, thrust: float | None = None) -> Linear:
    U = max(U, 0.5)
    T = hull.resistance(U) if thrust is None else thrust
    d = 1e-4
    def rud(delta=0.0, v=0.0, r=0.0):
        f = prop.rudder_forces(delta, T, U, v, r)
        return f[1], f[2]
    dv = 1e-3
    yv_r = [(rud(v=s * dv)[i] - rud(v=-s * dv)[i]) / (2 * dv) for s in (1,) for i in (0, 1)]
    dr = 1e-5
    yr_r = [(rud(r=dr)[i] - rud(r=-dr)[i]) / (2 * dr) for i in (0, 1)]
    yd_r = [(rud(delta=d)[i] - rud(delta=-d)[i]) / (2 * d) for i in (0, 1)]
    Yv_h, Yr_h = U * hull.yv, U * hull.yr * hull.L
    Nv_h, Nr_h = U * hull.nv, U * hull.nr * hull.L
    M = ((hull.m22, hull.m23), (hull.m32, hull.m33))
    A_h = ((Yv_h, Yr_h - hull.m * U), (Nv_h, Nr_h))
    A = ((Yv_h + yv_r[0], Yr_h + yr_r[0] - hull.m * U), (Nv_h + yv_r[1], Nr_h + yr_r[1]))
    n1, n0, a, b1, c = _tf(M, A, yd_r)
    c_h = A_h[0][0] * A_h[1][1] - A_h[0][1] * A_h[1][0]
    K = n0 / c if abs(c) > 1e-30 else math.copysign(1e30, n0)
    Tn = b1 / c - n1 / n0 if abs(n0) > 1e-30 and abs(c) > 1e-30 else 1e6
    return Linear(U=U, K=K, T=Tn, c_hull=c_h, c_total=c, stable_hull=c_h > 0, stable_total=c > 0)


class NomotoTable:
    """K(U), T(U) on a speed grid (m/s), linearly interpolated; built once per vessel."""

    def __init__(self, hull, prop, u_max: float, step_kt: float = 1.0):
        n = max(2, int(math.ceil(u_max / (step_kt * KT))) + 1)
        self.us = [i * step_kt * KT for i in range(1, n + 1)]
        self.rows = [linearise(hull, prop, u) for u in self.us]

    def at(self, u: float) -> tuple[float, float]:
        us, rows = self.us, self.rows
        if u <= us[0]:
            return rows[0].K, rows[0].T
        if u >= us[-1]:
            return rows[-1].K, rows[-1].T
        i = int((u - us[0]) / (us[1] - us[0]))
        f = (u - us[i]) / (us[i + 1] - us[i])
        return rows[i].K + f * (rows[i + 1].K - rows[i].K), rows[i].T + f * (rows[i + 1].T - rows[i].T)
