"""Berthing API adapter over shared RK4 mechanics. Synthetic parameters, never vessel-qualified.

No hull hydrodynamic data is available. Constants below define an arbitrary
numerical demonstration body, independent of ship displacement and dimensions.
Catalog geometry/elastic forces remain seed estimates. This is not a predictive
vessel simulator, nor an impact/snatch/rupture qualification.
"""
import math
from dataclasses import asdict

from mooring import refdata, scenarios
from mooring.core.envelopes import envelope, resolved_inputs_hash
from mooring.core.store import DocStore, save_snapshot
from mooring.core.schemas import (BerthingSimResponse, BerthingSimResult, ContactSummary, FenderResult,
    LineTension, MooringConfig, ResultManifest, ShipState, SimEvent, SimFrame, SimSeries,
    SimulationDiagnostics, SimulationTransition, TugState, Validity, ValidityReason)
from mooring.core.units import KT_TO_FPS
from mooring.mechanics.dynamics import BodyParams, MooredBody
from mooring.mechanics.streaming import Integrator
from mooring.mechanics.equilibrium import build_system
from mooring.tugs.allocation import _bounds
from .s3_tug_geometry import (TugCommand, TugGeometryError, TugLimits, bind_push_point, slew_force,
                              target_signed, tug_contact, total_wrench)
from .forcing import ForcingSeries, ForcingUncovered, apparent_wind  # noqa: F401

PARAMETER_SET = "synthetic-demonstration-v1"
# Arbitrary test-body inputs, NOT estimates for any hull (lbf, ft, s).
PARAMS = BodyParams(1_000_000, 10_000_000_000, damping_lin=(100_000, 100_000, 1_000_000_000),
                    qualification="unqualified")
SLEW_SECONDS = 5.0  # demonstration actuator ramp time, not a certified tug response
MAX_STEPS = 300_000
MAX_TRANSITIONS = 10_000
SERIES = DocStore("simulation_series", SimSeries)


class _AdvanceYield(Exception):
    """Internal cooperative yield after completed work; never a physical/numerical failure."""


