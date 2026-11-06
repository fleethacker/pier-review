"""Phases 1c and 2, berthing: assist tugs, berthing windows, line sequence, berthing simulator."""

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query

from mooring import refdata
from mooring.core import access
from mooring.core.envelopes import new_id
from mooring.core.schemas import (
    BerthingSimRequest,
    BerthingTugRequest,
    BerthingWindowRequest,
    BerthingWindowsResponse,
    JobAccepted,
    SequenceRequest,
    SequenceResponse,
    SequenceValidateRequest,
    SimRecording,
    SimRecordingList,
    SimScene,
    SimSeries,
    SimSessionCreate,
    SimSessionCreated,
    TugPlanResponse,
)
from mooring.examples import ex

from mooring.core.schemas.sequence_search import SequenceSearchRequest, SequenceSearchResult
from ..backend import berthing_sim, berthing_tugs, sequence as sequence_impl
from ..state import API_PREFIX, JOBS, SESSIONS

router = APIRouter()


# ---- M6 Assist tugs and windows ----

@router.post("/tugs/berthing-plan", response_model=TugPlanResponse, tags=["M6 Tugs"],
             summary="Tugs needed to land and hold the ship before lines are fast")
def berthing_plan(req: Annotated[BerthingTugRequest, Body(openapi_examples=ex("tugs_berthing_plan"))]):
    return berthing_tugs.berthing_plan(req)


@router.post("/windows/berthing", response_model=BerthingWindowsResponse, tags=["M6 Tugs"],
             summary="Time windows with low current and gusts for berthing")
def berthing_windows(req: Annotated[BerthingWindowRequest, Body(openapi_examples=ex("windows_berthing"))]):
    return berthing_tugs.windows(req)


# ---- M7 Line sequence ----

@router.post("/mooring/sequence", response_model=SequenceResponse, tags=["M7 Planning"],
             summary="Ordered line-handling steps for a configuration")
def sequence(req: Annotated[SequenceRequest, Body(openapi_examples=ex("mooring_sequence"))]):
    return sequence_impl.sequence(req)


@router.post("/mooring/sequence/validate", response_model=SequenceResponse, tags=["M7 Planning"],
             summary="Check a proposed line-handling sequence: dependencies, crews, tug provenance and intermediate states")
def sequence_validate(req: SequenceValidateRequest):
    return sequence_impl.validate_sequence(req)


@router.post("/mooring/sequence/search", response_model=SequenceSearchResult, tags=["M7 Planning"],
             summary="S8: bounded search over line orders with intermediate static checks (draft, unreviewed)")
def sequence_search(req: SequenceSearchRequest):
    try:
        return sequence_impl.propose_sequences(req)
    except (refdata.NotFound, refdata.InvalidReference) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


# ---- M11 Berthing simulator ----

@router.post("/berthing/simulate", response_model=JobAccepted, status_code=202, tags=["M11 Berthing simulator"],
             summary="Batch berthing simulation (job; result is a BerthingSimResponse)")
def simulate(req: Annotated[BerthingSimRequest, Body(openapi_examples=ex("berthing_simulate"))]):
    # Resolve ownership and validate before queuing; the worker inherits identity.
    from mooring import scenarios
    scenarios.get(req.scenario_id)
    jid = new_id("job")
    return JOBS.submit_task("berthing.simulate", lambda ctx: berthing_sim.simulate_berthing(req, jid, API_PREFIX, ctx), job_id=jid)


@router.get("/berthing/simulations/{job_id}/series", response_model=SimSeries, tags=["M11 Berthing simulator"],
            summary="Persisted frames and validity from a completed batch run")
def series(job_id: str):
    job = JOBS.get(job_id)
    if job is None or job.state != "succeeded" or job_id not in berthing_sim.SERIES:
        raise refdata.NotFound(f"No simulation series for job '{job_id}'")
    return berthing_sim.SERIES[job_id]


@router.post("/berthing/sessions", response_model=SimSessionCreated, status_code=201, tags=["M11 Berthing simulator"],
             summary="Start an interactive session; drive it over WS /ws/sim/{session_id}")
def create_session(req: Annotated[SimSessionCreate, Body(openapi_examples=ex("berthing_session"))]):
    sid = new_id("sim")
    from ..sim_sessions import create
    try:
        session = create(SESSIONS, sid, berthing_sim.initial_model(req.scenario_id, req.initial_state,
                                                      dt=req.dt_s or 0.1, duration=req.duration_s or 900,
                                                      forcing=req.forcing, controls=req.controls),
                         record_interval_s=req.record_interval_s or 1.0)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    base = f"{API_PREFIX}/berthing/sessions/{sid}"
    return SimSessionCreated(session_id=sid, ws_url=f"/ws/sim/{sid}", validity=session.model.validity(),
                             scene_url=f"{base}/scene", protocol="rm0-v1", recording_url=f"{base}/recording",
                             forcing_revision=session.model.forcing_revision,
                             forcing_synthetic=session.model.forcing.synthetic if session.model.forcing else None)


def _owned_session(session_id):
    from ..sim_sessions import Session
    session = SESSIONS.get(session_id)
    if not access.allowed("session", session_id) or not (session is None or isinstance(session, Session)):
        raise refdata.NotFound(f"No simulation session '{session_id}'")
    return session


@router.get("/berthing/sessions/{session_id}/scene", response_model=SimScene, tags=["M11 Berthing simulator"],
            summary="Static rm0-v1 scene (berth, hull, fittings, fenders) for an interactive session")
def session_scene(session_id: str):
    from ..sim_sessions import SCENES
    session = _owned_session(session_id)
    if session is not None and session.rich:
        return session.scene
    try:
        return SCENES[session_id]
    except KeyError:
        raise refdata.NotFound(f"No simulation session '{session_id}'")


@router.get("/berthing/recordings", response_model=SimRecordingList, tags=["M11 Berthing simulator"],
            summary="Owner-scoped saved recordings, including expired sessions; stable session-ID order")
def recordings(limit: int = Query(default=20, ge=1, le=100),
               after_session_id: str = Query(default="", max_length=256)):
    from ..sim_sessions import list_recordings
    items, cursor = list_recordings(limit, after_session_id)
    return SimRecordingList(recordings=items, next_cursor=cursor)


@router.get("/berthing/sessions/{session_id}/recording", response_model=SimRecording, tags=["M11 Berthing simulator"],
            summary="Bounded recording of an interactive session: live copy, else the persisted one")
def session_recording(session_id: str):
    # Frames were validated when produced; serve the stored JSON instead of re-validating up to 10,000 frames.
    from fastapi.responses import Response
    from ..sim_sessions import load_recording_json
    session = _owned_session(session_id)
    try:
        raw = session.recording_json() if session is not None and session.rich else load_recording_json(session_id)
    except (KeyError, ValueError):
        raise refdata.NotFound(f"No recording for session '{session_id}'") from None
    return Response(content=raw, media_type="application/json")
