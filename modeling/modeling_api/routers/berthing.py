from typing import Annotated

from fastapi import APIRouter, Body

from mooring import refdata
from mooring.core.envelopes import new_id
from mooring.core.schemas import BerthingSimRequest, JobAccepted, SimSeries, SimSessionCreate, SimSessionCreated
from mooring.mock.examples import ex

from ..backend import dynamics
from ..state import API_PREFIX, JOBS, SESSIONS

router = APIRouter(tags=["M11 Berthing simulator"])


@router.post("/berthing/simulate", response_model=JobAccepted, status_code=202,
             summary="Batch berthing simulation (job; result is a BerthingSimResponse)")
def simulate(req: Annotated[BerthingSimRequest, Body(openapi_examples=ex("berthing_simulate"))]):
    jid = new_id("job")
    return JOBS.submit("berthing.simulate", dynamics.simulate_berthing(req, jid, API_PREFIX), job_id=jid)


@router.get("/berthing/simulations/{job_id}/series", response_model=SimSeries, summary="Frames from a batch run (1 Hz)")
def series(job_id: str):
    if job_id not in dynamics.SERIES:
        raise refdata.NotFound(f"No simulation series for job '{job_id}'")
    return dynamics.SERIES[job_id]


@router.post("/berthing/sessions", response_model=SimSessionCreated, status_code=201,
             summary="Start an interactive session; drive it over WS /ws/sim/{session_id}")
def create_session(req: Annotated[SimSessionCreate, Body(openapi_examples=ex("berthing_session"))]):
    sid = new_id("sim")
    SESSIONS[sid] = dynamics.initial_model(req.scenario_id, req.initial_state)
    return SimSessionCreated(session_id=sid, ws_url=f"/ws/sim/{sid}")