class BerthingModel:
    def __init__(self, sc, initial, env, *, dt=0.1, duration=900, params=PARAMS, forcing=None):
        self.sc, self.initial, self.env = sc.model_copy(deep=True), initial.model_copy(deep=True), env.model_copy(deep=True)
        self.ship, self.berth = refdata.ship(sc.ship_class_id), refdata.berth(sc.berth_id)
        self.cfg = sc.config or MooringConfig(ship_x_ft=initial.x_ft, side_to=sc.side_to, lines=[])
        self.system = build_system(self.ship, self.berth, self.cfg,
            {ln.spec_id: refdata.line(ln.spec_id) for ln in self.cfg.lines}, self.env,
            loading=sc.loading, lines_wet=True)
        self.all_lines = {rec.ln.line_number: rec for rec in self.system.lines}
        if len(self.all_lines) != len(self.system.lines):
            raise ValueError("line numbers must be unique for simulation commands")
        self.system.lines = []  # lines become active only through explicit line events
        self.params = params
        # Optional immutable forcing series (S2). None keeps the frozen scenario environment exactly as before.
        self.forcing_spec = forcing
        self.forcing = ForcingSeries(forcing, self.env, duration) if forcing is not None else None
        self.forcing_env, self.forcing_covered = None, True
        self.body = MooredBody(self.system, self.params)
        self.dt, self.duration = dt, duration
        psi = math.radians((self.berth.face_bearing_true_deg-initial.heading_true_deg+180)%360-180)
        # Legacy v_kt is toward the pier; convert its side-dependent sign to ship +port.
        v = -initial.v_kt if sc.side_to == "starboard" else initial.v_kt
        state = (initial.x_ft, initial.y_ft, psi, initial.u_kt*KT_TO_FPS, v*KT_TO_FPS, math.radians(initial.r_degps))
        self.anchors = {}
        points = sorted((p for p in self.ship.push_points if p.side != sc.side_to), key=lambda p: -p.x_ft)
        fleet = refdata.tugs()
        for tug, point in zip(fleet, points):
            self.anchors[tug.tug_id] = (tug, point, _bounds(self.ship, tug, point, 1.0))
        self.tug_limits = {tid: TugLimits.from_specs(tug, pp, slew_s=SLEW_SECONDS)
                           for tid, (tug, pp, _) in self.anchors.items()}
        self.ramps = {}  # id -> (start time, old signed force, new signed force)
        self.pending = []
        self.sequence = 0
        self.transitions, self.events = [], []
        self.contact = None
        self.impact_speed = {}  # fender_id -> lateral speed (ft/s) just before first contact
        self.max_line_tension = self.work = self.dissipated = self.event_energy = 0.0
        self.reasons = [ValidityReason(code="VESSEL_DYNAMICS_UNQUALIFIED",
            message=f"{PARAMETER_SET}: arbitrary synthetic mass/inertia/damping; not identified for {sc.ship_class_id}."),
            ValidityReason(code="DYNAMICS_APPROXIMATIONS", message="Quasi-static M3 environment, fixed water level; no relative-flow, wave, rupture or validated snatch model. Catalog and tug response data are estimates.")]
        self.invalid = False
        self.set_env(0.0, state)  # series must cover the start; ForcingUncovered (a ValueError) otherwise
        self.integrator = Integrator(self.params, self.forces, state, dt, events=self.crossing_functions(), gap=self.body.contact_gap)
        if not all(math.isfinite(value) for value in state):
            raise ValueError("initial state exceeds numerical range")
        try:
            self.initial_energy = self.body.energy(state)
        except OverflowError:
            raise ValueError("initial energy exceeds numerical range") from None
        if not math.isfinite(self.initial_energy):
            raise ValueError("initial energy exceeds numerical range")
        self.track_contact(state)
        for name, fn in sorted(self.integrator.events.items()):
            if name.startswith("contact:") and fn(0,state)>0:
                self.transitions.append(SimulationTransition(t_s=0,kind="contact_start",element_id=name.split(":",1)[1]))

    @property
    def t(self): return self.integrator.t

    @property
    def forcing_revision(self): return self.forcing.revision if self.forcing else None

    def set_env(self, t, s):
        """Resolve forcing at simulation time t (an integration-stage time). No-op without a forcing series."""
        if self.forcing is None: return
        env, covered = self.forcing.at(t)
        self.forcing_env, self.forcing_covered = env, covered
        if not covered and not any(r.code == "FORCING_UNCOVERED" for r in self.reasons):
            self.invalid = True
            self.reasons.append(ValidityReason(code="FORCING_UNCOVERED",
                message=f"Simulation time {t:g} s is past forcing series {self.forcing.revision}; last covered value held (policy: invalidate)."))
        if self.forcing.spec.vessel_relative_wind:
            env = apparent_wind(env, (self.berth.face_bearing_true_deg-math.degrees(s[2]))%360, s[3], s[4])
        self.system.env = env

    def crossing_functions(self):
        out = {}
        for fr in self.system.fenders:
            def gap(t, s, fr=fr):
                hit = fr.model.hull_y(self.system.frame, self.body.pose(s), fr.hull_side_y, fr.half_len)
                return fr.model.face_y_ft-hit[0] if hit else -1.0
            out["contact:"+fr.model.fender_id] = gap
        def taut(t, s, rec):
            if rec not in self.system.lines: return -1.0
            self.set_env(t, s)  # tide moves the line geometry (rest length is unchanged)
            return rec.model.strain(self.system.line_state(rec, self.body.pose(s)).length_ft)
        for n, rec in self.all_lines.items():
            out[f"taut:line-{n}"] = lambda t, s, rec=rec: taut(t, s, rec)
        return out

    def tug_force(self, tug_id, t):
        if tug_id not in self.ramps: return 0.0
        start, old, new = self.ramps[tug_id]
        return slew_force(old, new, self.tug_limits[tug_id], max(0.0, t-start))

    def tug_wrench(self, t):
        contacts = []
        for tid in self.ramps:
            pp = self.anchors[tid][1]
            contacts.append(tug_contact(tid, pp, self.tug_force(tid, t), 0.0, self.tug_limits[tid]))
        return total_wrench(contacts)

    def forces(self, t, s):
        self.set_env(t, s)
        w = self.body.forces(t, s)
        return tuple(a+b for a, b in zip(w, self.tug_wrench(t)))

    def schedule(self, msg):
        if self.t >= self.duration-1e-9:
            raise ValueError("simulation has ended; reset before sending commands")
        t = self.t if msg.t_s is None else msg.t_s
        if t < self.t-1e-9 or t > self.duration:
            raise ValueError("command time must be between the current simulation time and the session end")
        if len(self.pending) >= 1000:
            raise ValueError("pending command limit reached")
        if msg.type == "tug_command":
            if msg.tug_id not in self.anchors:
                raise ValueError("tug has no unique water-side push-point assignment")
            tug, pp, (lo, hi) = self.anchors[msg.tug_id]
            cmd = TugCommand(msg.tug_id, pp.push_point_id, msg.force_lbf, msg.direction_rel_deg)
            try:
                bind_push_point(cmd, self.ship.push_points, side_to=self.sc.side_to, allowed_ids=[pp.push_point_id])
            except TugGeometryError as e:
                raise ValueError(str(e)) from e
            if not lo <= target_signed(cmd) <= hi:
                raise ValueError("tug or hull push-point rating exceeded")
        elif msg.line_number not in self.all_lines:
            raise ValueError("line is not in the scenario configuration")
        self.sequence += 1
        self.pending.append((t, self.sequence, msg))
        self.pending.sort(key=lambda item: item[:2])

    def apply_pending(self, *, max_commands=None):
        applied = 0
        while (self.pending and self.pending[0][0] <= self.t+1e-9
               and (max_commands is None or applied < max_commands)):
            _, _, msg = self.pending.pop(0)
            applied += 1
            if msg.type == "tug_command":
                force = target_signed(TugCommand(msg.tug_id, self.anchors[msg.tug_id][1].push_point_id, msg.force_lbf, msg.direction_rel_deg))
                self.ramps[msg.tug_id] = (self.t, self.tug_force(msg.tug_id, self.t), force)
            else:
                rec = self.all_lines[msg.line_number]
                pose = self.body.pose(self.integrator.state)
                was_taut = rec in self.system.lines and rec.model.strain(self.system.line_state(rec, pose).length_ft) > 0
                before = self.body.energy(self.integrator.state)
                if msg.event == "released":
                    self.system.lines = [r for r in self.system.lines if r is not rec]
                elif rec not in self.system.lines:
                    self.system.lines.append(rec)
                is_taut = rec in self.system.lines and rec.model.strain(self.system.line_state(rec, pose).length_ft) > 0
                if was_taut != is_taut:
                    self.transitions.append(SimulationTransition(t_s=self.t, kind="line_taut" if is_taut else "line_slack",
                                                                 element_id=f"line-{msg.line_number}"))
                # 'tensioned' activates the installed rest length, never resets pretension.
                self.event_energy += self.body.energy(self.integrator.state)-before
                self.transitions.append(SimulationTransition(t_s=self.t, kind=msg.event, element_id=f"line-{msg.line_number}"))
        return applied

    def powers(self, t, s):
        self.set_env(t, s)
        w = self.system.env_wrench(self.body.pose(s))
        c, sn = math.cos(s[2]), math.sin(s[2])
        external = (c*w.fx_lbf+sn*w.fy_lbf, -sn*w.fx_lbf+c*w.fy_lbf, w.mz_ftlbf)
        power = sum((a+b)*v for a,b,v in zip(external, self.tug_wrench(t), s[3:]))
        damp = sum(d*v*v+q*abs(v)**3 for d,q,v in zip(self.params.damping_lin, self.params.damping_quad, s[3:]))
        return power, damp

    def advance(self, end, *, check=lambda: None, observe=lambda *args: None, max_work=None):
        """Advance on the existing grid/command boundaries, optionally yielding after bounded work.

        One work unit is an accepted integrator step (including a contact subdivision) or one command.
        A yield preserves pending commands and crossings; the next call continues the same trajectory.
        """
        if end < self.t or end > self.duration+1e-9:
            raise ValueError("invalid integration target")
        if max_work is not None and (type(max_work) is not int or max_work < 1):
            raise ValueError("max_work must be a positive integer")
        start_steps, applied = self.integrator.steps, 0
        def remaining():
            return None if max_work is None else max(0, max_work-(self.integrator.steps-start_steps)-applied)
        def observe_step(t0, s0, t1, s1):
            p0,d0 = self.powers(t0,s0); p1,d1 = self.powers(t1,s1)
            self.work += (t1-t0)*(p0+p1)/2
            self.dissipated += (t1-t0)*(d0+d1)/2
            tensions = self.system.line_tensions(self.body.pose(s1))
            self.max_line_tension = max(self.max_line_tension, *(v for _,_,v in tensions), 0)
            for rec,_,force in tensions:
                if force >= rec.model.mbs_eff_lbf:
                    self.invalid = True
                    self.reasons.append(ValidityReason(code="LINE_MBS_EXCEEDED",
                        message="Integration stopped at line breaking strength; no qualified rupture law.",
                        affected_components=[f"line-{rec.ln.line_number}"]))
                    self.events.append(SimEvent(t_s=t1,kind="line_overload",detail=f"line-{rec.ln.line_number}: breaking strength exceeded"))
                    raise ValueError("line breaking strength exceeded; rupture is not modeled")
            self.track_contact(s1, s0)
            self.validity()
            observe(t0,s0,t1,s1)
        def bounded_check():
            check()
            if self.integrator.steps >= MAX_STEPS:
                raise ValueError("integration work budget exceeded")
            if remaining() == 0:
                raise _AdvanceYield()
        while self.t < end-1e-10:
            applied += self.apply_pending(max_commands=remaining())
            if remaining() == 0:
                return
            boundary = min(end, (math.floor((self.t+1e-9)/self.dt)+1)*self.dt,
                           self.pending[0][0] if self.pending else end)
            yielded = False
            try:
                self.integrator.advance(boundary, check=bounded_check, observe=observe_step)
            except _AdvanceYield:
                yielded = True
            # A contact subdivision can yield before the requested boundary. Drain all already accepted
            # crossings now, in their original order; none may be duplicated or lost on the next chunk.
            for t, name, positive in self.integrator.crossings:
                typ, eid = name.split(":",1)
                kind = ("contact_start" if positive else "contact_end") if typ=="contact" else ("line_taut" if positive else "line_slack")
                self.transitions.append(SimulationTransition(t_s=t, kind=kind, element_id=eid))
                if kind == "contact_start":
                    self.events.append(SimEvent(t_s=t, kind="fender_contact", detail=f"Contact starts at {eid}; synthetic unqualified dynamics."))
            self.integrator.crossings.clear()
            if len(self.transitions) > MAX_TRANSITIONS:
                raise ValueError("transition output budget exceeded")
            if yielded:
                return
        self.apply_pending(max_commands=remaining())

    def validity(self):
        self.set_env(self.t, self.integrator.state)
        pose = self.body.pose(self.integrator.state)
        loads = self.system.loads_at(pose)
        from mooring.loads.service import _metadata
        _, _, validity = _metadata(self.ship, self.sc.loading, self.system.depth_ft(pose),
            self.system.env.water_density_kgm3, True, self.system.env.current_speed_kt, [loads], self.system.env, True)
        self.invalid |= validity.state == "invalid"
        existing = {r.code for r in self.reasons}
        self.reasons.extend(r for r in validity.reasons if r.code not in existing)
        return Validity(state="invalid" if self.invalid else "limited", reasons=self.reasons)

    def diagnostics(self, state=None):
        energy = self.body.energy(state or self.integrator.state)
        return SimulationDiagnostics(parameter_set=PARAMETER_SET, integration_steps=self.integrator.steps,
            simulated_time_s=self.t, initial_energy_ftlbf=self.initial_energy, final_energy_ftlbf=energy,
            applied_work_ftlbf=self.work, dissipated_energy_ftlbf=self.dissipated, line_event_energy_ftlbf=self.event_energy,
            energy_residual_ftlbf=energy-self.initial_energy-self.work+self.dissipated-self.event_energy, integration_dt_s=self.dt)

    @staticmethod
    def lateral_speed(s):
        return abs(s[3]*math.sin(s[2])+s[4]*math.cos(s[2]))

    def track_contact(self, s, before=None):
        """First-contact normal speed includes rotation at the fender, using the preceding state."""
        for fr,d,_ in self.system.fender_loads(self.body.pose(s)):
            energy = fr.model.energy(d)
            over = fr.model.rated_energy_ftlbf is not None and energy > fr.model.rated_energy_ftlbf
            if d > 0:
                # Report the speed at impact, not at peak compression (where the body is nearly stopped).
                previous = before if before is not None else s
                normal_velocity = (previous[3]*math.sin(previous[2]) + previous[4]*math.cos(previous[2])
                                   + previous[5]*(fr.model.x_ft-previous[0]))
                self.impact_speed.setdefault(fr.model.fender_id, abs(normal_velocity))
                contact = ContactSummary(lateral_speed_fps=self.impact_speed[fr.model.fender_id],
                    energy_ftlbf=energy, fender_id=fr.model.fender_id,
                    pct_rated=100*energy/fr.model.rated_energy_ftlbf if fr.model.rated_energy_ftlbf else 0,
                    status="RED" if over else "AMBER")
                if self.contact is None or contact.energy_ftlbf > self.contact.energy_ftlbf:
                    self.contact = contact

    def frame(self, state=None, t=None, alerts=None):
        s = state or self.integrator.state
        t = self.t if t is None else t
        self.set_env(t, s)
        pose = self.body.pose(s)
        environment = self.forcing.motion_environment(self.forcing_env, t, self.forcing_covered) if self.forcing else None
        fenders = []
        for fr,d,_ in self.system.fender_loads(pose):
            energy = fr.model.energy(d)
            over = fr.model.rated_energy_ftlbf is not None and energy > fr.model.rated_energy_ftlbf
            fenders.append(FenderResult(fender_id=fr.model.fender_id, reaction_lbf=fr.model.force(d), compression_ft=d,
                                        status="RED" if over else "AMBER"))
        lines = [LineTension(line_number=rec.ln.line_number,tension_lbf=force) for rec,_,force in self.system.line_tensions(pose)]
        return SimFrame(t_s=t, forcing_revision=self.forcing_revision, environment=environment, pose=ShipState(x_ft=s[0], y_ft=s[1],
            heading_true_deg=(self.berth.face_bearing_true_deg-math.degrees(s[2]))%360,
            u_kt=s[3]/KT_TO_FPS, v_kt=(-s[4] if self.sc.side_to=="starboard" else s[4])/KT_TO_FPS,
            r_degps=math.degrees(s[5])),
            tugs=[TugState(tug_id=tid, force_lbf=abs(self.tug_force(tid,t)),
                direction_rel_deg=90 if self.tug_force(tid,t)<0 else 270) for tid in sorted(self.ramps)],
            lines=lines,
            fenders=fenders, alerts=alerts or [], validity=self.validity())


