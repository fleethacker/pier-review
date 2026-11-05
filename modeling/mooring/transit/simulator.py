"""S6 port transit simulator: several vessels on one fixed-step RK4 clock. See docs/PORT_TRANSIT.md.

Surrogate maneuvering model with ASSUMED propulsion; unqualified for any ship. No ship-ship interaction, bank effect,
squat or under-keel clearance. Tug hull kinematics are not modeled.

Per step (dt): (1) the autopilot (or scripted helm) computes rudder and engine commands from the state at the start of
the step; (2) actuator states that are not part of the ODE (rudder angle, tug and thruster force vectors) are advanced
by their rate limits; (3) the apparent-wind loads are evaluated once; (4) RK4 integrates position, heading, (u, v, r)
and the delivered thrust (a true ODE state, first-order lag) with rudder angle, tug/thruster forces and wind held
constant over the step (zero-order hold). Every vessel is advanced with the same dt on the same clock and never reads
another vessel's state, so adding a vessel cannot change another's trajectory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from mooring import refdata
from mooring.core.envelopes import envelope, resolved_inputs_hash
from mooring.core.schemas import (
    BodyWrench,
    EnvironmentSnapshot,
    ResultManifest,
    TrackFix,
    TransitEvent,
    TransitForces,
    TransitFrame,
    TransitResponse,
    TransitResult,
    TransitSeries,
    TransitTugState,
    TransitVesselState,
    TransitVesselSummary,
    Validity,
    ValidityReason,
)
from mooring.core.store import DocStore, save_snapshot
from mooring.loads import compute_loads
from mooring.loads.validity import wind_basis

from . import coefficients as C
from .autopilot import Autopilot
from .geo import RANGE_LIMIT_M, LocalPlane, bearing_deg, norm360
from .hull import build_hull
from .nomoto import NomotoTable
from .propulsion import build_propulsion
from .tugs import TugTrack, point_xy

CODE_VERSION = "transit-surrogate-v1"
SERIES = DocStore("transit_series", TransitSeries)
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
KT, FT, LBF = C.KT_MPS, C.FT_M, C.LBF_N
FTLBF = LBF * FT
NM = 1852.0
DEEP_FT = 1000.0
DEFAULT_SAMPLE_S = 2.0
CALM_ENV = EnvironmentSnapshot(wind_speed_kt=0.0, wind_gust_kt=0.0, wind_from_true_deg=0.0, current_speed_kt=0.0,
                               current_set_true_deg=0.0, water_level_mllw_ft=0.0)
POINT_TOL_M = 0.5               # waypoints closer than this are duplicates


class RequestInvalid(ValueError):
    """The request cannot be simulated (surfaced as HTTP 422)."""


# ----------------------------------------------------------------------------------------------------------------
class Vessel:
    def __init__(self, vt, plane: LocalPlane, env, rho: float):
        # environment=None is explicit calm: handled as a zero-wind, zero-current snapshot so that the own-motion apparent
        # wind (air drag of the moving ship) is applied exactly as for a supplied calm environment.
        env = env if env is not None else CALM_ENV
        self.vt, self.plane, self.env = vt, plane, env
        try:
            self.ship = refdata.ship(vt.ship_class_id)
            self.lc = refdata.loading(self.ship, vt.loading)
            fleet = refdata.tugs()
            self.tug_specs = {t.tug_id: t for t in fleet}
            for c in vt.tug_commands:
                refdata.tug(c.tug_id)
            for tid in (vt.tug_assist.tug_ids if vt.tug_assist else []):
                refdata.tug(tid)
        except refdata.NotFound as exc:
            raise RequestInvalid(str(exc)) from None
        vmax_kt = vt.propulsion.max_speed_kt or C.DEFAULT_MAX_SPEED_KT.get(vt.ship_class_id)
        if vmax_kt is None:
            raise RequestInvalid(f"No maximum-speed basis for ship class '{vt.ship_class_id}': supply propulsion.max_speed_kt "
                                 "(no default exists for this class and a guess is not made)")
        self.vmax_kt, self.vmax = vmax_kt, vmax_kt * KT
        self.speed_basis = "supplied" if vt.propulsion.max_speed_kt else "public nominal maximum, not a trial result"
        self.hull = build_hull(self.ship, self.lc, rho)
        self.prop = build_propulsion(self.hull, vt.propulsion, self.vmax, vt.ship_class_id)
        self.loa = self.ship.loa_ft * FT
        L = self.hull.L
        # route in local metres; P[0] is the start
        sx, sy = plane.to_local(vt.start.lat, vt.start.lon)
        pts, speeds, radii = [(sx, sy)], [], []
        for w in vt.route:
            pts.append(plane.to_local(w.lat, w.lon))
            speeds.append(w.speed_kt * KT)
            radii.append((w.acceptance_radius_ft * FT) if w.acceptance_radius_ft else 2 * L)
        self.pts = pts
        for k in range(1, len(pts)):
            if math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]) < POINT_TOL_M:
                what = "the final leg has zero length" if k == len(pts) - 1 else f"waypoints {k - 1} and {k} coincide"
                raise RequestInvalid(f"Vessel '{vt.vessel_id}': route has a degenerate leg ({what}; start counts as waypoint -1)")
        ap = vt.autopilot
        self.ap = Autopilot(pts, speeds, radii, L=L, v_max=self.vmax, lookahead_ls=ap.lookahead_ship_lengths,
                            slow_dist_m=ap.arrival_slowdown_nm * NM, v_arrival=ap.arrival_speed_kt * KT,
                            max_rudder=self.prop.max_rudder, m33=self.hull.m33, m11=self.hull.m11,
                            nomoto=NomotoTable(self.hull, self.prop, 1.2 * self.vmax),
                            decel_plan=C.DECEL_PLAN_FRACTION * vt.propulsion.astern_thrust_fraction * self.prop.t_max / self.hull.m11)
        self.far_m = 0.0  # set by prepare(): farthest route point from the plane origin
        # state: x, y, heading (rad, clockwise from north), u, v, r, delivered thrust
        u0 = vt.start.speed_kt * KT
        self.s = (sx, sy, math.radians(vt.start.heading_true_deg), u0, 0.0, 0.0, self.hull.resistance(u0) if u0 > 0 else 0.0)
        self.t = 0.0
        self.delta = 0.0
        self.order = 0.0
        self.cmd = None
        self.status = "underway"
        self.invalid = False
        vc = env.current_speed_kt * KT
        th = math.radians(env.current_set_true_deg)
        self.cur = (vc * math.sin(th), vc * math.cos(th))
        self.wind_factor = wind_basis(env, False).factor
        self.wind = (0.0, 0.0, 0.0)
        # tugs
        self.tracks: dict[str, TugTrack] = {}
        ids = list(vt.tug_assist.tug_ids) if vt.tug_assist and vt.tug_assist.tug_ids else [t.tug_id for t in fleet[:2]]
        self.assist_ids = ids[:2]
        self.auto = vt.mode == "tug_assisted" and vt.tug_assist is not None and vt.tug_assist.policy == "auto"
        self.assist_below = (vt.tug_assist.assist_below_kt * KT) if vt.tug_assist else 0.0
        self.manual_since: dict[str, float] = {}  # tug_id -> simulation time of its first manual command
        for c in vt.tug_commands:
            self.manual_since[c.tug_id] = min(c.t_s, self.manual_since.get(c.tug_id, c.t_s))
        self.tug_cmds = sorted(vt.tug_commands, key=lambda c: c.t_s)
        self.tug_idx = 0
        self.helm = sorted(vt.helm_commands, key=lambda c: c.t_s)
        self.helm_idx = 0
        self.helm_rudder = self.helm_order = None
        self.thruster_cmd = 0.0
        self.thruster_force = 0.0
        self.events: list[TransitEvent] = []
        self.tug_sat: dict[str, bool] = {}
        self.max_tug_n = 0.0
        self.max_rudder = 0.0
        self.max_xt = 0.0
        self.dist_m = 0.0
        self.arrival_t = None
        self.track: list[TrackFix] = []
        self.last_forces = None
        self.last_deficit = self.last_thr_moment = self.last_tug_remainder = 0.0

    # -- helpers -------------------------------------------------------------------------------------------------
    def track_of(self, tid):
        if tid not in self.tracks:
            self.tracks[tid] = TugTrack(tid, self.tug_specs[tid].bollard_pull_ahead_lbf * LBF)
        return self.tracks[tid]

    def ground(self, s):
        x, y, H, u, v, r, T = s
        return (u * math.sin(H) - v * math.cos(H) + self.cur[0], u * math.cos(H) + v * math.sin(H) + self.cur[1])

    def wind_wrench(self, s):
        env = self.env
        ge, gn = self.ground(s)
        w = env.wind_speed_kt * KT * self.wind_factor           # basis-converted true wind speed
        th = math.radians(env.wind_from_true_deg)
        ae, an = -w * math.sin(th) - ge, -w * math.cos(th) - gn  # air velocity relative to the ship (toward)
        app = math.hypot(ae, an)
        if app < 1e-9:
            return (0.0, 0.0, 0.0)
        frm = bearing_deg(-ae, -an)
        snap = env.model_copy(update={"wind_speed_kt": app / KT / self.wind_factor, "wind_gust_kt": app / KT / self.wind_factor,
                                      "wind_from_true_deg": norm360(frm), "current_speed_kt": 0.0})
        res = compute_loads(self.ship, self.vt.loading, norm360(math.degrees(s[2])), snap, DEEP_FT, use_gust=False)
        return (res.wind.fx_lbf * LBF, res.wind.fy_lbf * LBF, res.wind.mz_ftlbf * FTLBF)

    def components(self, s, delta, wind, tugw, thr):
        x, y, H, u, v, r, T = s
        h = self.hull.forces(u, v, r)
        p = (T, 0.0, 0.0)
        rd = self.prop.rudder_forces(delta, T, u, v, r)
        bt = (0.0, thr, self.prop.thruster_x * thr)
        return {"hull": h, "propeller": p, "rudder": rd, "wind": wind, "tugs": tugw, "bow_thruster": bt}

    def deriv(self, s, delta, wind, tugw, thr, t_cmd):
        x, y, H, u, v, r, T = s
        comps = self.components(s, delta, wind, tugw, thr)
        X = sum(c[0] for c in comps.values()); Y = sum(c[1] for c in comps.values()); N = sum(c[2] for c in comps.values())
        du, dv, dr = self.hull.accelerations(u, v, r, X, Y, N)
        return (u * math.sin(H) - v * math.cos(H) + self.cur[0], u * math.cos(H) + v * math.sin(H) + self.cur[1],
                -r, du, dv, dr, (t_cmd - T) / self.prop.tau_engine)

    # -- one step ------------------------------------------------------------------------------------------------
    def step(self, dt):
        if self.invalid or self.status == "arrived":
            # an arrived vessel is no longer integrated (state frozen; berthing simulation takes over, see docs)
            self.t += dt
            return
        s = self.s
        t = self.t
        x, y, H, u, v, r, T = s
        ge, gn = self.ground(s)
        sog = math.hypot(ge, gn)
        cog = bearing_deg(ge, gn)
        hdg = norm360(math.degrees(H))
        # scripted helm: the latest command defines both controls; a null field releases it to the autopilot
        while self.helm_idx < len(self.helm) and self.helm[self.helm_idx].t_s <= t + 1e-9:
            hc = self.helm[self.helm_idx]
            # a null field returns that control to the autopilot (schema: "a null field leaves that control to the autopilot")
            self.helm_rudder = None if hc.rudder_deg is None else math.radians(hc.rudder_deg)
            self.helm_order = hc.engine_order
            self.helm_idx += 1
        cmd = self.ap.update(t, dt, (x, y), hdg, u, r, sog, cog, self.delta, engine_manual=self.helm_order is not None, v=v)
        self.cmd = cmd
        for kind, detail in cmd.events:
            self.events.append(TransitEvent(t_s=t, vessel_id=self.vt.vessel_id, kind=kind, detail=detail))
            if kind == "arrived":
                self.arrival_t = t
        self.status = self.ap.status
        if self.status == "arrived":
            self.t = t + dt
            return
        rud_cmd = cmd.rudder_rad if self.helm_rudder is None else self.helm_rudder
        order = cmd.order if self.helm_order is None else self.helm_order
        self.advance(t, dt, rud_cmd, order, cmd.yaw_moment_demand)

    def advance(self, t, dt, rud_cmd, order, yaw_demand):
        """Physics half of a step, independent of any route or autopilot: actuators (rudder rate limit, tugs, thruster), wind
        and one RK4 step of the 3-DOF state under the given rudder angle command (rad) and engine order, held constant over dt.
        Callable from any initial state, so a route-free 'predict from state for N seconds' is a loop over advance()."""
        s = self.s
        x, y, H, u, v, r, T = s
        self.order = order
        # rudder: rate and angle limits
        lim = self.prop.rudder_rate * dt
        self.delta = max(-self.prop.max_rudder, min(self.prop.max_rudder, self.delta + max(-lim, min(lim, rud_cmd - self.delta))))
        # tugs: scripted commands, then automatic assist, then slew
        while self.tug_idx < len(self.tug_cmds) and self.tug_cmds[self.tug_idx].t_s <= t + 1e-9:
            c = self.tug_cmds[self.tug_idx]
            self.tug_idx += 1
            tr = self.track_of(c.tug_id)
            tr.set_point(c.point, *point_xy(c.point, self.loa, self.hull.B))
            self.flag_sat(t, tr, tr.command(c.force_lbf * LBF, c.direction_rel_deg, "command"))
        rud_n = self.prop.rudder_forces(self.delta, T, u, v, r)[2]
        deficit = yaw_demand - rud_n
        if (deficit > 0) != (yaw_demand > 0):
            deficit = 0.0
        # yaw-moment allocation: the bow thruster (any mode) takes the deficit first, tugs the remainder
        thr_target, remainder = self.allocate_yaw(deficit, u)
        self.last_deficit, self.last_thr_moment, self.last_tug_remainder = deficit, thr_target * self.prop.thruster_x, remainder
        assisting = self.auto and abs(u) < self.assist_below
        if assisting:
            self.auto_assist(t, remainder, self.cmd.braking_demand_n if self.cmd else 0.0)
        else:
            self.release_auto_assist(t)
        for tr in self.tracks.values():
            tr.slew(dt)
            self.max_tug_n = max(self.max_tug_n, tr.magnitude())
        tw = [0.0, 0.0, 0.0]
        for tr in self.tracks.values():
            w = tr.wrench()
            tw = [tw[i] + w[i] for i in range(3)]
        # bow thruster (any mode): supplies the same yaw-moment deficit, fading with speed
        if self.prop.thruster_max is not None:
            target = thr_target
            step = self.prop.thruster_max / C.THRUSTER_SLEW_S * dt
            self.thruster_force += max(-step, min(step, target - self.thruster_force))
        self.wind = self.wind_wrench(s)
        t_cmd = self.prop.command_thrust(order)
        args = (self.delta, self.wind, tuple(tw), self.thruster_force, t_cmd)
        k1 = self.deriv(s, *args)
        s2 = tuple(a + 0.5 * dt * b for a, b in zip(s, k1))
        k2 = self.deriv(s2, *args)
        s3 = tuple(a + 0.5 * dt * b for a, b in zip(s, k2))
        k3 = self.deriv(s3, *args)
        s4 = tuple(a + dt * b for a, b in zip(s, k3))
        k4 = self.deriv(s4, *args)
        new = tuple(a + dt / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(s, k1, k2, k3, k4))
        self.t = t + dt
        if not all(math.isfinite(q) for q in new) or max(abs(new[3]), abs(new[4])) > 60:
            self.invalid = True
            self.events.append(TransitEvent(t_s=self.t, vessel_id=self.vt.vessel_id, kind="integration_failed",
                                            detail="non-finite or implausible state"))
            return
        self.dist_m += math.hypot(new[0] - x, new[1] - y)
        self.s = new
        self.max_rudder = max(self.max_rudder, abs(self.delta))
        self.max_xt = max(self.max_xt, self.ap.cross_track_metric((new[0], new[1])))

    def flag_sat(self, t, tr, over):
        if over and not self.tug_sat.get(tr.tug_id):
            self.events.append(TransitEvent(t_s=t, vessel_id=self.vt.vessel_id, kind="tug_saturated",
                                            detail=f"{tr.tug_id} demand exceeds bollard pull {tr.capacity_n / LBF:.0f} lbf"))
        self.tug_sat[tr.tug_id] = over

    def allocate_yaw(self, deficit, u):
        """Split the yaw-moment deficit (N m, CCW +): the bow thruster first (limited by its capacity at this speed),
        the remainder to the tugs. Returns (thruster force target, N; remaining moment for tugs, N m)."""
        if self.prop.thruster_max is None:
            return 0.0, deficit
        self.thruster_cmd = max(-1.0, min(1.0, deficit / (self.prop.thruster_x * self.prop.thruster_max)))
        force = self.prop.thruster_force(self.thruster_cmd, u)
        # capacity: effectiveness fades with speed, so a command of +-1 may not deliver the full demand
        return force, deficit - force * self.prop.thruster_x

    def is_manual(self, tid, t) -> bool:
        """A tug belongs to the operator only from its first manual command onward (simulation time), so a command
        scheduled for later never suppresses auto-assist before it is issued."""
        t0 = self.manual_since.get(tid)
        return t0 is not None and t0 <= t + 1e-9

    def release_auto_assist(self, t):
        """Outside the assist regime (speed at/above assist_below, auto policy off): tugs we were driving are commanded to
        zero (they still slew down). Tugs holding a manual command are untouched."""
        for tid, tr in self.tracks.items():
            if not self.is_manual(tid, t) and tr.source == "auto_assist":
                self.flag_sat(t, tr, tr.command(0.0, 0.0, "auto_assist"))

    def auto_assist(self, t, deficit, brake):
        """Bow and stern tugs: a yaw couple for the heading controller's deficit plus an astern braking share."""
        L = self.loa
        arm = 0.45 * L
        f_couple = abs(deficit) / (2 * arm)
        cdir_bow = 270.0 if deficit > 0 else 90.0
        for idx, tid in enumerate(self.assist_ids):
            if self.is_manual(tid, t):
                continue
            tr = self.track_of(tid)
            point = "bow" if idx == 0 else "stern"
            tr.set_point(point, *point_xy(point, L, self.hull.B))
            cdir = cdir_bow if idx == 0 else norm360(cdir_bow + 180.0)
            ux, uy = math.cos(math.radians(cdir)), -math.sin(math.radians(cdir))
            fx = f_couple * ux - brake / 2.0   # braking astern = -x
            fy = f_couple * uy
            mag = math.hypot(fx, fy)
            ang = norm360(math.degrees(math.atan2(-fy, fx))) if mag > 1e-9 else 0.0
            self.flag_sat(t, tr, tr.command(mag, ang, "auto_assist"))

    # -- output --------------------------------------------------------------------------------------------------
    def wrench_model(self, c):
        return BodyWrench(surge_lbf=c[0] / LBF, sway_lbf=c[1] / LBF, yaw_ftlbf=c[2] / FTLBF)

    def state_model(self, t) -> TransitVesselState:
        s = self.s
        x, y, H, u, v, r, T = s
        ge, gn = self.ground(s)
        sog = math.hypot(ge, gn)
        tw = [0.0, 0.0, 0.0]
        for tr in self.tracks.values():
            w = tr.wrench()
            tw = [tw[i] + w[i] for i in range(3)]
        comps = self.components(s, self.delta, self.wind, tuple(tw), self.thruster_force)
        lat, lon = self.plane.to_geo(x, y)
        tugs = []
        for tid in sorted(self.tracks):
            tr = self.tracks[tid]
            if tr.point is None:
                continue
            tx, ty = tr.x, tr.y   # body (x forward, y port) -> east/north
            e = x + tx * math.sin(H) - ty * math.cos(H)
            n = y + tx * math.cos(H) + ty * math.sin(H)
            tla, tlo = self.plane.to_geo(e, n)
            tugs.append(TransitTugState(tug_id=tid, point=tr.point, force_lbf=tr.magnitude() / LBF,
                                        direction_rel_deg=tr.direction_rel_deg(), lat=tla, lon=tlo, source=tr.source))
        return TransitVesselState(
            vessel_id=self.vt.vessel_id, lat=lat, lon=lon, x_east_ft=x / FT, y_north_ft=y / FT,
            heading_true_deg=norm360(math.degrees(H)),
            cog_true_deg=bearing_deg(ge, gn) if sog > 0.2 * KT else None, sog_kt=sog / KT, stw_kt=u / KT,
            u_kt=u / KT, v_kt=v / KT, r_degps=math.degrees(r), rudder_deg=math.degrees(self.delta),
            engine_order=self.order, thrust_lbf=T / LBF, leg_index=self.ap.leg_index,
            cross_track_ft=self.ap.cross_track((x, y)) / FT, distance_to_go_nm=self.ap.distance_to_go((x, y)) / NM,
            status="invalid" if self.invalid else self.status, tugs=tugs,
            forces=TransitForces(**{k: self.wrench_model(v_) for k, v_ in comps.items()}))


