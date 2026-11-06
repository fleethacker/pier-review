"""Motion workspace: private scenarios, paused sessions and immutable predictions."""
import threading
from weakref import WeakKeyDictionary

from fastapi import APIRouter, HTTPException, Response
from mooring import environment, refdata
from mooring.berthing import motion_workspace as workspace
from mooring.core.envelopes import new_id
from mooring.core.schemas import EnvironmentSnapshot, SimSessionCreated
from mooring.core.schemas.motion_prediction import MotionPredictionRequest, MotionPredictionResponse
from mooring.core.schemas.motion_state import MotionStateInput, MotionStateSnapshot
from mooring.core.schemas.motion_workspace import (
    MotionWorkspaceCatalog, MotionWorkspaceScenario, MotionWorkspaceSessionCreated,
    MotionWorkspaceSessionRequest, MotionWorkspaceSpec,
)
from ..sim_sessions import create
from ..state import API_PREFIX, SESSIONS
from .berthing import _owned_session
from .env import guarded

router = APIRouter(tags=["Motion workspace"])
_PREDICTIONS = threading.BoundedSemaphore(2)
_PREDICTION_LOCK = threading.Lock()
_SESSION_PREDICTIONS = WeakKeyDictionary()


@router.get("/motion/catalog", response_model=MotionWorkspaceCatalog)
def catalog():
    return workspace.catalog()


@router.post("/motion/scenarios", response_model=MotionWorkspaceScenario, status_code=201)
def create_scenario(req: MotionWorkspaceSpec):
    try:
        return workspace.create_scenario(req)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/motion/configuration", response_model=MotionWorkspaceSpec)
def resolve_configuration(req: MotionWorkspaceSpec):
    """Resolve training defaults for authoring; creates no resource and acquires no live data."""
    try:
        return workspace.resolve_configuration(req)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/motion/scenarios", response_model=list[MotionWorkspaceScenario])
def list_scenarios():
    return list(workspace.SCENARIOS.values())


@router.get("/motion/scenarios/{scenario_id}", response_model=MotionWorkspaceScenario)
def get_scenario(scenario_id: str):
    return workspace.get_scenario(scenario_id)


@router.get("/motion/environment", response_model=EnvironmentSnapshot)
def current_environment(berth_id: str):
    refdata.berth(berth_id)
    return guarded(environment.live_snapshot, berth_id)


def require_session(session_id):
    session = _owned_session(session_id)
    if session is None:
        raise refdata.NotFound("Motion session not found")
    return session


@router.post("/motion/sessions", response_model=MotionWorkspaceSessionCreated, status_code=201)
def create_session(req: MotionWorkspaceSessionRequest):
    row = workspace.get_scenario(req.motion_scenario_id)
    try:
        model = guarded(workspace.build_model, row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    sid = new_id("sim")
    session = create(SESSIONS, sid, model, record_interval_s=1)
    with session.lock:
        session.paused = True
        session.reanchor()
        session.emit("paused", "Ready. Start explicitly to advance simulation time.")
        session.publish()
    base = f"{API_PREFIX}/berthing/sessions/{sid}"
    created = SimSessionCreated(session_id=sid, ws_url=f"/ws/sim/{sid}", validity=model.validity(),
        scene_url=f"{base}/scene", protocol="rm0-v1", recording_url=f"{base}/recording",
        forcing_revision=model.forcing_revision,
        forcing_synthetic=(row.configuration.environment_mode == "synthetic" or
                           bool(model.forcing and model.forcing.synthetic)))
    route = workspace.norfolk_route(model.berth) if row.configuration.route_id else None
    return MotionWorkspaceSessionCreated(session=created, scenario=row, ship=model.ship, berth=model.berth,
        controls=row.configuration.controls, route=route, environment=model.env)


@router.delete("/motion/sessions/{session_id}", status_code=204)
def release_session(session_id: str):
    session = require_session(session_id)
    with session.lock:
        if session.connection is not None:
            raise HTTPException(409, "Close the session socket before releasing its slot")
        session.persist(force=True)
        if session.rec_dirty:
            raise HTTPException(503, "Recording is not yet durable; session retained for retry")
        if SESSIONS.get(session_id) is session:
            session.released = True
            del SESSIONS[session_id]
    return Response(status_code=204)


@router.post("/motion/sessions/{session_id}/state", response_model=MotionStateSnapshot)
def import_state(session_id: str, req: MotionStateInput):
    from ..motion_state_sessions import adopt_state
    from mooring.berthing.motion_state import MotionStateRejected
    session = require_session(session_id)
    try:
        return adopt_state(session, req)
    except MotionStateRejected as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc)}) from None
    except ValueError as exc:
        raise HTTPException(422, {"code": "STATE_RESEED_INVALID", "message": str(exc)}) from None


@router.post("/motion/sessions/{session_id}/prediction", response_model=MotionPredictionResponse)
def predict(session_id: str, req: MotionPredictionRequest):
    from mooring.berthing.motion_prediction import predict_motion
    session = require_session(session_id)
    with _PREDICTION_LOCK:
        lock = _SESSION_PREDICTIONS.setdefault(session, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(429, "A prediction is already running for this session", headers={"Retry-After": "1"})
    acquired = False
    try:
        acquired = _PREDICTIONS.acquire(blocking=False)
        if not acquired:
            raise HTTPException(429, "Prediction workers are busy", headers={"Retry-After": "1"})
        with session.lock:
            if getattr(session, "released", False):
                raise HTTPException(404, "Motion session has been released")
            snapshot = session.snapshot_model()
            identity = dict(session_id=session_id, run_id=session.run_id, sequence=session.sequence,
                            scene_id=session.scene.scene_id, scene_revision=session.scene.revision)
        try:
            return predict_motion(snapshot, req, **identity)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    finally:
        if acquired:
            _PREDICTIONS.release()
        lock.release()
