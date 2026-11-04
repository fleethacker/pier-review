"""Berth Map agent endpoints."""

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from mooring import refdata
from mooring.core.schemas import BerthCreated, JobAccepted

from ...backend import vision
from ...vision.schemas import VisionConfirm, VisionMetadata
from ..state import JOBS, Client, VisionTools

router = APIRouter(tags=["Berth map agent"])
VISION_RESULTS: dict[str, dict] = {}  # job_id -> VisionResponse JSON
META_EXAMPLE = ('{"image_kind": "satellite", "georef": {"scale_ft_per_px": 0.5}, '
                '"ship_class_id": "DDG-51-FIIA", "side_to": "starboard"}')


@router.post("/berth-vision/analyze", response_model=JobAccepted, status_code=202,
             summary="Analyze a berth image (multipart: image + metadata JSON). Job result is a VisionResponse.")
async def vision_analyze(tk: VisionTools, image: Annotated[UploadFile, File(description="PNG, JPEG or PDF page")],
                         metadata: Annotated[str, Form(description=f"VisionMetadata as JSON, e.g. {META_EXAMPLE}")]):
    try:
        meta = VisionMetadata.model_validate_json(metadata)
    except ValidationError as e:
        return JSONResponse(status_code=422, content={"detail": json.loads(e.json())})
    resp = await vision.analyze(await image.read(), image.filename or "upload", meta, tk)
    accepted = JOBS.submit("berth_vision.analyze", resp)
    VISION_RESULTS[accepted.job_id] = resp.model_dump(mode="json")
    return accepted


@router.post("/berth-vision/{job_id}/confirm", response_model=BerthCreated, status_code=201,
             summary="Save the human-confirmed berth to the modeling service")
async def vision_confirm(job_id: str, req: VisionConfirm, client: Client):
    if job_id not in VISION_RESULTS:
        raise refdata.NotFound(f"Vision job '{job_id}' not found")
    berth = req.berth.model_copy(update={"provenance": req.berth.provenance.model_copy(
        update={"notes": (req.berth.provenance.notes or "") + " Confirmed by user."})})
    return BerthCreated(berth_id=await client.save_berth(berth))