def predict_constant_commands(vt, env, horizon_s: float, rudder_deg: float, engine_order: float, dt: float = 0.2,
                              sample_s: float = 5.0, rho: float | None = None):
    """Route-free horizon prediction: from the vessel's initial state (vt.start, speed through the water, tugs as given in
    vt) hold the rudder angle and engine order constant for horizon_s and return [(t, TransitVesselState)]. No autopilot, no
    global state (many predictions can run concurrently); deterministic. vt.route is only needed to satisfy the schema."""
    plane = LocalPlane(vt.start.lat, vt.start.lon)
    water_rho = rho if rho is not None else (env.water_density_kgm3 if env is not None else C.RHO_WATER_DEFAULT)
    v = Vessel(vt, plane, env, water_rho)
    dt, every = effective_step(dt, sample_s)
    out = [(0.0, v.state_model(0.0))]
    rud = math.radians(rudder_deg)
    for k in range(1, int(horizon_s / dt + 1e-9) + 1):
        v.advance(v.t, dt, rud, engine_order, 0.0)
        if k % every == 0:
            v.wind = v.wind_wrench(v.s)
            out.append((k * dt, v.state_model(k * dt)))
    return out


# ----------------------------------------------------------------------------------------------------------------
@dataclass
class Run:
    frames: list[TransitFrame]
    events: list[TransitEvent]
    vessels: list[Vessel]
    plane: LocalPlane
    start_utc: datetime
    synthetic_epoch: bool
    sample_s: float
    t_end: float
    dt_s: float = 0.0


