"""Jobs, health and version for the agents service."""

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from mooring import refdata
from mooring.core.schemas import Health, JobStatus, VersionInfo

from ...backend import BACKENDS, overall_backend
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
def job_events(job_id: str, last_event_id: int | None = Header(default=None, ge=0)):
    if JOBS.get(job_id) is None:
        raise refdata.NotFound(f"Job '{job_id}' not found")
    return StreamingResponse(JOBS.stream(job_id, last_event_id), media_type="text/event-stream")


@router.delete("/jobs/{job_id}", response_model=JobStatus)
def cancel_job(job_id: str):
    if JOBS.cancel(job_id) is None:
        raise refdata.NotFound(f"Job '{job_id}' not found")
    return JOBS.status(job_id)


@router.get("/health", response_model=Health)
def health():
    return Health(status="ok", backend=overall_backend())


@router.get("/version", response_model=VersionInfo)
def version():
    return VersionInfo(api_version="1.0.0", modules=BACKENDS)
