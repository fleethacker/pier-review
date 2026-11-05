import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Body, Header, HTTPException

from mooring.core.schemas import TelemetryAccepted, TelemetryBatch
from mooring.examples import ex

from ..backend import telemetry as impl

router = APIRouter(tags=["M13 Telemetry"])


@router.post("/telemetry/batch", response_model=TelemetryAccepted, status_code=202, summary="Ingest sensor records")
def batch(req: Annotated[TelemetryBatch, Body(openapi_examples=ex("telemetry_batch"))],
          x_telemetry_key: Annotated[str | None, Header()] = None):
    """When MOORING_TELEMETRY_KEY is set the key is required (constant-time compare). Unset means local demo only."""
    key = os.environ.get("MOORING_TELEMETRY_KEY")
    if key and not (x_telemetry_key and hmac.compare_digest(key.encode(), x_telemetry_key.encode())):
        raise HTTPException(status_code=401, detail="telemetry key required")
    try:
        return impl.ingest(req)
    except ValueError as e:   # batch too large
        raise HTTPException(status_code=413, detail=str(e)) from None
