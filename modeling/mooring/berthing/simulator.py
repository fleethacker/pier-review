"""Berthing API adapter over shared RK4 mechanics; never vessel-qualified.

Legacy sessions retain the original arbitrary demonstration body. Opt-in controls
carry explicit synthetic/supplied mass, payload, propulsion and optional tug-body
parameters; payloads alter inertia and prescribed hydrostatic attitude. Catalog
geometry and elastic forces remain seed estimates. No qualified impact/rupture law.
"""
import math
import copy
from dataclasses import asdict

from mooring import refdata, scenarios
from mooring.core.envelopes import envelope, resolved_inputs_hash
from mooring.core.store import DocStore, save_snapshot
from mooring.core.schemas import (BerthingSimResponse, BerthingSimResult, ContactSummary, FenderResult,
    LineTension, MooringConfig, ResultManifest, ShipState, SimEvent, SimFrame, SimSeries,
    SimulationDiagnostics, SimulationTransition, TugState, Validity, ValidityReason)
from mooring.core.units import KT_TO_FPS
from mooring.mechanics.dynamics import BodyParams, MooredBody, _deriv
from mooring.mechanics.streaming import Integrator
from mooring.mechanics.equilibrium import build_system
from mooring.tugs.allocation import _bounds
from .s3_tug_geometry import (TugCommand, TugGeometryError, TugLimits, bind_push_point, slew_force,
                              target_signed, tug_contact, total_wrench)
