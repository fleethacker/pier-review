"""Jobs, health and version for the agents service."""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from mooring import refdata
from mooring.core.schemas import Health, JobStatus, VersionInfo

from ...backend import BACKENDS
from ..state import JOBS

router = APIRouter(tags=["System"])


@router.get("/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str):
    st = JOBS.status(job_id)
    if st is None:
        raise refdata.NotFound(f"Job '{job_id}' not found")
    return st


@router.get("/jobs/{job_id}/events", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}}})
def job_events(job_id: str):
    if JOBS.get(job_id) is None:
        raise refdata.NotFound(f"Job '{job_id}' not found")
    return StreamingResponse(JOBS.stream(job_id), media_type="text/event-stream")


@router.get("/health", response_model=Health)
def health():
    return Health(status="ok", backend="mock")


@router.get("/version", response_model=VersionInfo)
def version():
    return VersionInfo(api_version="1.0.0", modules=BACKENDS)
