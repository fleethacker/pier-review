"""Mock berthing simulator (M11) and approach planner (M12).

Berthing: 1-DOF sway toward the pier (mass + added mass, quadratic drag, tug and environment forces), PIANC-style
fender energy at contact. Workstream E replaces it with the 3-DOF model in docs/PLAN.md.
Approach: a canned NAVSTA Norfolk route (approximate coordinates), Barrass squat for under-keel clearance.
"""

import math
from datetime import timedelta

from mooring import refdata
from mooring.core.geometry import ship_heading_true
from mooring.core.schemas import (
    ApproachSimRequest,
    ApproachSimResponse,
    ApproachSimResult,
    ApproachTrack,
    BerthingSimRequest,
    BerthingSimResponse,
    BerthingSimResult,
    ContactSummary,
    EnvironmentSnapshot,
    FenderResult,
    LatLon,
    RouteRequest,
    RouteResponse,
    RouteResult,
    Scenario,
    ShipState,
    SimEvent,
    SimFrame,
    SimSeries,
    TimeWindow,
    TrackPoint,
    TugState,
    UkcLeg,
    UkcRequest,
    UkcResponse,
    UkcResult,
    Waypoint,
)
from mooring.core.units import G_FPS2, KGM3_TO_SLUG_FT3, KT_TO_FPS, LT_TO_LB

from . import environment, scenarios
from ._common import envelope, utcnow
from .forces import crude_loads, mean_draft_ft, off_pier

MAX_CONTACT_FPS = 1.5  # NSTM Table 582-2-3 berthing velocity
SERIES: dict[str, SimSeries] = {}
TRACKS: dict[str, ApproachTrack] = {}


class BerthingModel:
    """State and stepping shared by batch runs and interactive WebSocket sessions."""

    def __init__(self, sc: Scenario, initial: ShipState, env: EnvironmentSnapshot):
        self.sc, self.env = sc, env
        self.ship, self.berth = refdata.ship(sc.ship_class_id), refdata.berth(sc.berth_id)
        lc = refdata.loading(self.ship, sc.loading)
        self.draft = mean_draft_ft(self.ship, sc.loading)
        self.mass = lc.displacement_lt * LT_TO_LB / G_FPS2
        self.added = 1.0 + 2 * self.draft / self.ship.beam_ft  # PIANC added-mass factor
        self.heading = ship_heading_true(self.berth, sc.side_to)
        self.pier_rel = 90.0 if sc.side_to == "starboard" else 270.0
        self.standoff = max((f.standoff_ft for f in self.berth.fenders), default=12.0)
        self.contact_y = self.standoff + self.ship.beam_ft / 2
        self.state = initial.model_copy()
        self.v_fps = initial.v_kt * KT_TO_FPS
        self.tugs: dict[str, TugState] = {}
        self.t = 0.0
        self.contact: ContactSummary | None = None
        self.paused = False
        depth = 45.0 + env.water_level_mllw_ft
        loads = crude_loads(self.ship, sc.loading, self.heading, env, depth)
        self.f_env_toward = -off_pier(loads.total.fy_lbf, sc.side_to)

    def command(self, tug_id: str, force_lbf: float, direction_rel_deg: float) -> None:
        self.tugs[tug_id] = TugState(tug_id=tug_id, force_lbf=force_lbf, direction_rel_deg=direction_rel_deg)

    def step(self, dt: float) -> list[SimEvent]:
        if self.paused or self.contact:
            self.t += dt
            return []
        rho = self.env.water_density_kgm3 * KGM3_TO_SLUG_FT3
        f_tug = sum(t.force_lbf * math.cos(math.radians(t.direction_rel_deg - self.pier_rel)) for t in self.tugs.values())
        drag = 0.5 * rho * 1.0 * self.ship.lwl_ft * self.draft * self.v_fps * abs(self.v_fps)
        a = (f_tug + self.f_env_toward - drag) / (self.mass * self.added)
        self.v_fps += a * dt
        y = self.state.y_ft - self.v_fps * dt
        self.t += dt
        events = []
        if y <= self.contact_y and self.v_fps > 0:
            y = self.contact_y
            fender = min(self.berth.fenders, key=lambda f: abs(f.x_ft - self.state.x_ft)) if self.berth.fenders else None
            energy = 0.5 * self.mass * self.v_fps**2 * self.added * 0.5 * 1.0 * 0.9  # Cm x Ce x Cs x Cc
            pct = 100 * energy / fender.rated_energy_ftlbf if fender else 0.0
            status = "RED" if pct > 100 or self.v_fps > MAX_CONTACT_FPS else "AMBER" if pct > 80 else "GREEN"
            self.contact = ContactSummary(lateral_speed_fps=round(self.v_fps, 3), energy_ftlbf=round(energy),
                                          fender_id=fender.fender_id if fender else "none", pct_rated=round(pct, 1),
                                          status=status)
            events.append(SimEvent(t_s=round(self.t, 1), kind="fender_contact",
                                   detail=f"Contact at {self.v_fps:.2f} ft/s, {energy:,.0f} ft-lbf ({pct:.0f}% of rating)."))
            if self.v_fps > MAX_CONTACT_FPS:
                events.append(SimEvent(t_s=round(self.t, 1), kind="speed_exceeded",
                                       detail=f"Lateral speed {self.v_fps:.2f} ft/s exceeds {MAX_CONTACT_FPS} ft/s."))
            self.v_fps = 0.0
        self.state = self.state.model_copy(update={"y_ft": round(y, 2), "v_kt": round(self.v_fps / KT_TO_FPS, 3)})
        return events

    def frame(self, alerts: list[str] | None = None) -> SimFrame:
        fenders = []
        if self.contact:
            fenders = [FenderResult(fender_id=self.contact.fender_id, reaction_lbf=round(max(self.f_env_toward, 0)),
                                    compression_ft=0.0, status=self.contact.status)]
        return SimFrame(t_s=round(self.t, 2), pose=self.state, tugs=list(self.tugs.values()), lines=[],
                        fenders=fenders, alerts=alerts or [])


