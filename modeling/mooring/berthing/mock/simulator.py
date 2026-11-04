"""Mock berthing simulator (M11, Phase 2).

1-DOF sway toward the pier (mass + added mass, quadratic drag, tug and environment forces), PIANC-style
fender energy at contact. Workstream E replaces it with the 3-DOF model in docs/PLAN.md.
"""

import math

from mooring import refdata
from mooring.core.geometry import ship_heading_true
from mooring.core.schemas import (
    BerthingSimRequest,
    BerthingSimResponse,
    BerthingSimResult,
    ContactSummary,
    EnvironmentSnapshot,
    FenderResult,
    Scenario,
    ShipState,
    SimEvent,
    SimFrame,
    SimSeries,
    TugState,
)
from mooring.core.units import G_FPS2, KGM3_TO_SLUG_FT3, KT_TO_FPS, LT_TO_LB

from mooring import scenarios
from mooring.core.envelopes import envelope
from mooring.loads import compute_loads, mean_draft_ft, off_pier

MAX_CONTACT_FPS = 1.5  # NSTM Table 582-2-3 berthing velocity
SERIES: dict[str, SimSeries] = {}


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
        loads = compute_loads(self.ship, sc.loading, self.heading, env, depth)
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
