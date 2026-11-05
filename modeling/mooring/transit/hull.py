"""Rigid body, added mass, hull hydrodynamics, resistance and the 3-DOF equations of motion (SI, z-up frame).

Frame: body +x forward, +y port, yaw rate r positive counterclockwise seen from above. Velocities u, v, r are
relative to the WATER (uniform current). Equations (rigid-body Coriolis terms only; the linear hydrodynamic
derivatives already contain the Munk moment):

    (m - X_udot) du/dt         = X + m v r
    (m - Y_vdot) dv/dt - Y_rdot dr/dt = Y - m u r
    -N_vdot dv/dt + (Iz - N_rdot) dr/dt = N

Clarke, Gedling & Hine (1983) give derivatives in the SNAME frame (y starboard, yaw clockwise). Flipping BOTH the y
axis and the yaw sense leaves every linear derivative and added-mass coefficient unchanged (force and velocity
change sign together), so the coefficients are used as published. The rudder is not invariant and is derived
separately in propulsion.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import coefficients as C


@dataclass(frozen=True)
class Hull:
    L: float; B: float; T: float; Cb: float; rho: float
    m: float; Iz: float
    m11: float; m22: float; m23: float; m32: float; m33: float
    yv: float; yr: float; nv: float; nr: float       # dimensional per-unit-U derivatives (multiply by U)
    S: float; k: float; ca: float
    cd: float; strips: tuple[tuple[float, float], ...]  # (x, dx) of strip centres
    u_floor: float = C.U_FLOOR

    # -- resistance ----------------------------------------------------------------------------------------
    def cf(self, speed: float) -> float:
        re = max(abs(speed), self.u_floor) * self.L / C.NU_WATER
        return 0.075 / (math.log10(re) - 2.0) ** 2

    def resistance(self, u: float) -> float:
        """R = 1/2 rho S C_T u|u|, C_T = (1+k) C_F(ITTC-57) + C_A. Positive opposes forward motion."""
        ct = (1 + self.k) * self.cf(u) + self.ca
        return 0.5 * self.rho * self.S * ct * u * abs(u)

    # -- forces ----------------------------------------------------------------------------------------------
    def forces(self, u: float, v: float, r: float) -> tuple[float, float, float]:
        """Hull force on the ship (N, N, N m) from resistance, Clarke linear derivatives and cross-flow drag."""
        U = max(math.hypot(u, v), self.u_floor)
        x = -self.resistance(u)
        y = U * (self.yv * v + self.yr * r * self.L)   # yr, nv, nr carry the L powers; see build_hull
        n = U * (self.nv * v + self.nr * r * self.L)
        h = 0.5 * self.rho * self.cd * self.T
        for xs, dx in self.strips:
            w = v + xs * r
            f = -h * w * abs(w) * dx
            y += f
            n += xs * f
        return x, y, n

    def accelerations(self, u, v, r, X, Y, N) -> tuple[float, float, float]:
        du = (X + self.m * v * r) / self.m11
        b1, b2 = Y - self.m * u * r, N
        det = self.m22 * self.m33 - self.m23 * self.m32
        dv = (b1 * self.m33 - self.m23 * b2) / det
        dr = (self.m22 * b2 - self.m32 * b1) / det
        return du, dv, dr


def clarke(L, B, T, Cb) -> dict[str, float]:
    """Nondimensional (prime-system) coefficients, Clarke, Gedling & Hine (1983)."""
    p = math.pi * (T / L) ** 2
    bl, bt = B / L, B / T
    return {
        "Yv": -p * (1 + 0.40 * Cb * bt),
        "Yr": -p * (-0.5 + 2.2 * bl - 0.080 * bt),
        "Nv": -p * (0.5 + 2.4 * T / L),
        "Nr": -p * (0.25 + 0.039 * bt - 0.56 * bl),
        "Yvd": -p * (1 + 0.16 * Cb * bt - 5.1 * bl ** 2),
        "Yrd": -p * (0.67 * bl - 0.0033 * bt ** 2),
        "Nvd": -p * (1.1 * bl - 0.041 * bt),
        "Nrd": -p * (1 / 12 + 0.017 * Cb * bt - 0.33 * bl),
    }


def build_hull(ship, loading_cond, rho: float) -> Hull:
    L, B = ship.lwl_ft * C.FT_M, ship.beam_ft * C.FT_M
    T = (loading_cond.draft_fwd_ft + loading_cond.draft_aft_ft) / 2 * C.FT_M
    Cb = ship.block_coefficient
    m = loading_cond.displacement_lt * C.LT_KG
    Iz = m * (C.IZ_RADIUS_FACTOR * L) ** 2
    c = clarke(L, B, T, Cb)
    half = 0.5 * rho
    yvd, yrd = c["Yvd"] * half * L ** 3, c["Yrd"] * half * L ** 4
    nvd, nrd = c["Nvd"] * half * L ** 4, c["Nrd"] * half * L ** 5
    vol = m / rho
    S = 1.7 * L * T + vol / T
    n = C.N_STRIPS
    dx = L / n
    strips = tuple((-L / 2 + (i + 0.5) * dx, dx) for i in range(n))
    return Hull(L=L, B=B, T=T, Cb=Cb, rho=rho, m=m, Iz=Iz,
                m11=m * (1 + C.ADDED_SURGE), m22=m - yvd, m23=-yrd, m32=-nvd, m33=Iz - nrd,
                yv=c["Yv"] * half * L ** 2,          # Y_v  = Y'_v  1/2 rho L^2 U
                yr=c["Yr"] * half * L ** 2,          # Y_r  = Y'_r  1/2 rho L^3 U  (times L at use)
                nv=c["Nv"] * half * L ** 3,          # N_v  = N'_v  1/2 rho L^3 U
                nr=c["Nr"] * half * L ** 3,          # N_r  = N'_r  1/2 rho L^4 U  (times L at use)
                S=S, k=C.FORM_K, ca=C.C_A, cd=C.CD_CROSSFLOW, strips=strips)
