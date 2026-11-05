"""S6 port transit simulation: own thrust or tug-assisted, several vessels. Implementation: mooring.transit."""

from fastapi import APIRouter, HTTPException

from mooring.core.schemas import JobAccepted, TransitPreset, TransitRequest, TransitSeries

router = APIRouter(tags=["S6 Port transit"])


def _todo():
    raise HTTPException(status_code=501, detail="S6 not implemented yet")


@router.post("/transit/simulate", response_model=JobAccepted, status_code=202,
             summary="Simulate vessels entering or leaving port (job; result is a TransitResponse)")
def simulate(req: TransitRequest):
    _todo()


@router.get("/transit/simulations/{job_id}/series", response_model=TransitSeries,
            summary="Sampled frames for every vessel from a completed transit run")
def series(job_id: str):
    _todo()


@router.get("/transit/presets", response_model=list[TransitPreset],
            summary="Ready-made inbound/outbound transit requests (labeled demonstration routes)")
def presets():
    _todo()