from .forcing import ForcingSeries, ForcingUncovered, apparent_wind  # noqa: F401
from .loading import loading_state, body_params
from .propulsion import Propulsion
from .tug_dynamics import TugFleet
from mooring.core.schemas.motion_controls import MotionControlsConfig, MotionLineControlState

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
    def __init__(self, sc, initial, env, *, dt=0.1, duration=900, params=PARAMS, forcing=None,
                 controls: MotionControlsConfig | None = None, ship_override=None, tug_ids=None, guidance=None):
        self.sc, self.initial, self.env = sc.model_copy(deep=True), initial.model_copy(deep=True), env.model_copy(deep=True)
        self.ship_override = ship_override.model_copy(deep=True) if ship_override is not None else None
        if ship_override is not None and ship_override.class_id != sc.ship_class_id:
            raise ValueError("ship override must have the scenario ship class identity")
        self.ship = (self.ship_override or refdata.ship(sc.ship_class_id)).model_copy(deep=True)
        self.berth = refdata.berth(sc.berth_id)
        self.requested_tug_ids = list(tug_ids) if tug_ids is not None else None
        self.controls_config = controls.model_copy(deep=True) if controls is not None else None
        self.parameter_set = "synthetic-motion-controls-v1" if controls is not None else PARAMETER_SET
        self.motion_controls_used = controls is not None
        self.loading_spec = controls.loading.model_copy(deep=True) if controls is not None else None
        self.propulsion = Propulsion(controls.propulsion) if controls is not None else None
        if guidance is not None and self.propulsion is None:
            raise ValueError("route guidance requires an explicit propulsion configuration")
        self.initial_guidance = copy.deepcopy(guidance)
        self.guidance = copy.deepcopy(guidance)
        self.base_params = params
        self.cfg = self.sc.config or MooringConfig(ship_x_ft=initial.x_ft, side_to=sc.side_to, lines=[])
        self.system = build_system(self.ship, self.berth, self.cfg,
            {ln.spec_id: refdata.line(ln.spec_id) for ln in self.cfg.lines}, self.env,
            loading=sc.loading, lines_wet=True)
        self.all_lines = {rec.ln.line_number: rec for rec in self.system.lines}
        if len(self.all_lines) != len(self.system.lines):
            raise ValueError("line numbers must be unique for simulation commands")
        self.system.lines = []  # lines become active only through explicit line events
        self.params = params
        if self.loading_spec is not None:
            self.apply_loading(self.loading_spec)
        # Optional immutable forcing series (S2). None keeps the frozen scenario environment exactly as before.
        self.forcing_spec = forcing.model_copy(deep=True) if forcing is not None else None
        self.forcing_time_offset_s = 0.0
        self.state_inputs = []
        self.forcing = ForcingSeries(self.forcing_spec, self.env, duration) if forcing is not None else None
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
        if tug_ids is not None:
            if len(tug_ids) != len(set(tug_ids)):
                raise ValueError("tug identifiers must be unique")
            known = {tug.tug_id: tug for tug in fleet}
            if any(tid not in known for tid in tug_ids):
                raise ValueError("unknown tug identifier")
            if len(tug_ids) > len(points):
                raise ValueError("not enough distinct water-side push points for requested tugs")
            fleet = [known[tid] for tid in tug_ids]
        for tug, point in zip(fleet, points):
            self.anchors[tug.tug_id] = (tug, point, _bounds(self.ship, tug, point, 1.0))
        self.tug_attachments = {}
        if controls is not None and controls.tug_standoff_ft is not None:
            self.tug_attachments = {tid: (pp.x_ft, (1 if pp.side == "port" else -1)*
                (self.ship.beam_ft/2+controls.tug_standoff_ft)) for tid,(_,pp,_) in self.anchors.items()}
        slew_s = controls.tug_slew_s if controls is not None and controls.tug_slew_s is not None else SLEW_SECONDS
        self.tug_limits = {tid: TugLimits.from_specs(tug, pp, slew_s=slew_s)
                           for tid, (tug, pp, _) in self.anchors.items()}
        self.tug_dynamics = (TugFleet(controls.tug_dynamics,self.anchors,self.ship.beam_ft,self.berth.face_bearing_true_deg,self.ship.loa_ft)
                             if controls is not None and controls.tug_dynamics else None)
        if self.tug_dynamics is not None and dt > self.tug_dynamics.max_step()+1e-12:
            raise ValueError(f"tug dynamics require dt <= {self.tug_dynamics.max_step():g} s for supplied coefficients")
        if self.tug_dynamics is not None:
            for tid in self.tug_dynamics.ids:
                self.tug_attachments.pop(tid,None)
        self.ramps = {}  # id -> (start time, old signed force, new signed force)
        self.pending = []
        self.sequence = 0
        self.transitions, self.events = [], []
        self.contact = None
        self.impact_speed = {}  # fender_id -> lateral speed (ft/s) just before first contact
        self.max_line_tension = self.work = self.dissipated = self.event_energy = self.loading_event_energy = self.tug_event_energy = 0.0
        self.reasons = [ValidityReason(code="VESSEL_DYNAMICS_UNQUALIFIED",
            message=f"{self.parameter_set}: {'arbitrary' if controls is None else 'explicit'} synthetic mass/inertia/damping; not identified for {sc.ship_class_id}."),
            ValidityReason(code="DYNAMICS_APPROXIMATIONS", message="Quasi-static M3 environment, fixed water level; no relative-flow, wave, rupture or validated snatch model. Catalog and tug response data are estimates.")]
        self.invalid = False
        self.set_env(0.0, state)  # series must cover the start; ForcingUncovered (a ValueError) otherwise
        self.integrator = Integrator(self.params, self.forces, state, dt, events=self.crossing_functions(),
            gap=self.integration_gap if self.tug_dynamics is not None else self.body.contact_gap,
            coupled_step=self.coupled_step if self.tug_dynamics is not None else None,
            step_speed=self.integration_speed if self.tug_dynamics is not None else None,
            auxiliary_state=self.tug_dynamics.initial_state() if self.tug_dynamics is not None else ())
        if not all(math.isfinite(value) for value in state):
            raise ValueError("initial state exceeds numerical range")
        try:
            self.initial_energy = self.total_energy(state)
        except OverflowError:
            raise ValueError("initial energy exceeds numerical range") from None
        if not math.isfinite(self.initial_energy):
            raise ValueError("initial energy exceeds numerical range")
        self.track_contact(state)
        for name, fn in sorted(self.integrator.events.items()):
            if name.startswith("contact:") and fn(0,state)>0:
                self.transitions.append(SimulationTransition(t_s=0,kind="contact_start",element_id=name.split(":",1)[1]))

    def clone_for_prediction(self):
        """Independent complete mechanics snapshot; caller must hold the session lock.

        Deepcopy preserves shared record references but Python function closures are
        not rebound by deepcopy. Rebuild all model-bound integrator callbacks so
        crossing checks and stage forcing cannot mutate the original simulation.
        """
        clone = copy.deepcopy(self)
        clone.integrator.forces = clone.forces
        clone.integrator.gap = clone.integration_gap if clone.tug_dynamics is not None else clone.body.contact_gap
        clone.integrator.events = clone.crossing_functions()
        clone.integrator.coupled_step = clone.coupled_step if clone.tug_dynamics is not None else None
        clone.integrator.step_speed = clone.integration_speed if clone.tug_dynamics is not None else None
        return clone

    def reseeded(self, state, *, tug_id=None):
        """Prepare an independent observed-state run at t=0; never mutate this model.

        Active lines, actual actuator values/targets, loading and other bodies are
        retained. Future commands are discarded. Elastic preload becomes the new
        energy reference. Forcing retains its source-time phase. The session owner
        validates evidence, pauses, then swaps this model with a new run identity.
        Measured acceleration is evidence only, never an applied force.
        """
        if len(state)!=6 or not all(type(v) in (int,float) and math.isfinite(v) for v in state):
            raise ValueError("observed state must contain six finite canonical values")
        clone = self.clone_for_prediction()
        if tug_id is None:
            clone.integrator.state = tuple(float(v) for v in state)
        else:
            clone.reseed_tug(tug_id,state)
        old_t = self.t
        if clone.propulsion is not None:
            clone.propulsion.old = clone.propulsion.actual(old_t)
            clone.propulsion.start = 0.0
        clone.ramps = {tid:(0.0,clone.tug_force(tid,old_t),ramp[2]) for tid,ramp in clone.ramps.items()}
        clone.forcing_time_offset_s += old_t
        clone.integrator.t = 0.0
        clone.integrator.steps = 0
        clone.integrator.previous = (0.0,clone.integrator.state)
        clone.integrator.previous_auxiliary_state = clone.integrator.auxiliary_state
        clone.integrator.crossings.clear()
        clone.pending.clear()
        clone.sequence = 0
        if clone.guidance is not None:
            clone.guidance.next_update_s = 0.0
        clone.events,clone.transitions,clone.impact_speed = [],[],{}
        clone.contact = None
        clone.work = clone.dissipated = clone.event_energy = clone.loading_event_energy = clone.tug_event_energy = 0.0
        clone.invalid = False
        clone.reasons = [r for r in clone.reasons if r.code in ("VESSEL_DYNAMICS_UNQUALIFIED","DYNAMICS_APPROXIMATIONS")]
        clone.set_env(0.0,clone.integrator.state)
        try:
            clone.initial_energy = clone.total_energy()
        except OverflowError:
            raise ValueError("observed state energy exceeds numerical range") from None
        if not math.isfinite(clone.initial_energy):
            raise ValueError("observed state energy exceeds numerical range")
        clone.max_line_tension = max((force for _,_,force in clone.system.line_tensions(clone.body.pose(clone.integrator.state))),default=0.0)
        if any(force >= rec.model.mbs_eff_lbf for rec,_,force in clone.system.line_tensions(clone.body.pose(clone.integrator.state))):
            clone.invalid = True
            clone.reasons.append(ValidityReason(code="LINE_MBS_EXCEEDED",
                message="Observed state exceeds an active line's breaking strength; no qualified rupture law."))
        clone.track_contact(clone.integrator.state)
        for name,fn in sorted(clone.integrator.events.items()):
            if name.startswith("contact:") and fn(0,clone.integrator.state)>0:
                clone.transitions.append(SimulationTransition(t_s=0,kind="contact_start",element_id=name.split(":",1)[1]))
        clone.validity()
        return clone

    def forcing_at(self, t):
        return self.forcing.at(t+self.forcing_time_offset_s) if self.forcing is not None else (self.env,True)

    def integration_gap(self, state):
        return min(self.body.contact_gap(state),self.tug_dynamics.contact_gap(state,self.integrator.auxiliary_state))

    def integration_speed(self, state):
        return self.tug_dynamics.maximum_point_speed(state,self.integrator.auxiliary_state)

    def coupled_step(self, t, ship, auxiliary, dt):
        """One pure coupled RK4 step: all ship/tug forces use the same stage state."""
        full = (*ship,*auxiliary)
        def derivative(tt, ss):
            return (*_deriv(self.params,ss[:6],self.forces(tt,ss[:6],ss[6:])),
                    *self.tug_dynamics.derivative(ss[:6],ss[6:]))
        k1 = derivative(t,full)
        k2 = derivative(t+dt/2,tuple(a+dt*b/2 for a,b in zip(full,k1)))
        k3 = derivative(t+dt/2,tuple(a+dt*b/2 for a,b in zip(full,k2)))
        k4 = derivative(t+dt,tuple(a+dt*b for a,b in zip(full,k3)))
        out = tuple(a+dt*(b+2*c+2*d+e)/6 for a,b,c,d,e in zip(full,k1,k2,k3,k4))
        return out[:6],self.tug_dynamics.saturate_actuators(out[6:])

    def auxiliary_at(self, t=None):
        if self.tug_dynamics is None:
            return ()
        t = self.t if t is None else t
        if abs(t-self.t)<1e-9:
            return self.integrator.auxiliary_state
        return self.integrator.sample_auxiliary(t)

    def total_energy(self, state=None, auxiliary=None):
        s = state or self.integrator.state
        energy = self.body.energy(s)
        if self.tug_dynamics is not None:
            aux = self.integrator.auxiliary_state if auxiliary is None else auxiliary
            energy += self.tug_dynamics.energy(s,aux)
        return energy

    def reseed_tug(self, tug_id, state, *, reset_actuators=False):
        """Install explicit observed state; session owner must pause and start a new run.

        This is an input-boundary operation, never a steering command. It preserves
        other bodies and resets dense-output history to avoid stale interpolation.
        """
        if self.tug_dynamics is None or tug_id not in self.tug_dynamics.offsets:
            raise ValueError("tug has no independent dynamics configuration")
        if len(state)!=6 or not all(math.isfinite(v) for v in state):
            raise ValueError("tug observed state must contain six finite canonical values")
        aux = list(self.integrator.auxiliary_state)
        i = self.tug_dynamics.offsets[tug_id]
        aux[i:i+6] = state
        if reset_actuators:
            aux[i+6:i+9] = (0.0,0.0,0.0)
        self.integrator.auxiliary_state = tuple(aux)
        self.integrator.previous_auxiliary_state = tuple(aux)
        self.integrator.previous = (self.t,self.integrator.state)

    def apply_loading(self, spec):
        """Atomically replace explicit mass/geometry parameters; no velocity overwrite."""
        loaded = loading_state(spec, self.ship.loa_ft, self.ship.beam_ft)
        params = body_params(spec, loaded)
        self.loading_spec, self.params = spec.model_copy(deep=True), params
        self.system.ship_vertical_offset_ft = -loaded.sinkage_ft
        self.system.ship_roll_rad = math.radians(loaded.roll_deg)
        self.system.ship_pitch_rad = math.radians(loaded.pitch_deg)
        ship = self.ship.model_copy(deep=True)
        condition = next(x for x in ship.loading_conditions if x.name == self.sc.loading)
        condition.displacement_lt = loaded.total_weight_lbf/2240
        condition.draft_fwd_ft, condition.draft_aft_ft = loaded.draft_fwd_ft, loaded.draft_aft_ft
        self.system.ship = ship
        if hasattr(self,"body"):
            self.body.params = params
            self.integrator.params = params

    def loading_state(self, state=None, t=None):
        if self.loading_spec is None:
            return None
        s, t = state or self.integrator.state, self.t if t is None else t
        env = self.forcing_at(t)[0]
        water = env.water_level_mllw_ft
        if self.forcing is not None and "water_level_mllw_ft" not in self.forcing.supplied:
            water = None
        return loading_state(self.loading_spec, self.ship.loa_ft, self.ship.beam_ft, s, water)

    def current_body(self, s):
        """Water velocity for rudder incidence only; hull drag remains the existing damping model."""
        env = self.system.env
        angle = math.radians(self.berth.face_bearing_true_deg-env.current_set_true_deg)-s[2]
        speed = env.current_speed_kt*KT_TO_FPS
        return speed*math.cos(angle), speed*math.sin(angle)

    def propulsion_wrench(self, t, s):
        return self.propulsion.forces(t,s,self.current_body(s))[0] if self.propulsion is not None else (0.0,0.0,0.0)

    def line_control_states(self, state=None):
        pose = self.body.pose(state or self.integrator.state)
        out = []
        for n,rec in sorted(self.all_lines.items()):
            length = self.system.line_state(rec,pose).length_ft
            attached = rec in self.system.lines
            out.append(MotionLineControlState(line_number=n, attached=attached,
                paid_out_length_ft=rec.model.rest_length_ft, geometric_length_ft=length,
                extension_ft=max(0,length-rec.model.rest_length_ft),
                tension_lbf=rec.model.tension(length) if attached else None))
        return out

    @property
    def t(self): return self.integrator.t

    @property
    def forcing_revision(self): return self.forcing.revision if self.forcing else None

    def set_env(self, t, s):
        """Resolve forcing at simulation time t (an integration-stage time). No-op without a forcing series."""
        if self.forcing is None: return
        env, covered = self.forcing_at(t)
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

    def legacy_tug_wrench(self, t):
        contacts = []
        for tid in self.ramps:
            pp = self.anchors[tid][1]
            contacts.append(tug_contact(tid, pp, self.tug_force(tid, t), 0.0, self.tug_limits[tid]))
        return total_wrench(contacts)

    def tug_wrench(self, t, state=None, auxiliary=None):
        legacy = self.legacy_tug_wrench(t)
        if self.tug_dynamics is None:
            return legacy
        dynamic = self.tug_dynamics.ship_wrench(state or self.integrator.state,
            self.auxiliary_at(t) if auxiliary is None else auxiliary)
        return tuple(a+b for a,b in zip(legacy,dynamic))

    def forces(self, t, s, auxiliary=None):
        self.set_env(t, s)
        w = self.body.forces(t, s)
        return tuple(a+b+c for a,b,c in zip(w, self.tug_wrench(t,s,auxiliary), self.propulsion_wrench(t,s)))

    def schedule(self, msg):
        if self.t >= self.duration-1e-9:
            raise ValueError("simulation has ended; reset before sending commands")
        t = self.t if msg.t_s is None else msg.t_s
        if t < self.t-1e-9 or t > self.duration:
            raise ValueError("command time must be between the current simulation time and the session end")
        if len(self.pending) >= 1000:
            raise ValueError("pending command limit reached")
        if msg.type == "tug_command":
            if self.tug_dynamics is not None and msg.tug_id in self.tug_dynamics.configs:
                raise ValueError("independent tug requires tug_motion_command; direct ship-force commands are disabled")
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
        elif msg.type == "tug_motion_command":
            if self.tug_dynamics is None:
                raise ValueError("session has no independent tug dynamics")
            self.tug_dynamics.validate_order(msg)
        elif msg.type == "helm_command":
            if self.propulsion is None:
                raise ValueError("session has no explicitly configured propulsion model")
            if abs(msg.rudder_deg) > self.propulsion.spec.rudder_max_deg:
                raise ValueError("rudder order exceeds supplied actuator limit")
        elif msg.type == "loading_command":
            if self.loading_spec is None:
                raise ValueError("session has no explicitly configured loading model")
            if abs(t-self.t) > 1e-9 or any(abs(v)>1e-8 for v in self.integrator.state[3:]):
                raise ValueError("payload changes require the current simulation time and a stationary ship")
            spec = self.loading_spec.model_copy(update={"payloads":msg.payloads}, deep=True)
            loading_state(spec, self.ship.loa_ft, self.ship.beam_ft)
        elif msg.type in ("line_event", "line_control"):
            if msg.line_number not in self.all_lines:
                raise ValueError("line is not in the scenario configuration")
        else:
            raise ValueError("unsupported simulation command")
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
            elif msg.type == "tug_motion_command":
                before = self.total_energy()
                self.tug_dynamics.order(msg)
                self.tug_event_energy += self.total_energy()-before
            elif msg.type == "helm_command":
                if self.guidance is not None:
                    self.guidance.active = False
                self.propulsion.order(msg,self.t)
            elif msg.type == "loading_command":
                if any(abs(v)>1e-8 for v in self.integrator.state[3:]):
                    raise ValueError("payload changes require a stationary ship")
                before = self.body.energy(self.integrator.state)
                self.apply_loading(self.loading_spec.model_copy(update={"payloads":msg.payloads}, deep=True))
                self.loading_event_energy += self.body.energy(self.integrator.state)-before
            else:
                rec = self.all_lines[msg.line_number]
                pose = self.body.pose(self.integrator.state)
                was_taut = rec in self.system.lines and rec.model.strain(self.system.line_state(rec, pose).length_ft) > 0
                before = self.body.energy(self.integrator.state)
                if msg.type == "line_control":
                    self.motion_controls_used = True
                    if msg.paid_out_length_ft is not None:
                        rec.model.rest_length_ft = msg.paid_out_length_ft
                    attached = msg.attached
                    event = "secured" if attached is True else "released" if attached is False else "line_paid_out"
                else:
                    attached = msg.event != "released"
                    event = msg.event
                if attached is False:
                    self.system.lines = [r for r in self.system.lines if r is not rec]
                elif attached is True and rec not in self.system.lines:
                    self.system.lines.append(rec)
                is_taut = rec in self.system.lines and rec.model.strain(self.system.line_state(rec, pose).length_ft) > 0
                if was_taut != is_taut:
                    self.transitions.append(SimulationTransition(t_s=self.t, kind="line_taut" if is_taut else "line_slack",
                                                                 element_id=f"line-{msg.line_number}"))
                # 'tensioned' activates the installed rest length, never resets pretension.
                self.event_energy += self.body.energy(self.integrator.state)-before
                self.transitions.append(SimulationTransition(t_s=self.t, kind=event, element_id=f"line-{msg.line_number}"))
        return applied

    def guidance_due(self):
        return self.guidance is not None and self.guidance.active and self.guidance.next_update_s <= self.t+1e-9

    def commands_due(self):
        return bool(self.pending and self.pending[0][0] <= self.t+1e-9) or self.guidance_due()

    def apply_guidance(self):
        if not self.guidance_due():
            return 0
        order = self.guidance.order(self.t,self.integrator.state,self.params,self.propulsion.spec)
        self.propulsion.order(order,self.t)
        self.sequence += 1
        return 1

    def powers(self, t, s):
        self.set_env(t, s)
        w = self.system.env_wrench(self.body.pose(s))
        c, sn = math.cos(s[2]), math.sin(s[2])
        external = (c*w.fx_lbf+sn*w.fy_lbf, -sn*w.fx_lbf+c*w.fy_lbf, w.mz_ftlbf)
        # Dynamic tug connection forces are internal to the coupled system. Only
        # tug propulsion contributes external work; springs/dashpots are below.
        power = sum((a+b+c)*v for a,b,c,v in zip(external, self.legacy_tug_wrench(t), self.propulsion_wrench(t,s), s[3:]))
        damp = sum(d*v*v+q*abs(v)**3 for d,q,v in zip(self.params.damping_lin, self.params.damping_quad, s[3:]))
        if self.tug_dynamics is not None:
            tp,td = self.tug_dynamics.powers(s,self.auxiliary_at(t))
            power += tp; damp += td
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
            loaded = self.loading_state(s1,t1)
            if loaded is not None and loaded.validity.state == "invalid":
                raise ValueError("under-keel contact possible; seabed contact dynamics not modeled")
            if self.tug_dynamics is not None and any(c.invalid for c in self.tug_dynamics.connections(s1,self.auxiliary_at()).values()):
                raise ValueError("tug connection deformation exceeds synthetic model boundary")
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
            applied += self.apply_guidance()
            if remaining() == 0:
                return
            boundary = min(end, (math.floor((self.t+1e-9)/self.dt)+1)*self.dt,
                           self.pending[0][0] if self.pending else end,
                           self.guidance.next_update_s if self.guidance is not None and self.guidance.active else end)
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
        applied += self.apply_pending(max_commands=remaining())
        if remaining() != 0:
            self.apply_guidance()

    def validity(self):
        self.set_env(self.t, self.integrator.state)
        pose = self.body.pose(self.integrator.state)
        loads = self.system.loads_at(pose)
        from mooring.loads.service import _metadata
        _, _, validity = _metadata(self.system.ship, self.sc.loading, self.system.depth_ft(pose),
            self.system.env.water_density_kgm3, True, self.system.env.current_speed_kt, [loads], self.system.env, True)
        self.invalid |= validity.state == "invalid"
        existing = {r.code for r in self.reasons}
        self.reasons.extend(r for r in validity.reasons if r.code not in existing)
        loaded = self.loading_state()
        if loaded is not None:
            self.invalid |= loaded.validity.state == "invalid"
            existing = {r.code for r in self.reasons}
            self.reasons.extend(r for r in loaded.validity.reasons if r.code not in existing)
        if self.tug_dynamics is not None:
            existing = {r.code for r in self.reasons}
            for connection in self.tug_dynamics.connections(self.integrator.state,self.auxiliary_at()).values():
                valid = Validity.model_validate(self.tug_dynamics.validity(connection))
                self.invalid |= valid.state == "invalid"
                self.reasons.extend(r for r in valid.reasons if r.code not in existing)
                existing.update(r.code for r in valid.reasons)
        return Validity(state="invalid" if self.invalid else "limited", reasons=self.reasons)

    def diagnostics(self, state=None):
        energy = self.total_energy(state or self.integrator.state)
        return SimulationDiagnostics(parameter_set=self.parameter_set, integration_steps=self.integrator.steps,
            simulated_time_s=self.t, initial_energy_ftlbf=self.initial_energy, final_energy_ftlbf=energy,
            applied_work_ftlbf=self.work, dissipated_energy_ftlbf=self.dissipated, line_event_energy_ftlbf=self.event_energy,
            loading_event_energy_ftlbf=self.loading_event_energy if self.loading_spec is not None else None,
            tug_event_energy_ftlbf=self.tug_event_energy if self.tug_dynamics is not None else None,
            energy_residual_ftlbf=energy-self.initial_energy-self.work+self.dissipated-self.event_energy-self.loading_event_energy-self.tug_event_energy,
            integration_dt_s=self.dt)

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
        controls = self.propulsion.state(t,s,self.current_body(s)) if self.propulsion is not None else None
        loaded = self.loading_state(s,t)
        line_controls = self.line_control_states(s) if self.motion_controls_used else None
        tug_dynamics = self.tug_dynamics.controls_state(s,self.auxiliary_at(t)) if self.tug_dynamics is not None else None
        tugs = [TugState(tug_id=tid,force_lbf=abs(self.tug_force(tid,t)),
            direction_rel_deg=90 if self.tug_force(tid,t)<0 else 270) for tid in sorted(self.ramps)]
        if self.tug_dynamics is not None:
            for tid,c in self.tug_dynamics.connections(s,self.auxiliary_at(t)).items():
                fx,fy,_ = c.ship_wrench
                tugs.append(TugState(tug_id=tid,force_lbf=math.hypot(fx,fy),
                                     direction_rel_deg=math.degrees(math.atan2(-fy,fx))%360))
        return SimFrame(t_s=t, forcing_revision=self.forcing_revision, environment=environment, pose=ShipState(x_ft=s[0], y_ft=s[1],
            heading_true_deg=(self.berth.face_bearing_true_deg-math.degrees(s[2]))%360,
            u_kt=s[3]/KT_TO_FPS, v_kt=(-s[4] if self.sc.side_to=="starboard" else s[4])/KT_TO_FPS,
            r_degps=math.degrees(s[5])),
            tugs=sorted(tugs,key=lambda tug:tug.tug_id),
            lines=lines,
            fenders=fenders, alerts=alerts or [], validity=self.validity(), controls=controls,
            loading=loaded, line_controls=line_controls, tug_dynamics=tug_dynamics,
            guidance=self.guidance.state(t,s) if self.guidance is not None else None,
            state_inputs=self.state_inputs or None,forcing_time_offset_s=(self.forcing_time_offset_s
                if self.controls_config is not None or self.state_inputs or self.forcing_time_offset_s else None))


def initial_model(scenario_id, initial, *, dt=0.1, duration=900, forcing=None, controls=None, ship_override=None, tug_ids=None, guidance=None):
    sc = scenarios.get(scenario_id)
    return BerthingModel(sc, initial, scenarios.environment_for(sc), dt=dt, duration=duration, forcing=forcing,
                         controls=controls, ship_override=ship_override, tug_ids=tug_ids,guidance=guidance)


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