def prepare(req):
    """Resolve and validate; raises RequestInvalid. Returns (plane, env, rho, vessels)."""
    first = req.vessels[0].start
    o = req.origin or first
    plane = LocalPlane(o.lat, o.lon)
    env = req.environment
    rho = env.water_density_kgm3 if env is not None else C.RHO_WATER_DEFAULT
    vessels = [Vessel(v, plane, env, rho) for v in req.vessels]
    for v in vessels:
        v.far_m = max(math.hypot(*p) for p in v.pts)
    return plane, env, rho, vessels


def effective_step(dt: float, sample: float) -> tuple[float, int]:
    """dt_eff = sample / ceil(sample / dt) <= dt, so every output frame falls exactly on a multiple of the requested
    sample interval (a requested dt that does not divide the interval is shortened, never lengthened)."""
    every = max(1, math.ceil(sample / dt - 1e-9))
    return sample / every, every


def run(req, job_id: str = "local", ctx=None) -> Run:
    plane, env, rho, vessels = prepare(req)
    sample = req.sample_interval_s or DEFAULT_SAMPLE_S
    dt, every = effective_step(req.dt_s, sample)
    n_frames = int(math.floor(req.duration_s / sample + 1e-9))      # last frame at floor(duration/sample) x sample <= duration
    nsteps = n_frames * every
    start = req.start_utc or EPOCH

    def emit(k):
        t = k * sample
        for v in vessels:
            v.wind = v.wind_wrench(v.s)            # forces consistent with the reported state (also frame 0)
            st = v.state_model(t)
            v.track.append(TrackFix(t_utc=start + timedelta(seconds=t), lat=st.lat, lon=st.lon,
                                    heading_true_deg=st.heading_true_deg, cog_true_deg=st.cog_true_deg, sog_kt=st.sog_kt,
                                    quality="unknown", source=f"simulated:{job_id}"))
            v._cur = st
        frames.append(TransitFrame(t_s=t, t_utc=start + timedelta(seconds=t) if req.start_utc else None,
                                   vessels=[v._cur for v in vessels]))

    frames: list[TransitFrame] = []
    emit(0)
    last = 0
    for step in range(1, nsteps + 1):
        for v in vessels:
            v.step(dt)
        last = step
        if step % every == 0:
            emit(step // every)
            if all(v.invalid or v.status != "underway" for v in vessels):
                break                               # everything finished: stop at a sample boundary, never between frames
        if step % 500 == 0 and ctx is not None:
            ctx.check_cancelled()
            ctx.progress(step / nsteps, "Integrated simulation time")
    return_run = Run(frames, sorted((e for v in vessels for e in v.events), key=lambda e: (e.t_s, e.vessel_id)),
                     vessels, plane, start, req.start_utc is None, sample, last * dt)
    return_run.dt_s = dt
    return return_run


def validity_for(req, r: Run) -> Validity:
    reasons = [
        ValidityReason(code="TRANSIT_SURROGATE_MANEUVERING", message="Hull forces are Clarke et al. (1983) regression derivatives plus assumed "
                       "cross-flow drag and an MMG-style rudder; not identified or validated for any ship; not for navigation."),
        ValidityReason(code="PROPULSION_ASSUMED", message="No propulsion, rudder or thruster data exist: T_max is calibrated to a public nominal "
                       "maximum speed; engine lag, astern fraction, rudder size/rate and race are labeled assumptions."),
        ValidityReason(code="DEEP_WATER_NO_SQUAT_OR_BANK", message="Deep water assumed: no squat, shallow-water, bank or channel effects, no under-keel clearance check."),
        ValidityReason(code="NO_SHIP_INTERACTION", message="Vessels share one clock but exert no forces on each other; no collision or passing-distance check."),
    ]
    if any(v.vt.mode == "tug_assisted" for v in r.vessels):
        reasons.append(ValidityReason(code="TUG_KINEMATICS_NOT_MODELED", message="Tugs are force sources at hull points; tug hulls, lines and "
                       "their motion are not simulated; reported tug positions are hull contact points."))
    if req.environment is None:
        reasons.append(ValidityReason(code="CALM_ASSUMED", message="No environment supplied: calm air and still water assumed (explicit, not unknown)."))
    if r.synthetic_epoch:
        reasons.append(ValidityReason(code="SYNTHETIC_EPOCH", message="No start_utc: track timestamps count from the synthetic epoch 2000-01-01T00:00:00Z."))
    if any(v.far_m > RANGE_LIMIT_M for v in r.vessels):
        reasons.append(ValidityReason(code="GEO_TANGENT_PLANE_RANGE", message="Route extends more than 40 km from the plane origin; tangent-plane error grows beyond the documented bound."))
    if any(v.invalid for v in r.vessels):
        reasons.append(ValidityReason(code="TRANSIT_INTEGRATION_FAILED", message="A vessel's integration failed; its later output is not meaningful.",
                                      affected_components=[v.vt.vessel_id for v in r.vessels if v.invalid]))
        return Validity(state="invalid", reasons=reasons)
    return Validity(state="limited", reasons=reasons)


def simulate_transit(req, job_id, base_path, ctx=None):
    r = run(req, job_id, ctx)
    if ctx:
        ctx.check_cancelled()
    summaries = []
    for v in r.vessels:
        summaries.append(TransitVesselSummary(
            vessel_id=v.vt.vessel_id, ship_class_id=v.vt.ship_class_id, mode=v.vt.mode, arrived=v.status == "arrived",
            arrival_t_s=v.arrival_t, distance_nm=v.dist_m / NM, max_cross_track_ft=v.max_xt / FT,
            max_rudder_deg=math.degrees(v.max_rudder), max_tug_force_lbf=v.max_tug_n / LBF,
            max_speed_assumed_kt=v.vmax_kt, track=v.track))
    snapshot = {"request": req.model_dump(mode="json"), "code_version": CODE_VERSION,
                "origin": [r.plane.lat0, r.plane.lon0],
                "vessels": {v.vt.vessel_id: {"ship": v.ship.model_dump(mode="json"), "loading": v.lc.model_dump(mode="json"),
                                             "max_speed_kt": v.vmax_kt, "speed_basis": v.speed_basis,
                                             "mass_kg": v.hull.m, "t_max_n": v.prop.t_max,
                                             "tugs": {k: t.model_dump(mode="json") for k, t in v.tug_specs.items()}}
                            for v in r.vessels},
                "coefficients": [c.__dict__ for c in C.COEFFICIENT_TABLE]}
    rh = resolved_inputs_hash(snapshot)
    save_snapshot(rh, snapshot)
    SERIES[job_id] = TransitSeries(job_id=job_id, frames=r.frames)
    validity = validity_for(req, r)
    assumptions = [f"{c.name}: {c.value} [{c.status}; {c.source}]" for c in C.COEFFICIENT_TABLE]
    assumptions += [f"{v.vt.vessel_id}: max speed {v.vmax_kt:g} kt ({v.speed_basis})." for v in r.vessels]
    assumptions.append("Autopilot gains are L/U-scaled heuristics, not tuned to any ship; tugs may exceed no more than catalog bollard pull.")
    result = TransitResult(series_url=f"{base_path}/transit/simulations/{job_id}/series", vessels=summaries, events=r.events)
    return envelope(TransitResponse, model="mooring.transit.simulator", model_version="1.0.0", backend="real", request=req,
                    result=result, status="RED" if validity.state == "invalid" else "AMBER", validity=validity,
                    manifest=ResultManifest(resolved_inputs_hash=rh, code_version=CODE_VERSION,
                                            numerical_settings={"dt_s": r.dt_s, "dt_requested_s": req.dt_s, "sample_interval_s": r.sample_s, "integrator": "RK4"}),
                    assumptions=assumptions)