def initial_model(scenario_id: str, initial: ShipState) -> BerthingModel:
    sc = scenarios.get(scenario_id)
    return BerthingModel(sc, initial, scenarios.environment_for(sc))


def simulate_berthing(req: BerthingSimRequest, job_id: str, base_path: str) -> BerthingSimResponse:
    m = initial_model(req.scenario_id, req.initial_state)
    commands = sorted(req.tug_commands, key=lambda c: c.t_s)
    events: list[SimEvent] = []
    frames: list[SimFrame] = []
    n = int(req.duration_s / req.dt_s)
    every = max(1, int(1.0 / req.dt_s))
    ci = 0
    secured: set[int] = set()
    all_lines = {ln.line_number for ln in (m.sc.config.lines if m.sc.config else [])}
    for i in range(n):
        while ci < len(commands) and commands[ci].t_s <= m.t:
            c = commands[ci]
            m.command(c.tug_id, c.force_lbf, c.direction_rel_deg)
            ci += 1
        for le in req.line_events:
            if le.event == "secured" and abs(le.t_s - m.t) < req.dt_s / 2:
                secured.add(le.line_number)
                if all_lines and secured >= all_lines:
                    events.append(SimEvent(t_s=round(m.t, 1), kind="all_fast", detail="All lines secured."))
        events += m.step(req.dt_s)
        if i % every == 0:
            frames.append(m.frame())
    SERIES[job_id] = SimSeries(job_id=job_id, frames=frames)
    status = m.contact.status if m.contact else "AMBER"
    result = BerthingSimResult(series_url=f"{base_path}/berthing/simulations/{job_id}/series", events=events,
                               contact=m.contact, max_line_tension_lbf=0.0)
    return envelope(BerthingSimResponse, model="mooring.dynamics.berthing", request=req, result=result, status=status,
                    assumptions=["Mock 1-DOF sway model; lines not modeled yet.",
                                 "Fender energy = 0.5 M v^2 Cm Ce Cs Cc with Ce 0.5, Cs 1.0, Cc 0.9 (PIANC 2002)."])


# ---------- Approach ----------

ROUTE = [  # approximate, for development only
    ("Thimble Shoal Channel entrance", 36.9590, -76.0450, 55.0, 1000.0),
    ("Thimble Shoal Channel", 36.9660, -76.1600, 55.0, 1000.0),
    ("Hampton Roads", 36.9640, -76.2700, 50.0, 1500.0),
    ("NAVSTA approach", 36.9600, -76.3150, 45.0, 800.0),
]


def route(req: RouteRequest) -> RouteResponse:
    berth = refdata.berth(req.berth_id)
    wps = [Waypoint(lat=lat, lon=lon, leg_name=n, channel_depth_mllw_ft=d, width_ft=w) for n, lat, lon, d, w in ROUTE]
    wps.append(Waypoint(lat=berth.origin_lat, lon=berth.origin_lon, leg_name=f"Berth {berth.name}",
                        channel_depth_mllw_ft=min(p.depth_mllw_ft for p in berth.depth_profile), width_ft=400.0))
    if req.origin:
        wps.insert(0, Waypoint(lat=req.origin.lat, lon=req.origin.lon, leg_name="Origin",
                               channel_depth_mllw_ft=60.0, width_ft=2000.0))
    result = RouteResult(waypoints=wps, tug_rendezvous=LatLon(lat=36.9620, lon=-76.3000),
                         abort_points=[LatLon(lat=36.9650, lon=-76.2500), LatLon(lat=36.9620, lon=-76.3000)])
    return envelope(RouteResponse, model="mooring.approach.route", request=req, result=result, status="GREEN",
                    assumptions=["Mock route with approximate coordinates; real route from NOAA ENC."])


