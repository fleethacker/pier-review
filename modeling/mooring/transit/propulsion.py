"""Propeller thrust, rudder (MMG-style) and bow thruster. SI units, body frame (+x fwd, +y port, yaw CCW).

Propulsion: the commanded thrust is order x T_max (ahead) or order x astern_fraction x T_max (astern). T_max is the
net thrust that balances calm deep-water resistance at max_speed (so it is calibrated, not a propeller design).
Delivered thrust follows dT/dt = (T_cmd - T)/tau_e and is an integrated state.

Rudder (positive delta turns the bow to port = trailing edge deflected to PORT, side force toward starboard acting
aft of midships). Inflow:
    u_a  = (1 - w) u                                   (wake fraction)
    u_s  = sqrt(max(u_a,0)^2 + 2 T+/(rho A_D))          (actuator-disc momentum theory, fully developed race)
    u_R  = u_a + f_race (u_s - max(u_a,0))              (race fraction at the rudder; works with u_a = 0)
    v_R  = gamma_R (v + x_R r)                          (lateral velocity at the rudder, x_R = -0.5 L)
    alpha = delta sgn(u_R) + atan2(v_R, |u_R|)          (flow from port deflects force the same way as +delta)
    F_N  = 1/2 rho A_R f_a sin(clamp(alpha, +-stall)) (u_R^2 + v_R^2)
    X = -(1 - t_R) F_N sin(delta),  Y = -(1 + a_H) F_N cos(delta),  N = -(x_R + a_H x_H) F_N cos(delta)
With x_R, x_H < 0 and delta > 0: F_N > 0, Y < 0 (toward starboard) and N > 0 (counterclockwise: bow to port).
The ship moving to port (v_R > 0) also produces alpha > 0, i.e. a restoring side force toward starboard.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import coefficients as C


@dataclass(frozen=True)
class Propulsion:
    t_max: float
    astern_fraction: float
    tau_engine: float
    area_disc: float
    area_rudder: float
    f_alpha: float
    x_r: float
    x_h: float
    rho: float
    max_rudder: float        # rad
    rudder_rate: float       # rad/s
    thruster_max: float | None   # N
    thruster_x: float

    def command_thrust(self, order: float) -> float:
        return order * self.t_max if order >= 0 else order * self.astern_fraction * self.t_max

    def rudder_forces(self, delta: float, thrust: float, u: float, v: float, r: float) -> tuple[float, float, float]:
        u_a = (1 - C.WAKE_W) * u
        u_p = max(u_a, 0.0)
        u_s = math.sqrt(u_p * u_p + 2 * max(thrust, 0.0) / (self.rho * self.area_disc))
        u_r = u_a + C.RACE_FRACTION * (u_s - u_p)
        v_r = C.GAMMA_R * (v + self.x_r * r)
        sgn = 1.0 if u_r >= 0 else -1.0
        alpha = delta * sgn + math.atan2(v_r, max(abs(u_r), 1e-3))
        stall = math.radians(C.RUDDER_STALL_DEG)
        alpha = max(-stall, min(stall, alpha))
        fn = 0.5 * self.rho * self.area_rudder * self.f_alpha * math.sin(alpha) * (u_r * u_r + v_r * v_r)
        return (-(1 - C.T_R) * fn * math.sin(delta), -(1 + C.A_H) * fn * math.cos(delta),
                -(self.x_r + C.A_H * self.x_h) * fn * math.cos(delta))

    def thruster_force(self, command: float, u: float) -> float:
        """Lateral force (+ port) of the bow thruster; effectiveness fades linearly to zero at THRUSTER_FADE_MPS."""
        if self.thruster_max is None:
            return 0.0
        return command * self.thruster_max * max(0.0, 1.0 - abs(u) / C.THRUSTER_FADE_MPS)


def build_propulsion(hull, settings, max_speed_mps: float) -> Propulsion:
    L, B, T = hull.L, hull.B, hull.T
    lam = C.RUDDER_ASPECT
    return Propulsion(
        t_max=hull.resistance(max_speed_mps), astern_fraction=settings.astern_thrust_fraction,
        tau_engine=settings.engine_time_constant_s,
        area_disc=math.pi / 4 * (C.PROP_D_OVER_T * T) ** 2,
        area_rudder=(T * L / 100.0) * (1 + 25 * (B / L) ** 2),
        f_alpha=6.13 * lam / (2.25 + lam),
        x_r=C.X_R_OVER_L * L, x_h=C.X_H_OVER_L * L, rho=hull.rho,
        max_rudder=math.radians(settings.max_rudder_deg), rudder_rate=math.radians(settings.rudder_rate_degps),
        thruster_max=None if settings.bow_thruster_lbf is None else settings.bow_thruster_lbf * C.LBF_N,
        thruster_x=C.THRUSTER_X_OVER_L * L)
