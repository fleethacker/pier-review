from typing import Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from mooring import refdata
from mooring.core.envelopes import RESULTS
from mooring.core.schemas import Health, JobStatus, VersionInfo

from ..backend import BACKENDS, overall_backend
from ..state import JOBS

router = APIRouter(tags=["System"])


@router.get("/jobs/{job_id}", response_model=JobStatus, summary="Job status; `result` holds the envelope when done")
def job_status(job_id: str):
    st = JOBS.status(job_id)
    if st is None:
        raise refdata.NotFound(f"Job '{job_id}' not found")
    return st


@router.get("/jobs/{job_id}/events", summary="Server-Sent Events: `progress` and `done` (JobProgressEvent, JobDoneEvent)",
            response_class=StreamingResponse, responses={200: {"content": {"text/event-stream": {}}}})
def job_events(job_id: str, last_event_id: Annotated[str | None, Header()] = None):
    if JOBS.get(job_id) is None:
        raise refdata.NotFound(f"Job '{job_id}' not found")
    resume = int(last_event_id) if last_event_id and last_event_id.isdigit() else None
    return StreamingResponse(JOBS.stream(job_id, resume), media_type="text/event-stream")


@router.delete("/jobs/{job_id}", response_model=JobStatus, summary="Cancel a queued or running job")
def job_cancel(job_id: str):
    if JOBS.cancel(job_id) is None:
        raise refdata.NotFound(f"Job '{job_id}' not found")
    return JOBS.status(job_id)


@router.get("/results/{result_id}", response_model=dict[str, Any],
            summary="Any stored result envelope by id (for citations and audit)")
def get_result(result_id: str):
    if result_id not in RESULTS:
        raise refdata.NotFound(f"Result '{result_id}' not found")
    return RESULTS[result_id]


@router.get("/health", response_model=Health)
def health():
    return Health(status="ok", backend=overall_backend())


@router.get("/version", response_model=VersionInfo)
def version():
    return VersionInfo(api_version="1.0.0", modules=BACKENDS)


@router.get("/metrics", response_model=dict[str, float], summary="Single-process operational counters (authenticated when enabled)")
def metrics_snapshot():
    from mooring.core.metrics import snapshot
    values=snapshot()
    values["queue_depth"]=sum(j.task and j.task_state=="queued" for j in list(JOBS.jobs.values()))
    values["active_jobs"]=JOBS.active_count()
    return values
