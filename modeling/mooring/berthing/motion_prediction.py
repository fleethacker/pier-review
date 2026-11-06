"""Bounded look-ahead of the SAME berthing model, with no session/storage side effects.

The caller captures model and identity under the session lock; this module clones
again before doing any work. Synthetic mechanics remain synthetic. Missing hazard
layers and trajectory uncertainty remain explicitly unavailable.
"""

import hashlib
import json
import math
import time
from dataclasses import fields, is_dataclass
from datetime import date, datetime

from pydantic import BaseModel
from shapely.geometry import LineString, Polygon

from mooring.core.schemas.common import Validity, ValidityReason
from mooring.core.schemas.motion import MotionPose, MotionVelocity
from mooring.core.schemas.motion_prediction import (
    MotionPredictionPoint, MotionPredictionPose, MotionPredictionRequest,
    MotionPredictionResponse, MotionPredictionSource, MotionPredictionWarning,
    MotionPredictionWork,
)

MAX_WORK = 2400
WORK_CHUNK = 1  # Check the wall deadline between every accepted step or command.
MAX_RUNTIME_S = 0.8
# This worker shares the interpreter with live session ticks and socket delivery.
# Give those short jobs a scheduling opportunity during CPU-heavy rollouts;
# these are wall-clock scheduling values, never an integration time step.
YIELD_INTERVAL_S = 0.005
YIELD_SLEEP_S = 0.001
MAX_TRANSITIONS = 512
MAX_EVENTS = 256
MAX_WARNINGS = 128
ENGINE_VERSION = "berthing-motion-prediction-v1"
EPS = 1e-8


