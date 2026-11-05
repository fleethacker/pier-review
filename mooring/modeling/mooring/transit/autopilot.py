"""Waypoint autopilot: line-of-sight guidance, crab compensation, model-based heading control, ground-speed arrival logic.

All positions are local metres (x east, y north); headings are true bearings in degrees (clockwise from north);
yaw rate r is counterclockwise positive, so the heading error that needs a CCW (port) turn is
e_ccw = -wrap180(psi_cmd - heading).

Guidance: leg i runs from P[i-1] (P[0] is the start position) to P[i]. LOS course
    chi_d = chi_track + atan(e / Delta),  Delta = lookahead_ship_lengths * L,  e = cross-track (+ port of track)
Leg switch inside the acceptance radius or after passing the waypoint's perpendicular (along-track s > leg length).
Delta is a fixed multiple of L (default 2 L). The cross-track loop pole is U/Delta and the heading loop natural
frequency below is wn = WN_FACTOR U/L, so both scale with U/L and their ratio (WN_FACTOR Delta/L = 5 at the default) does
not change with speed: the outer (cross-track) loop stays slower than the inner (heading) loop at every speed.

Heading control (design from each vessel's own linearised dynamics, see nomoto.py). At the current speed U the
rudder-to-yaw-rate response is approximated by first-order Nomoto,  T r' + r = K delta  (K, T from nomoto.NomotoTable,
interpolated in U: gain scheduling), so with theta the CCW heading angle, T theta'' + theta' = K delta. The law
    delta = Kp e_ccw - Kd r + Ki int(e_ccw)
gives the closed loop  T s^2 + (1 + K Kd) s + K Kp = 0, and placing the poles at (wn, zeta) gives
    Kp = T wn^2 / K,    Kd = (2 zeta wn T - 1) / K,    wn = WN_FACTOR U_s / L,  zeta = ZETA = 0.9,
U_s = max(|u|, U_SCHED_MIN). For a course-unstable hull (T < 0, K < 0 in the linear model) the same expressions give
Kp > 0 and Kd > 0 (a stabilising controller); wn is also raised, when needed, so that Kd stays >= KD_MIN/K for T > 0. A small
integral term (Ki = Kp wn / TI_OVER_WN, clamped to +-3 deg of rudder, active only for small error at speed) removes
steady bias. WN_FACTOR, ZETA, TI_OVER_WN are controller design choices (not ship data), checked by the benchmarks in
docs/PORT_TRANSIT.md section 3. Moving astern (u < 0) the rudder command is inverted (the rudder acts on the astern
flow with opposite sign); the Nomoto model is then not valid and heading is held only roughly.

Crab compensation: psi_cmd = chi_d - beta_f with beta_f a 30 s low-pass of the drift angle (COG - heading), applied
only when through-water speed u > max(3 kt, 2 x current speed) (so a drift angle is not a measurement of current when the
ship is slow), clamped to +-20 deg, and decaying to zero otherwise. COG - heading is never used when moving astern.
The current is estimated as ground velocity minus water velocity (GPS minus log), a steady vector.

Speed and arrival (over ground). On a normal leg the target is the leg speed through the water, order = v_t/v_max
+ K_v (v_t - u) (feedforward linear, resistance quadratic, so a fraction of a knot of bias remains; no speed integrator).
In the arrival zone (within arrival_slowdown_nm of the end, or 2 L) the target is the along-track speed over ground g_t,
ramped linearly with remaining distance from max(v_fin + c_t, v_arr) to v_arr (c_t = along-track current, so the ramp is
continuous at its start); the engine order is (g_t - c_t)/v_max + K_v (g_t - g), g the measured along-track ground speed. The
through-water speed this needs is g_t - c_t, which is above g_t in a foul current and negative (astern) in a fair one;
astern is allowed only inside the arrival zone. `arrived`: inside the final radius with SOG <= arrival speed + 0.5 kt.
If the vessel passes the final waypoint's perpendicular outside the radius it reports `missed_approach` and re-approaches
on a new leg from where it is to the waypoint; `stopped_short` (SOG < 0.3 kt for 120 s outside the radius while the
ground-speed target exceeds 0.5 kt) is evaluated on SOG and distance, not on speed through the water.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import coefficients as C
from .geo import bearing_deg, norm360, wrap180

KT = C.KT_MPS
WN_FACTOR = 2.5                  # heading-loop natural frequency = WN_FACTOR U / L (design choice)
ZETA = 0.9                       # heading-loop damping ratio
KD_MIN = 0.5                     # Kd >= KD_MIN / K for a stable hull (keeps derivative action positive)
TI_OVER_WN = 10.0                # integral time Ti = TI_OVER_WN / wn
I_LIMIT = math.radians(3.0)
U_SCHED_MIN = 2.5 * KT           # lowest speed used for gain scheduling
CRAB_TAU = 30.0
CRAB_MIN_STW = 3.0 * KT
CRAB_CURRENT_RATIO = 2.0
CRAB_LIMIT = math.radians(20.0)
KV = 1.0 / (2 * KT)              # order per m/s of speed error (1.0 at 2 kt)
OMEGA_N = 0.03                   # rad/s, tug/thruster yaw-moment demand natural frequency
ZETA_ASSIST = 1.0
STOP_SPEED = 0.3 * KT
STOP_TIME = 120.0
ARRIVE_MARGIN = 0.5 * KT
REAPPROACH_SPEED = 6.0 * KT      # speed cap while re-approaching after a missed approach


class _GenericNomoto:
    """Fallback when no vessel model is supplied (unit tests of the logic): K' = 1, T' = 1 (labeled, nondimensional)."""

    def __init__(self, L):
        self.L = L

    def at(self, u):
        return u / self.L, self.L / u


@dataclass
class Command:
    psi_cmd_deg: float
    rudder_rad: float
    order: float
    v_target: float               # through-water target on a normal leg; along-track ground-speed target in the arrival ramp
    yaw_moment_demand: float      # N m, CCW positive, what the heading loop wants (for tug/thruster assist)
    in_assist_zone: bool
    braking_demand_n: float       # surge force wanted astern (N, >=0) when above target near arrival
    events: list = field(default_factory=list)


class Autopilot:
    def __init__(self, pts: list[tuple[float, float]], speeds: list[float], radii: list[float], *,
                 L: float, v_max: float, lookahead_ls: float, slow_dist_m: float, v_arrival: float,
                 max_rudder: float, m33: float, m11: float, nomoto=None, decel_plan: float | None = None):
        self.P, self.speeds, self.radii = list(pts), speeds, radii        # P has N+1 points; speeds/radii length N
        self.N = len(pts) - 1
        self.L, self.v_max, self.look, self.slow, self.v_arr = L, v_max, lookahead_ls * L, slow_dist_m, v_arrival
        self.max_rudder, self.m33, self.m11 = max_rudder, m33, m11
        self.nomoto = nomoto or _GenericNomoto(L)
        self.decel_plan = decel_plan      # m/s^2 deceleration the arrival planner may assume (None: linear ramp only)
        self.i = 1
        self.beta = 0.0
        self.integral = 0.0
        self.status = "underway"
        self.stop_timer = 0.0
        self.sat_rudder = False
        self.far_cross = False
        self.reapproach = False
        self.n_missed = 0
        self.last_corner = None       # index of the waypoint whose corner was last switched (for the cross-track metric)

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

    def cross_track_metric(self, pos) -> float:
        """|cross-track| for statistics, excluding the leg-switch corner: while within the switching region of the corner
        waypoint P[i-1] (inside its acceptance radius, or less than one lookahead distance Delta along the new leg) the
        smaller of the distances to the previous and the current leg line is used. Away from corners it is |cross_track|."""
        a, b, ln, (tx, ty) = self._leg()
        e = abs((pos[0] - a[0]) * -ty + (pos[1] - a[1]) * tx)
        if self.i < 2:
            return e
        s = (pos[0] - a[0]) * tx + (pos[1] - a[1]) * ty
        near = math.hypot(a[0] - pos[0], a[1] - pos[1]) < self.radii[self.i - 2] or s < self.look
        if not near:
            return e
        p0, p1 = self.P[self.i - 2], a
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        ln0 = math.hypot(dx, dy)
        if ln0 < 1e-6:
            return e
        e0 = abs((pos[0] - p0[0]) * -dy / ln0 + (pos[1] - p0[1]) * dx / ln0)
        return min(e, e0)

    def update(self, t, dt, pos, heading_deg, u, r, sog, cog_deg, rudder_actual, *, engine_manual=False, v=0.0) -> Command:
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
        # --- missed approach: past the final waypoint outside its radius -> new leg from here to the waypoint ---
        dist_end = math.hypot(self.P[-1][0] - pos[0], self.P[-1][1] - pos[1])
        a, b, ln, (tx, ty) = self._leg()
        if (self.status == "underway" and self.i >= self.N and not engine_manual
                and s_past(pos, a, tx, ty, ln) > 0 and dist_end > self.radii[-1]):
            self.reapproach = True
            self.n_missed += 1
            self.P[self.N - 1] = (pos[0], pos[1])
            ev.append(("missed_approach", f"passed the final waypoint {dist_end:.0f} m outside its radius; re-approaching"))
            a, b, ln, (tx, ty) = self._leg()
        e = (pos[0] - a[0]) * -ty + (pos[1] - a[1]) * tx
        chi_t = bearing_deg(tx, ty)
        chi_d = chi_t + math.degrees(math.atan(e / self.look))
        # --- water and ground velocity, current estimate (GPS minus log) ---
        hr = math.radians(heading_deg)
        wx, wy = u * math.sin(hr) - v * math.cos(hr), u * math.cos(hr) + v * math.sin(hr)
        cr = math.radians(cog_deg)
        gx, gy = sog * math.sin(cr), sog * math.cos(cr)
        cx, cy = gx - wx, gy - wy
        cur_speed = math.hypot(cx, cy)
        c_t = cx * tx + cy * ty                   # along-track current
        g_along = gx * tx + gy * ty               # along-track ground speed
        # --- crab ---
        if u > max(CRAB_MIN_STW, CRAB_CURRENT_RATIO * cur_speed) and sog > 0.5:
            tgt = max(-CRAB_LIMIT, min(CRAB_LIMIT, math.radians(wrap180(cog_deg - heading_deg))))
        else:
            tgt = 0.0
        self.beta += (tgt - self.beta) * min(1.0, dt / CRAB_TAU)
        psi_cmd = norm360(chi_d - math.degrees(self.beta))
        e_ccw = -math.radians(wrap180(psi_cmd - heading_deg))
        # --- heading: Nomoto pole placement, gain scheduled on speed ---
        us = max(abs(u), U_SCHED_MIN)
        K, T = self.nomoto.at(us)
        wn = WN_FACTOR * us / self.L
        if T > 0 and K > 0:
            wn = max(wn, (1 + KD_MIN) / (2 * ZETA * T))
        if abs(K) > 1e-9:
            kp = T * wn * wn / K
            kd = (2 * ZETA * wn * T - 1.0) / K
        else:
            kp, kd = 1.5, 0.0
        kp, kd = max(kp, 0.0), max(kd, 0.0)
        ki = kp * wn / TI_OVER_WN
        if abs(e_ccw) < 0.2 and abs(u) > 2.0:
            self.integral = max(-I_LIMIT / max(ki, 1e-9), min(I_LIMIT / max(ki, 1e-9), self.integral + e_ccw * dt))
        else:
            self.integral *= 1 - min(1.0, dt / 60.0)
        rud = kp * e_ccw - kd * r + ki * self.integral
        if u < -0.3:                       # astern: the rudder acts on reversed flow
            rud = -rud
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
        g_start = max(v_fin + c_t, self.v_arr)
        d_ramp = self.slow
        if self.slow > 0 and self.decel_plan:
            d_ramp = max(self.slow, (g_start ** 2 - self.v_arr ** 2) / (2 * self.decel_plan))
        ramp = self.slow > 0 and d_go < d_ramp
        zone = ramp or d_go < 2 * self.L
        past = self.i >= self.N and s_past(pos, a, tx, ty, ln) > 0
        if ramp:
            g_t = max(v_leg + c_t, self.v_arr)
            if d_go < self.slow:
                g_t = min(g_t, self.v_arr + (g_start - self.v_arr) * d_go / self.slow)
            if self.decel_plan:     # never ask for more deceleration than the ship can deliver (constant-deceleration profile)
                g_t = min(g_t, math.sqrt(self.v_arr ** 2 + 2 * self.decel_plan * d_go))
            if past:
                g_t = min(g_t, self.v_arr)
            if self.reapproach:
                g_t = min(g_t, max(self.v_arr, REAPPROACH_SPEED))
            v_t = g_t
            order = (g_t - c_t) / self.v_max + KV * (g_t - g_along)
            brake = max(0.0, g_along - g_t) * self.m11 / 20.0
        else:
            v_t = v_leg
            if past:
                v_t = min(v_t, self.v_arr)
            if self.reapproach:
                v_t = min(v_t, max(self.v_arr, REAPPROACH_SPEED))
            order = v_t / self.v_max + KV * (v_t - u)
            brake = max(0.0, u - v_t) * self.m11 / 20.0 if zone else 0.0
        if not zone:
            order = max(order, 0.0)
        order = max(-1.0, min(1.0, order))
        # --- yaw moment demand (CCW +) for tug/thruster assist ---
        m_des = self.m33 * (OMEGA_N ** 2 * e_ccw - 2 * ZETA_ASSIST * OMEGA_N * r)
        # --- arrival / stopped short (SOG and distance, not through-water speed) ---
        if self.status == "underway":
            if self.i >= self.N and dist_end < self.radii[-1] and sog <= self.v_arr + ARRIVE_MARGIN:
                self.status = "arrived"
                ev.append(("arrived", f"inside {self.radii[-1]:.0f} m of the final waypoint at {sog / KT:.2f} kt over ground"))
            else:
                if (not engine_manual and sog < STOP_SPEED and v_t > 0.5 * KT and dist_end > self.radii[-1]):
                    self.stop_timer += dt
                else:
                    self.stop_timer = 0.0
                if self.stop_timer > STOP_TIME:
                    self.status = "stopped_short"
                    ev.append(("stopped_short", f"SOG ~0 for over {STOP_TIME:.0f} s, {dist_end:.0f} m from the end"))
        return Command(psi_cmd, rud_cmd, order, v_t, m_des, zone, brake, ev)


def s_past(pos, a, tx, ty, ln):
    """Along-track distance beyond the end of the leg (positive after passing the final waypoint's perpendicular)."""
    return (pos[0] - a[0]) * tx + (pos[1] - a[1]) * ty - ln
