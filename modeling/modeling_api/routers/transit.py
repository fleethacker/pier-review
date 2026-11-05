"""S6 port transit simulation: own thrust or tug-assisted, several vessels. Implementation: mooring.transit."""

from fastapi import APIRouter, HTTPException

from mooring import refdata
from mooring.core.envelopes import new_id
from mooring.core.schemas import (
    JobAccepted,
    TransitPreset,
    TransitRequest,
    TransitSeries,
)
from mooring.transit import presets as transit_presets
from mooring.transit import simulator as transit_sim

from ..state import API_PREFIX, JOBS

router = APIRouter(tags=["S6 Port transit"])


@router.post("/transit/simulate", response_model=JobAccepted, status_code=202,
             summary="Simulate vessels entering or leaving port (job; result is a TransitResponse)")
def simulate(req: TransitRequest):
    try:
        transit_sim.prepare(req)  # fail fast (unknown class/tug, no speed basis) before queuing
    except transit_sim.RequestInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    jid = new_id("job")
    return JOBS.submit_task("transit.simulate", lambda ctx: transit_sim.simulate_transit(req, jid, API_PREFIX, ctx), job_id=jid)


@router.get("/transit/simulations/{job_id}/series", response_model=TransitSeries,
            summary="Sampled frames for every vessel from a completed transit run")
def series(job_id: str):
    job = JOBS.get(job_id)
    if job is None or job.state != "succeeded" or job_id not in transit_sim.SERIES:
        raise refdata.NotFound(f"No transit series for job '{job_id}'")
    return transit_sim.SERIES[job_id]


@router.get("/transit/presets", response_model=list[TransitPreset],
            summary="Ready-made inbound/outbound transit requests (labeled demonstration routes)")
def presets():
    return transit_presets.presets()