def _plain(value):
    """Canonical snapshot including newly added data state automatically.

    Callbacks are rebound by clone_for_prediction and identified by engine
    version, never by a Python address. Unknown data objects fail loudly.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return {name: _plain(getattr(value, name)) for name in type(value).model_fields}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items() if not callable(item)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value) if not callable(getattr(value, f.name))}
    if hasattr(value, "__dict__"):
        return {name: _plain(item) for name, item in vars(value).items() if not callable(item)}
    raise TypeError(f"unsupported prediction snapshot value: {type(value).__name__}")


def _digest(value):
    return hashlib.sha256(json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def snapshot_hash(model):
    """Call only on an owned clone or while holding its session lock."""
    return _digest({"engine_version": ENGINE_VERSION, "model": model})


def _footprint(model, state):
    half_l, half_b = model.ship.loa_ft / 2, model.ship.beam_ft / 2
    c, s = math.cos(state[2]), math.sin(state[2])
    return [(state[0]+c*x-s*y, state[1]+s*x+c*y)
            for x, y in ((-half_l, -half_b), (half_l, -half_b), (half_l, half_b), (-half_l, half_b))]


class _Hazards:
    """Finite supplied pier/fender faces, checked at each accepted RK4 step.

    Swept endpoint hulls are conservative for straight translation. Turning
    curvature between accepted states is a disclosed geometric approximation.
    """

    def __init__(self, model):
        self.model = model
        self.faces = []
        length = model.berth.face_length_ft
        if length > 0:
            self.faces.append(("pier", f"{model.berth.berth_id}:face", 0.0, length, 0.0))
        for rec in model.system.fenders:
            f = rec.model
            self.faces.append(("fender", f.fender_id, f.x_ft-f.length_ft/2, f.x_ft+f.length_ft/2, f.face_y_ft))
        self.lines = [LineString([(lo, y), (hi, y)]) for _, _, lo, hi, y in self.faces]
        self.interval = {"pier": None, "fender": None}
        self.warnings = {}

    def warn(self, code, message, *, severity="AMBER", t=None, element=None):
        key = code, element
        if key not in self.warnings or (t is not None and self.warnings[key].t_s is not None
                                       and t < self.warnings[key].t_s):
            self.warnings[key] = MotionPredictionWarning(code=code, severity=severity, message=message,
                                                         t_s=t, element_id=element)

    def check(self, t, before, after=None):
        hull = Polygon(_footprint(self.model, before))
        if after is not None:
            hull = hull.union(Polygon(_footprint(self.model, after))).convex_hull
        xmin, ymin, xmax, ymax = hull.bounds
        for (kind, identity, lo, hi, face_y), line in zip(self.faces, self.lines):
            distance = hull.distance(line)
            # Positive y is the known water side. A hull behind a finite face
            # cannot become newly clear merely because it passed through it.
            behind = xmin <= hi and xmax >= lo and ymin <= face_y
            if behind:
                clipped = hull.intersection(Polygon([(lo, ymin-1), (hi, ymin-1),
                    (hi, max(face_y, ymax)+1), (lo, max(face_y, ymax)+1)]))
                behind = not clipped.is_empty and clipped.bounds[1] <= face_y+EPS
            distance = 0.0 if behind else distance
            old = self.interval[kind]
            self.interval[kind] = distance if old is None else min(old, distance)
            if distance <= EPS:
                self.warn(f"{kind.upper()}_CONTACT", "Predicted hull reaches or crosses the known "
                    f"{kind} face; geometric evidence is limited by the supplied geometry.",
                    severity="RED", t=t, element=identity)

    def point(self, start, t, state):
        point = MotionPredictionPose(t_s=t, elapsed_s=max(0.0, t-start),
            pose=MotionPose(x_ft=state[0], y_ft=state[1], yaw_deg=math.degrees(state[2])),
            velocity=MotionVelocity(surge_fps=state[3], sway_fps=state[4], yaw_degps=math.degrees(state[5])),
            footprint=[MotionPredictionPoint(x_ft=x, y_ft=y) for x, y in _footprint(self.model, state)],
            pier_clearance_ft=self.interval["pier"], fender_clearance_ft=self.interval["fender"])
        self.interval = {"pier": None, "fender": None}
        return point


def predict_motion(model, request: MotionPredictionRequest, *, session_id: str, run_id: str,
                   sequence: int, scene_id: str, scene_revision: str) -> MotionPredictionResponse:
    """Roll forward an independent clone, with absolute-time what-if commands.

    Budgets are cooperative at bounded completed-work chunks. Incomplete results
    report their actual end time; dense samples never alter the integration grid.
    """
    begun = time.monotonic()
    last_yield = begun
    m = model.clone_for_prediction()
    req = MotionPredictionRequest.model_validate(request.model_dump(mode="json"))
    start = m.t
    source = MotionPredictionSource(session_id=session_id, run_id=run_id, sequence=sequence,
        scene_id=scene_id, scene_revision=scene_revision, t_s=start, input_hash=snapshot_hash(m),
        command_sequence=m.sequence, forcing_revision=m.forcing_revision)
    target = min(start+req.horizon_s, m.duration)
    reasons = []
    hazards = _Hazards(m)
    stop_invalid = False

    def reason(code, message, *, invalid=False):
        nonlocal stop_invalid
        if not any(r.code == code for r in reasons):
            reasons.append(ValidityReason(code=code, message=message))
        stop_invalid |= invalid
        hazards.warn(code, message, severity="RED" if invalid else "AMBER", t=m.t)

    if target < start+req.horizon_s-EPS:
        reason("PREDICTION_SESSION_END", "Prediction is truncated at the session's configured end time.")
    if m.forcing is not None:
        # An observed-state run restarts simulation t=0 while retaining the
        # source forcing phase. Coverage must be expressed in this run's clock.
        coverage_start = m.forcing.start-m.forcing_time_offset_s
        coverage_end = m.forcing.end-m.forcing_time_offset_s
        if start < coverage_start-EPS or start > coverage_end+EPS:
            target = start
            reason("PREDICTION_FORCING_UNCOVERED", "Source time is outside forcing coverage; no future rollout is available.", invalid=True)
        elif target > coverage_end+EPS:
            target = coverage_end
            reason("PREDICTION_FORCING_END", "Prediction stops at forcing coverage; uncovered forcing is never extrapolated.")

    transition_start, event_start = len(m.transitions), len(m.events)
    initial_steps = m.integrator.steps
    for command in req.what_if_commands:
        when = start if command.t_s is None else command.t_s
        if when < start-EPS or when > start+req.horizon_s+EPS:
            raise ValueError("what-if command time must be within the prediction's absolute simulation-time horizon")
        if when > target+EPS:
            raise ValueError("what-if command time is outside the available session/forcing horizon")
        m.schedule(command.model_copy(update={"t_s": when}))
    initial_pending = len(m.pending)
    initial_sequence = m.sequence
    hazards.check(start, m.integrator.state)
    path = [hazards.point(start, start, m.integrator.state)]
    hazards.check(start, m.integrator.state)
    last_t, last_state = start, m.integrator.state
    next_sample = start+req.sample_interval_s

    def observe(t0, s0, t1, s1):
        nonlocal next_sample, last_t, last_state
        previous = s0
        while next_sample <= t1+EPS and next_sample <= target+EPS:
            sample_t = min(next_sample, t1)
            state = s1 if abs(sample_t-t1) <= EPS else m.integrator.sample(sample_t)
            hazards.check(sample_t, previous, state)
            path.append(hazards.point(start, sample_t, state))
            hazards.check(sample_t, state)
            previous = state
            next_sample += req.sample_interval_s
        hazards.check(t1, previous, s1)
        last_t, last_state = t1, s1

    def commands_applied():
        # Queued arrivals already have sequence IDs. Deterministic guidance
        # adds its sequence only when it generates a new actuator order.
        return initial_pending-len(m.pending)+m.sequence-initial_sequence

    def used_work():
        return m.integrator.steps-initial_steps+commands_applied()

    try:
        while m.t < target-EPS or m.commands_due():
            if used_work() >= MAX_WORK:
                reason("PREDICTION_WORK_LIMIT", "Prediction stopped at its integration/command budget; the remaining horizon is unknown.")
                break
            now = time.monotonic()
            if now-begun >= MAX_RUNTIME_S:
                reason("PREDICTION_RUNTIME_LIMIT", "Prediction stopped at its interactive runtime budget; the remaining horizon is unknown.")
                break
            if len(m.transitions)-transition_start >= MAX_TRANSITIONS or len(m.events)-event_start >= MAX_EVENTS:
                reason("PREDICTION_EVENT_LIMIT", "Prediction stopped at its event output budget; the remaining horizon is unknown.")
                break
            m.advance(target, observe=observe, max_work=min(WORK_CHUNK, MAX_WORK-used_work()))
            if now-last_yield >= YIELD_INTERVAL_S:
                time.sleep(YIELD_SLEEP_S)
                last_yield = now
    except (ValueError, OverflowError) as exc:
        reason("PREDICTION_DYNAMICS_STOPPED", f"The berthing integrator stopped: {str(exc)[:500]}", invalid=True)

    # A mechanics failure can happen after accepting a state but before the
    # observer. Preserve that actual endpoint and its hazard evidence.
    if m.t > last_t+EPS:
        hazards.check(m.t, last_state, m.integrator.state)
    if m.t > path[-1].t_s+EPS:
        path.append(hazards.point(start, m.t, m.integrator.state))

    transitions = m.transitions[transition_start:]
    events = m.events[event_start:]
    if len(transitions) > MAX_TRANSITIONS or len(events) > MAX_EVENTS:
        reason("PREDICTION_EVENTS_TRUNCATED", "Additional events exceeded the output limit; this prediction is incomplete.")
        transitions, events = transitions[:MAX_TRANSITIONS], events[:MAX_EVENTS]
    for transition in transitions:
        if transition.kind in ("line_taut", "line_slack", "secured", "released", "tensioned"):
            hazards.warn("PREDICTED_"+transition.kind.upper(), f"Predicted line transition: {transition.kind}.",
                         severity="INFO", t=transition.t_s, element=transition.element_id)
        elif transition.kind == "contact_start":
            hazards.warn("FENDER_CONTACT", "The berthing integrator predicts fender contact.",
                         severity="RED", t=transition.t_s, element=transition.element_id)
    for event in events:
        if event.kind == "line_overload":
            hazards.warn("LINE_MBS_EXCEEDED", event.detail, severity="RED", t=event.t_s)

    # Coverage may have become invalid before this call (e.g. an externally
    # stopped source). Never let final metadata evaluation erase a bounded
    # partial result or extrapolate forcing just to render its validity.
    try:
        base_validity = m.validity()
    except (ValueError, OverflowError) as exc:
        reason("PREDICTION_SOURCE_INVALID", f"The source model cannot evaluate its final state: {str(exc)[:500]}", invalid=True)
        base_validity = Validity(state="invalid", reasons=list(m.reasons) or reasons)
    checked = sorted({face[0] for face in hazards.faces})
    unchecked = [name for name in ("pier", "fender", "coastline", "other_vessels", "bathymetry") if name not in checked]
    fixed_reasons = [
        ValidityReason(code="BERTHING_PREDICTION_SYNTHETIC", message="Exact rollout of the session's synthetic, unqualified berthing model; demonstrator decision support, never navigational guidance."),
        ValidityReason(code="PREDICTION_GEOMETRY_LIMITED", message="Hull footprint is the LOA × beam parallel-body envelope. Finite pier/fender faces use swept endpoint hulls at accepted RK4 steps; between-step turning curvature and pier impact dynamics are not qualified."),
        ValidityReason(code="HAZARD_COVERAGE_INCOMPLETE", message=f"Unchecked hazard layers: {', '.join(unchecked)}. Full bathymetric coverage is unavailable. Absence of a contact warning is not an all-clear."),
        ValidityReason(code="UNCERTAINTY_UNAVAILABLE", message="No calibrated trajectory uncertainty is available. Deterministic hull footprints are not a safe corridor."),
    ]
    all_reasons = {(r.code, r.message, tuple(r.affected_components)): r
                   for r in [*base_validity.reasons, *fixed_reasons, *reasons]}
    validity = Validity(state="invalid" if stop_invalid or base_validity.state == "invalid" else "limited",
                        reasons=list(all_reasons.values()))
    for r in fixed_reasons[2:]:
        hazards.warn(r.code, r.message)
    for r in base_validity.reasons:
        if r.code in ("UNDER_KEEL_CONTACT_POSSIBLE", "LINE_MBS_EXCEEDED", "FORCING_UNCOVERED"):
            hazards.warn(r.code, r.message, severity="RED")
    warnings = list(hazards.warnings.values())
    if len(warnings) > MAX_WARNINGS:
        warnings = warnings[:MAX_WARNINGS-1] + [MotionPredictionWarning(code="PREDICTION_WARNINGS_TRUNCATED",
            severity="AMBER", message="Additional warnings exceeded the output limit; hazard coverage is incomplete.")]
    complete = math.isclose(m.t-start, req.horizon_s, abs_tol=EPS) and not reasons
    work = MotionPredictionWork(integration_steps=m.integrator.steps-initial_steps,
        commands_applied=commands_applied(), work_limit=MAX_WORK,
        integration_dt_s=m.dt, runtime_limit_s=MAX_RUNTIME_S)
    result = MotionPredictionResponse(prediction_id="pending", source=source,
        requested_horizon_s=req.horizon_s, horizon_s=max(0.0, m.t-start), complete=complete, path=path,
        transitions=transitions, events=events, warnings=warnings,
        hazards_checked=checked,
        hazards_unchecked=unchecked, validity=validity,
        status="RED" if validity.state == "invalid" or any(w.severity == "RED" for w in hazards.warnings.values()) else "AMBER",
        work=work)
    result.prediction_id = "mpred_"+_digest({"request": req, "result": result})[:24]
    return result
