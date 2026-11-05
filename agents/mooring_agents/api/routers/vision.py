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
from ..state import JOBS, VisionTools
from ...physics.client import ModelingError
from ...vision.agent import MAX_IMAGE_BYTES

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
    resp = await vision.analyze(await image.read(MAX_IMAGE_BYTES + 1), image.filename or "upload", meta, tk)
    accepted = JOBS.submit("berth_vision.analyze", resp)
    VISION_RESULTS[accepted.job_id] = resp.model_dump(mode="json")
    return accepted


@router.post("/berth-vision/{job_id}/confirm", response_model=BerthCreated, status_code=201,
             summary="Save the human-confirmed berth to the modeling service")
async def vision_confirm(job_id: str, req: VisionConfirm, tk: VisionTools):
    if job_id not in VISION_RESULTS:
        raise refdata.NotFound(f"Vision job '{job_id}' not found")
    original = VISION_RESULTS[job_id]["result"]["draft_berth"]
    if req.berth.berth_id != original["berth_id"]:
        raise ModelingError(422, "Confirmation must preserve the draft berth id; it cannot replace another berth")
    from mooring.core.schemas import Provenance
    berth = req.berth.model_copy(update={"provenance": Provenance(
        source=original["provenance"]["source"], confidence="estimated",
        notes=(original["provenance"].get("notes") or "") + " Confirmed/edited by user; engineering qualification not established.")})
    return await tk.save_berth(berth)
