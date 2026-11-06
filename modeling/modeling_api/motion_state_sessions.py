"""Atomic, paused adoption of explicitly supplied state; no hardware connection."""
from mooring.berthing.motion_state import prepare_state_reseed
from mooring.core.envelopes import utcnow
from mooring.core.schemas.motion_state import MotionStateInput
from mooring.data_simulation.shoreline import ShorelineIntersection, validate_model_state


def adopt_state(session, observation: MotionStateInput, *, now_utc=None):
    """Start a fresh paused run, preserving the prior run in its recording.

    Wall-clock freshness and simulation time are separate. No extrapolation is
    applied, no pending commands survive, and measured acceleration is evidence
    only. Ordinary Reset still restores the original authored configuration.
    """
    from mooring.berthing.motion_state import MotionStateRejected
    with session.lock:
        if getattr(session, "released", False):
            raise MotionStateRejected("STATE_SESSION_RELEASED", "The session has been released.")
        model = session.model
        if observation.entity == "ship":
            expected_id = model.ship.class_id
            tug_id = None
        else:
            fleet = model.tug_dynamics
            if fleet is None or observation.entity_id not in fleet.configs:
                raise MotionStateRejected("STATE_ENTITY_MISMATCH", "Select an independent tug belonging to this session.")
            expected_id = tug_id = observation.entity_id
        history = getattr(session, "state_input_history", {})
        snapshot = prepare_state_reseed(observation, session_id=session.session_id, run_id=session.run_id,
            simulation_time_s=0, expected_entity=observation.entity, expected_entity_id=expected_id,
            expected_berth_id=model.berth.berth_id, face_bearing_true_deg=model.berth.face_bearing_true_deg,
            side_to=model.sc.side_to, paused=session.paused, previous_by_entity=history,
            now_utc=now_utc or utcnow())
        # Build the complete replacement before any session mutation. The model
        # rebuilds energy/dense history and preserves current actuator responses.
        replacement = model.reseeded(snapshot.as_integrator_state(), tug_id=tug_id)
        try:
            validate_model_state(replacement)
        except ShorelineIntersection as exc:
            raise MotionStateRejected("STATE_SHORELINE_INTERSECTION", str(exc)) from None
        evidence = {(s.input.entity, s.input.entity_id): s for s in getattr(model, "state_inputs", [])}
        evidence[(observation.entity, observation.entity_id)] = snapshot
        replacement.state_inputs = list(evidence.values())
        session.record_now()
        session.model = replacement
        session.run_id = snapshot.run_id
        session.state_input_history = {**history, (observation.entity, observation.entity_id): snapshot}
        session.paused = True
        session.error = None
        session.rec_last_t = None
        session.reanchor()
        session.emit("reset", "New paused run seeded from supplied state; original scenario remains available through Reset.")
        session.publish()
        session.record_now()
        session.persist(force=True)
        session.notify()
        return snapshot
