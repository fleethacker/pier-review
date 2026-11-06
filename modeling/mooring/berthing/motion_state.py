"""Pure validation/conversion of imported ship or tug state into a paused run.

No feed is acquired, session is looked up, clock is read or model is mutated here.
The authorized caller holds its session lock and supplies an injected clock and
per-entity history, then applies the returned state atomically. Store the snapshot
on the model for prediction/recording provenance, use its new run_id, reset prior
integration/energy bookkeeping and invalidate old predictions. Preserving nonzero
simulation time requires a paused lifecycle, not a reset event (reset needs t=0).
"""

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from mooring.core.schemas.dynamics import ShipState
from mooring.core.schemas.motion_state import MotionStateInput, MotionStatePolicy, MotionStateSnapshot, MotionStateVector
from mooring.core.units import KT_TO_FPS


class MotionStateRejected(ValueError):
    """Stable code for a request rejected before caller-owned state changes."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _reject(code, message):
    raise MotionStateRejected(code, message)


def _aware(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _reject("STATE_CLOCK_INVALID", f"{name} must be an aware datetime")
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def prepare_state_reseed(
    observation: MotionStateInput,
    *,
    session_id: str,
    run_id: str,
    simulation_time_s: float,
    expected_entity: Literal["ship", "tug"],
    expected_entity_id: str,
    expected_berth_id: str,
    face_bearing_true_deg: float,
    side_to: Literal["port", "starboard"],
    paused: bool,
    previous_by_entity: Mapping[tuple[str, str], MotionStateSnapshot],
    now_utc: datetime,
    policy: MotionStatePolicy | None = None,
) -> MotionStateSnapshot:
    """Prepare an immutable state application using caller-injected clock/history.

    History is independent per (entity kind, entity id), not per source label:
    changing sources cannot bypass replay rejection. Recorded data obeys the same
    age policy; explicit replay callers may inject their replay clock. Age never
    causes velocity extrapolation and measured acceleration never becomes force.
    """
    req = MotionStateInput.model_validate(observation.model_dump(mode="json"))
    limits = MotionStatePolicy.model_validate((policy or MotionStatePolicy()).model_dump())
    now = _aware(now_utc, "now_utc").astimezone(UTC)
    if paused is not True:
        _reject("STATE_REQUIRES_PAUSED", "Pause the session before adopting an imported state.")
    if req.entity != expected_entity or req.entity_id != expected_entity_id:
        _reject("STATE_ENTITY_MISMATCH", "Imported entity must match the caller-owned session entity.")
    if req.berth_id != expected_berth_id:
        _reject("STATE_FRAME_MISMATCH", "Imported berth frame does not match the session berth.")
    if side_to not in ("port", "starboard"):
        _reject("STATE_CONTEXT_INVALID", "Session side_to must be explicit port or starboard.")
    if (type(face_bearing_true_deg) not in (int, float) or not math.isfinite(face_bearing_true_deg)
            or not 0 <= face_bearing_true_deg < 360):
        _reject("STATE_CONTEXT_INVALID", "Session berth face bearing must be finite and in [0, 360) degrees true.")
    if (type(simulation_time_s) not in (int, float) or not math.isfinite(simulation_time_s)
            or not 0 <= simulation_time_s <= 7200):
        _reject("STATE_CONTEXT_INVALID", "Session simulation time must be finite and inside its bounded run.")
    if any(not isinstance(value, str) or not value.strip() for value in (session_id, run_id)):
        _reject("STATE_CONTEXT_INVALID", "Session and run identities are required.")

    age = (now-req.observed_at_utc).total_seconds()
    if age < -limits.future_tolerance_s:
        _reject("STATE_FUTURE", "Observation is ahead of the injected clock beyond its explicit tolerance.")
    if age > limits.max_age_s:
        _reject("STATE_STALE", "Observation exceeds the configured maximum age; it was not extrapolated.")
    if req.quality == "invalid":
        _reject("STATE_QUALITY_INVALID", "An input marked invalid cannot seed the model.")
    if req.quality == "suspect" and not limits.allow_suspect:
        _reject("STATE_QUALITY_SUSPECT", "Suspect quality is not accepted by the configured input policy.")

    previous = previous_by_entity.get((req.entity, req.entity_id))
    if previous is not None:
        if (previous.session_id != session_id or previous.input.entity != req.entity
                or previous.input.entity_id != req.entity_id or previous.input.berth_id != req.berth_id):
            _reject("STATE_HISTORY_MISMATCH", "Caller history must belong to this session, entity and berth frame.")
        if req.sequence == previous.input.sequence:
            _reject("STATE_DUPLICATE", "This entity sequence has already been accepted.")
        if req.sequence < previous.input.sequence:
            _reject("STATE_OUT_OF_ORDER", "Entity sequence must increase; old updates cannot replace newer state.")
        if req.observed_at_utc <= previous.input.observed_at_utc:
            _reject("STATE_TIME_NOT_INCREASING", "Observation timestamps must increase independently of arrival order.")

    state = MotionStateVector(x_ft=req.x_ft, y_ft=req.y_ft,
        yaw_rad=math.radians((face_bearing_true_deg-req.heading_true_deg+180) % 360-180),
        surge_fps=req.surge_fps, sway_fps=req.sway_fps, yaw_radps=math.radians(req.yaw_degps))
    limitations = [
        "Imported state does not establish a hardware connection or verify the claimed source.",
        "Supplied position and velocity are adopted without extrapolation to the acceptance clock.",
        "Measured acceleration is evidence only; forces and subsequent acceleration remain model-generated.",
        "Reseeding does not qualify synthetic demonstration dynamics or establish navigational guidance.",
    ]
    if req.source == "synthetic":
        limitations.append("Explicitly synthetic state, not an observation of a real vessel.")
    elif req.source == "recorded":
        limitations.append("Supplied recorded state, not a live hardware stream.")
    if req.quality in (None, "unknown"):
        limitations.append("Observation quality is unknown; a missing label does not mean good quality.")
    elif req.quality == "suspect":
        limitations.append("Suspect quality was accepted only under the caller's explicit policy.")
    if age < 0:
        limitations.append("Observation leads the clock within the caller's explicit clock-skew allowance.")
    raw_input = req.model_dump(mode="json")
    material = dict(input=raw_input, session_id=session_id, previous_run_id=run_id,
        simulation_time_s=simulation_time_s, accepted_at_utc=now.isoformat(), state=state.model_dump(),
        policy=limits.model_dump(), version="motion-state-v1")
    digest = _digest(material)
    return MotionStateSnapshot(snapshot_id="mstate_"+digest[:24], input_hash=_digest(raw_input),
        session_id=session_id, previous_run_id=run_id, run_id="run_state_"+digest[:24],
        simulation_time_s=simulation_time_s, accepted_at_utc=now, age_s=age,
        input=req, state=state, policy=limits, limitations=tuple(limitations))


def to_legacy_ship_state(snapshot: MotionStateSnapshot, *, side_to: Literal["port", "starboard"]) -> ShipState:
    """Compatibility only: legacy sway means toward pier, RM0 sway means port."""
    if snapshot.input.entity != "ship":
        _reject("STATE_ENTITY_MISMATCH", "Legacy ShipState projection is only defined for the ship entity.")
    if side_to not in ("port", "starboard"):
        _reject("STATE_CONTEXT_INVALID", "Legacy projection requires an explicit side_to.")
    state = snapshot.state
    return ShipState(x_ft=state.x_ft, y_ft=state.y_ft, heading_true_deg=snapshot.input.heading_true_deg,
        u_kt=state.surge_fps/KT_TO_FPS,
        v_kt=(-state.sway_fps if side_to == "starboard" else state.sway_fps)/KT_TO_FPS,
        r_degps=math.degrees(state.yaw_radps))
