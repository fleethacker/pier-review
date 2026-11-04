"""Phases 1c and 2, berthing: assist tugs, berthing windows, line sequence, berthing simulator."""

from typing import Annotated

from fastapi import APIRouter, Body

from mooring import refdata
from mooring.core.envelopes import new_id
from mooring.core.schemas import (
    BerthingSimRequest,
    BerthingTugRequest,
    BerthingWindowRequest,
    BerthingWindowsResponse,
    JobAccepted,
    SequenceRequest,
    SequenceResponse,
    SimSeries,
    SimSessionCreate,
    SimSessionCreated,
    TugPlanResponse,
)
from mooring.examples import ex

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


# ---- M11 Berthing simulator ----

@router.post("/berthing/simulate", response_model=JobAccepted, status_code=202, tags=["M11 Berthing simulator"],
             summary="Batch berthing simulation (job; result is a BerthingSimResponse)")
def simulate(req: Annotated[BerthingSimRequest, Body(openapi_examples=ex("berthing_simulate"))]):
    jid = new_id("job")
    return JOBS.submit_task("berthing.simulate", lambda ctx: berthing_sim.simulate_berthing(req, jid, API_PREFIX), job_id=jid)


@router.get("/berthing/simulations/{job_id}/series", response_model=SimSeries, tags=["M11 Berthing simulator"],
            summary="Frames from a batch run (1 Hz)")
def series(job_id: str):
    if job_id not in berthing_sim.SERIES:
        raise refdata.NotFound(f"No simulation series for job '{job_id}'")
    return berthing_sim.SERIES[job_id]


@router.post("/berthing/sessions", response_model=SimSessionCreated, status_code=201, tags=["M11 Berthing simulator"],
             summary="Start an interactive session; drive it over WS /ws/sim/{session_id}")
def create_session(req: Annotated[SimSessionCreate, Body(openapi_examples=ex("berthing_session"))]):
    sid = new_id("sim")
    SESSIONS[sid] = berthing_sim.initial_model(req.scenario_id, req.initial_state)
    return SimSessionCreated(session_id=sid, ws_url=f"/ws/sim/{sid}")
