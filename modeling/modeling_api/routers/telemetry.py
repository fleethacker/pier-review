from typing import Annotated

from fastapi import APIRouter, Body

from mooring.core.schemas import TelemetryAccepted, TelemetryBatch
from mooring.mock.examples import ex

from ..backend import telemetry as impl

router = APIRouter(tags=["M13 Telemetry"])


@router.post("/telemetry/batch", response_model=TelemetryAccepted, status_code=202, summary="Ingest sensor records")
def batch(req: Annotated[TelemetryBatch, Body(openapi_examples=ex("telemetry_batch"))]):
    return impl.ingest(req)