def initial_model(scenario_id, initial, *, dt=0.1, duration=900, forcing=None):
    sc = scenarios.get(scenario_id)
    return BerthingModel(sc, initial, scenarios.environment_for(sc), dt=dt, duration=duration, forcing=forcing)


def simulate_berthing(req, job_id, base_path, ctx=None):
    from mooring.core.schemas import SimTugCommandMessage, SimLineEventMessage
    if req.env_mode != "steady":
        raise ValueError("gusting dynamics needs a qualified time series; use steady mode")
    m = initial_model(req.scenario_id, req.initial_state, dt=req.dt_s, duration=req.duration_s, forcing=req.forcing)
    for cmd in req.tug_commands:
        m.schedule(SimTugCommandMessage(type="tug_command", **cmd.model_dump()))
    for cmd in req.line_events:
        m.schedule(SimLineEventMessage(type="line_event", **cmd.model_dump()))
    m.apply_pending()
    frames = [m.frame()]
    spacing, next_sample = req.sample_interval_s or 1.0, req.sample_interval_s or 1.0
    def observe(t0,s0,t1,s1):
        nonlocal next_sample
        # Boundary samples are emitted after commands at that timestamp apply.
        while next_sample < t1-1e-9:
            frames.append(m.frame(m.integrator.sample(next_sample), next_sample))
            next_sample += spacing
    try:
        while m.t < req.duration_s-1e-9:
            m.advance(min(req.duration_s, (round(m.t/req.dt_s)+1)*req.dt_s),
                      check=ctx.check_cancelled if ctx else lambda: None, observe=observe)
            if next_sample <= m.t+1e-9:
                frames.append(m.frame(t=next_sample))
                next_sample += spacing
            if ctx and (m.integrator.steps % 100 == 0 or m.t >= req.duration_s-1e-9):
                ctx.progress(m.t/req.duration_s, "Integrated simulation time")
    except (ValueError, OverflowError) as exc:
        m.invalid = True
        m.reasons.append(ValidityReason(code="FORCING_UNCOVERED" if isinstance(exc, ForcingUncovered) else "DYNAMICS_INTEGRATION_FAILED", message=str(exc)))
    if not math.isclose(frames[-1].t_s,m.t,abs_tol=1e-8): frames.append(m.frame())
    if ctx: ctx.check_cancelled()
    request_json = req.model_dump(mode="json")
    if req.forcing is None: request_json.pop("forcing", None)  # default requests keep their historical hash
    snapshot = {"request":request_json, "scenario":m.sc.model_dump(mode="json"),
                "ship":m.ship.model_dump(mode="json"), "berth":m.berth.model_dump(mode="json"),
                "environment":m.env.model_dump(mode="json"), "params":asdict(m.params),
                "lines":{str(n):asdict(rec.model) for n,rec in m.all_lines.items()},
                "tugs":{tid:{"rating":t.model_dump(mode="json"),"point":p.model_dump(mode="json")} for tid,(t,p,_) in m.anchors.items()}}
    if m.forcing is not None:
        snapshot["forcing_revision"] = m.forcing.revision
    # TensionCurve is a dataclass; all snapshots remain plain JSON data.
    rh = resolved_inputs_hash(snapshot)
    save_snapshot(rh,snapshot)
    SERIES[job_id] = SimSeries(job_id=job_id,frames=frames)
    validity = m.validity()
    result = BerthingSimResult(series_url=f"{base_path}/berthing/simulations/{job_id}/series", events=m.events,
        contact=m.contact, max_line_tension_lbf=m.max_line_tension, transitions=m.transitions, diagnostics=m.diagnostics(), forcing_revision=m.forcing_revision)
    return envelope(BerthingSimResponse,model="mooring.berthing.simulator",model_version="1.0.0",backend="real",
        request=req,result=result,status="RED" if validity.state=="invalid" or (m.contact and m.contact.status=="RED") else "AMBER",
        validity=validity,manifest=ResultManifest(resolved_inputs_hash=rh,code_version="berthing-synthetic-v1"),
        assumptions=[PARAMETER_SET+": synthetic body, unqualified for every vessel.",
            "Line events activate/deactivate installed rest lengths; no rupture law or validated snatch model.",
            "Tugs assigned in catalog order to water-side push points (fore to aft); normal forces only, linear demonstration slew over five seconds."])
