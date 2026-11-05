"""Waypoint autopilot: line-of-sight guidance, crab compensation, heading PD(+I), speed control, arrival logic.

All positions are local metres (x east, y north); headings are true bearings in degrees (clockwise from north);
yaw rate r is counterclockwise positive, so the heading error that needs a CCW (port) turn is
e_ccw = -wrap180(psi_cmd - heading). Gains are heuristics scaled from L/U (documented in docs/PORT_TRANSIT.md); they
are not tuned to any real ship's autopilot.

Guidance: leg i runs from P[i-1] (P[0] is the start position) to P[i]. LOS course
    chi_d = chi_track + atan(e / Delta),  Delta = lookahead_ship_lengths * L,  e = cross-track (+ port of track)
which steers back toward the track when e > 0 (clockwise bearing increases). Leg switch inside the acceptance radius
or after passing the waypoint's perpendicular (along-track s > leg length). Crab: psi_cmd = chi_d - beta_f, where
beta_f is a 30 s low-pass of (COG - heading) when SOG > 0.5 m/s.

Speed: order = v_target / v_max (feedforward) + K_v (v_target - u) with u the surge speed through the water; the
arrival ramp lowers v_target linearly with remaining distance over arrival_slowdown_nm to arrival_speed_kt; astern is
allowed only inside the arrival zone. Feedforward is linear in speed while resistance is quadratic, so the P term
settles a small (fraction of a knot) speed bias; there is no speed integrator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import coefficients as C
from .geo import bearing_deg, norm360, wrap180

KT = C.KT_MPS
KP_HEADING = 1.5                 # rudder rad per rad of heading error (heuristic)
TD_MIN, TD_MAX = 8.0, 60.0       # derivative time clamp, s
TI = 400.0                       # integral time, s (small I)
I_LIMIT = math.radians(3.0)
CRAB_TAU = 30.0
KV = 1.0 / (2 * KT)              # order per m/s of speed error (1.0 at 2 kt)
OMEGA_N = 0.03                   # rad/s, tug/thruster yaw-moment demand natural frequency
ZETA = 1.0
STOP_SPEED = 0.3 * KT
STOP_TIME = 120.0
ARRIVE_MARGIN = 0.5 * KT


@dataclass
class Command:
    psi_cmd_deg: float
    rudder_rad: float
    order: float
    v_target: float
    yaw_moment_demand: float      # N m, CCW positive, what the heading loop wants (for tug/thruster assist)
    in_assist_zone: bool
    braking_demand_n: float       # surge force wanted astern (N, >=0) when above target near arrival
    events: list = field(default_factory=list)


class Autopilot:
    def __init__(self, pts: list[tuple[float, float]], speeds: list[float], radii: list[float], *,
                 L: float, v_max: float, lookahead_ls: float, slow_dist_m: float, v_arrival: float,
                 max_rudder: float, m33: float, m11: float):
        self.P, self.speeds, self.radii = pts, speeds, radii        # P has N+1 points; speeds/radii length N
        self.N = len(pts) - 1
        self.L, self.v_max, self.look, self.slow, self.v_arr = L, v_max, lookahead_ls * L, slow_dist_m, v_arrival
        self.max_rudder, self.m33, self.m11 = max_rudder, m33, m11
        self.i = 1
        self.beta = 0.0
        self.integral = 0.0
        self.status = "underway"
        self.stop_timer = 0.0
        self.sat_rudder = False
        self.far_cross = False

    @property
    def leg_index(self) -> int:
        return min(self.i, self.N) - 1

    def _leg(self):
        a, b = self.P[self.i - 1], self.P[self.i]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        return a, b, ln, ((dx / ln, dy / ln) if ln > 1e-6 else (0.0, 1.0))

    def distance_to_go(self, pos) -> float:
        b = self.P[min(self.i, self.N)]
        d = math.hypot(b[0] - pos[0], b[1] - pos[1])
        for k in range(self.i + 1, self.N + 1):
            d += math.hypot(self.P[k][0] - self.P[k - 1][0], self.P[k][1] - self.P[k - 1][1])
        return d

    def cross_track(self, pos) -> float:
        a, b, ln, (tx, ty) = self._leg()
        return (pos[0] - a[0]) * -ty + (pos[1] - a[1]) * tx

    def update(self, t, dt, pos, heading_deg, u, r, sog, cog_deg, rudder_actual, *, engine_manual=False) -> Command:
        ev = []
        # --- leg switching ---
        while self.i < self.N:
            a, b, ln, (tx, ty) = self._leg()
            s = (pos[0] - a[0]) * tx + (pos[1] - a[1]) * ty
            if ln < 1e-6 or math.hypot(b[0] - pos[0], b[1] - pos[1]) < self.radii[self.i - 1] or s > ln:
                ev.append(("waypoint_reached", f"waypoint {self.i - 1} reached"))
                self.i += 1
            else:
                break
        a, b, ln, (tx, ty) = self._leg()
        e = (pos[0] - a[0]) * -ty + (pos[1] - a[1]) * tx
        chi_t = bearing_deg(tx, ty)
        chi_d = chi_t + math.degrees(math.atan(e / self.look))
        # --- crab ---
        if sog > 0.5:
            self.beta += (wrap180(cog_deg - heading_deg) - self.beta) * min(1.0, dt / CRAB_TAU)
        else:
            self.beta -= self.beta * min(1.0, dt / CRAB_TAU)
        psi_cmd = norm360(chi_d - self.beta)
        e_ccw = -math.radians(wrap180(psi_cmd - heading_deg))
        # --- heading PD(+I) ---
        td = min(TD_MAX, max(TD_MIN, self.L / max(abs(u), 1.5)))
        if abs(e_ccw) < 0.2 and abs(u) > 2.0:
            self.integral = max(-I_LIMIT / (KP_HEADING / TI), min(I_LIMIT / (KP_HEADING / TI), self.integral + e_ccw * dt))
        else:
            self.integral *= 1 - min(1.0, dt / 60.0)
        rud = KP_HEADING * (e_ccw - td * r) + KP_HEADING / TI * self.integral
        rud_cmd = max(-self.max_rudder, min(self.max_rudder, rud))
        sat = abs(rud) >= self.max_rudder and abs(rudder_actual) >= 0.98 * self.max_rudder
        if sat and not self.sat_rudder:
            ev.append(("rudder_saturated", f"rudder at {math.degrees(rudder_actual):.0f} deg limit"))
        if abs(rud) < 0.9 * self.max_rudder:
            self.sat_rudder = False
        elif sat:
            self.sat_rudder = True
        # --- cross-track events ---
        if abs(e) > 0.5 * self.L and not self.far_cross:
            self.far_cross = True
            ev.append(("large_cross_track", f"cross-track {e:.0f} m exceeds half a ship length"))
        elif abs(e) < 0.25 * self.L:
            self.far_cross = False
        # --- speed ---
        d_go = self.distance_to_go(pos)
        v_leg = min(self.speeds[min(self.i, self.N) - 1], self.v_max)
        v_fin = min(self.speeds[-1], self.v_max)
        zone = self.slow > 0 and d_go < self.slow or d_go < 2 * self.L
        v_t = v_leg
        if self.slow > 0 and d_go < self.slow:
            v_t = min(v_leg, self.v_arr + max(v_fin - self.v_arr, 0.0) * d_go / self.slow)
        if self.i >= self.N and s_past(pos, a, tx, ty, ln) > 0:
            v_t = min(v_t, self.v_arr)
        order = v_t / self.v_max + KV * (v_t - u)
        if not zone:
            order = max(order, 0.0)
        order = max(-1.0, min(1.0, order))
        # --- yaw moment demand (CCW +) and braking demand for tug/thruster assist ---
        m_des = self.m33 * (OMEGA_N ** 2 * e_ccw - 2 * ZETA * OMEGA_N * r)
        brake = max(0.0, (u - v_t)) * self.m11 / 20.0 if zone else 0.0
        # --- arrival / stopped short ---
        dist_end = math.hypot(self.P[-1][0] - pos[0], self.P[-1][1] - pos[1])
        if self.status == "underway":
            if self.i >= self.N and dist_end < self.radii[-1] and u <= self.v_arr + ARRIVE_MARGIN:
                self.status = "arrived"
                ev.append(("arrived", f"inside {self.radii[-1]:.0f} m of the final waypoint at {u / KT:.2f} kt"))
            else:
                if (not engine_manual and abs(u) < STOP_SPEED and v_t > 0.5 * KT and dist_end > self.radii[-1]):
                    self.stop_timer += dt
                else:
                    self.stop_timer = 0.0
                if self.stop_timer > STOP_TIME:
                    self.status = "stopped_short"
                    ev.append(("stopped_short", f"speed ~0 for over {STOP_TIME:.0f} s, {dist_end:.0f} m from the end"))
        return Command(psi_cmd, rud_cmd, order, v_t, m_des, zone, brake, ev)


def s_past(pos, a, tx, ty, ln):
    """Along-track distance beyond the end of the leg (positive after passing the final waypoint's perpendicular)."""
    return (pos[0] - a[0]) * tx + (pos[1] - a[1]) * ty - ln