def _leg_nm(a: Waypoint, b: Waypoint) -> float:
    dlat = (b.lat - a.lat) * 60
    dlon = (b.lon - a.lon) * 60 * math.cos(math.radians((a.lat + b.lat) / 2))
    return math.hypot(dlat, dlon)


def ukc(req: UkcRequest) -> UkcResponse:
    ship = refdata.ship(req.ship_class_id)
    draft = mean_draft_ft(ship, req.loading)
    t = req.eta_utc
    legs = []
    for i, (a, b) in enumerate(zip(req.waypoints, req.waypoints[1:])):
        v = req.speed_profile_kt[i] if i < len(req.speed_profile_kt) else req.speed_profile_kt[-1]
        squat = ship.block_coefficient * v**2 / 50 * 3.281  # Barrass, confined channel, metres -> feet
        wl = environment.synthetic(t, "forecast").water_level_mllw_ft
        ukc_ft = min(a.channel_depth_mllw_ft, b.channel_depth_mllw_ft) + wl - draft - squat
        status = "RED" if ukc_ft < 2 else "AMBER" if ukc_ft < 4 else "GREEN"
        legs.append(UkcLeg(leg_name=b.leg_name, min_ukc_ft=round(ukc_ft, 1), squat_ft=round(squat, 2),
                           water_level_ft=wl, status=status))
        t += timedelta(hours=_leg_nm(a, b) / max(v, 0.5))
    overall = "RED" if any(l.status == "RED" for l in legs) else "AMBER" if any(l.status == "AMBER" for l in legs) else "GREEN"
    return envelope(UkcResponse, model="mooring.approach.ukc", request=req,
                    result=UkcResult(legs=legs, window=TimeWindow(earliest_utc=req.eta_utc - timedelta(hours=1),
                                                                  latest_utc=req.eta_utc + timedelta(hours=2))),
                    status=overall, assumptions=["Barrass squat (confined): Cb x V^2 / 50 m.", "Mock tide."])


def simulate_approach(req: ApproachSimRequest, job_id: str, base_path: str) -> ApproachSimResponse:
    ship = refdata.ship(req.ship_class_id)
    draft = mean_draft_ft(ship, req.loading)
    pts, t_s = [], 0.0
    for i, (a, b) in enumerate(zip(req.waypoints, req.waypoints[1:])):
        v = req.speed_profile_kt[i] if i < len(req.speed_profile_kt) else req.speed_profile_kt[-1]
        hdg = math.degrees(math.atan2((b.lon - a.lon) * math.cos(math.radians(a.lat)), b.lat - a.lat)) % 360
        dur = _leg_nm(a, b) / max(v, 0.5) * 3600
        for k in range(10):
            f = k / 10
            squat = ship.block_coefficient * v**2 / 50 * 3.281
            wl = environment.synthetic(req.eta_utc + timedelta(seconds=t_s + f * dur), "forecast").water_level_mllw_ft
            pts.append(TrackPoint(lat=a.lat + f * (b.lat - a.lat), lon=a.lon + f * (b.lon - a.lon), t_s=round(t_s + f * dur),
                                  heading_true_deg=round(hdg, 1), speed_kt=v, cross_track_ft=round(20 * math.sin(k), 1),
                                  ukc_ft=round(min(a.channel_depth_mllw_ft, b.channel_depth_mllw_ft) + wl - draft - squat, 1)))
        t_s += dur
    TRACKS[job_id] = ApproachTrack(job_id=job_id, points=pts)
    min_ukc = min(p.ukc_ft for p in pts) if pts else 0.0
    result = ApproachSimResult(track_url=f"{base_path}/approach/simulations/{job_id}/track",
                               max_cross_track_ft=max(abs(p.cross_track_ft) for p in pts) if pts else 0.0,
                               min_ukc_ft=min_ukc, events=[])
    return envelope(ApproachSimResponse, model="mooring.dynamics.approach", request=req, result=result,
                    status="RED" if min_ukc < 2 else "AMBER" if min_ukc < 4 else "GREEN",
                    assumptions=["Mock straight-line track between waypoints; no maneuvering model yet."])


def now_utc():
    return utcnow()
