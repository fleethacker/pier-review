"""S5 mission storyboarding: tracks, images and reports tied together by time. Implementation: mooring.missions."""

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from mooring.core.schemas import (
    MediaItem,
    Mission,
    MissionCreate,
    MissionTrack,
    Report,
    ReportCreate,
    Storyboard,
    TrackIngest,
    TrackIngestResult,
)
from mooring.core.schemas.missions import MediaMetadata
from mooring.missions import exif, parsers, store
from mooring.missions import storyboard as sb
from pydantic import ValidationError

from ..state import API_PREFIX

router = APIRouter(tags=["S5 Missions"])

MAX_TRACK_FILE_BYTES = 20_000_000
_PARSERS = {"csv": parsers.parse_csv, "gpx": parsers.parse_gpx, "geojson": parsers.parse_geojson}


async def _read_limited(upload: UploadFile, limit: int, what: str) -> bytes:
    buf = bytearray()
    while chunk := await upload.read(1 << 20):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, f"{what} larger than {limit} bytes")
    return bytes(buf)


def _limit(fn, *a):
    try:
        return fn(*a)
    except store.LimitExceeded as exc:
        raise HTTPException(409, str(exc)) from exc


def _ingest(mission_id, result: parsers.ParseResult, fmt: str) -> TrackIngestResult:
    store.require(mission_id)
    if not result.fixes and result.rejected:
        raise HTTPException(422, {"message": "no valid fixes in the upload", "rejected": result.rejected,
                                  "errors": result.errors})
    if not result.fixes:
        raise HTTPException(422, "the upload contains no fixes")
    return _limit(store.ingest, mission_id, result.fixes, result.rejected, result.errors, fmt)


@router.post("/missions", response_model=Mission, status_code=201, summary="Create a mission")
def create_mission(req: MissionCreate):
    return store.create_mission(req)


@router.get("/missions", response_model=list[Mission], summary="Missions visible to the caller")
def list_missions():
    return store.list_missions()


@router.get("/missions/{mission_id}", response_model=Mission, summary="One mission")
def get_mission(mission_id: str):
    return store.get_mission(mission_id)


@router.post("/missions/{mission_id}/track", response_model=TrackIngestResult, summary="Add recorded fixes (JSON)")
def ingest_track(mission_id: str, req: TrackIngest):
    store.require(mission_id)
    return _limit(store.ingest, mission_id, req.fixes, 0, [], "json")


@router.post("/missions/{mission_id}/track/file", response_model=TrackIngestResult,
             summary="Add recorded fixes from a CSV, GPX, NMEA 0183 (RMC/GGA) or GeoJSON file")
async def ingest_track_file(mission_id: str,
                            file: Annotated[UploadFile, File(description="Track file, at most 20 MB")],
                            format: Annotated[str, Form(description="csv | gpx | nmea | geojson")],
                            utc_offset_min: Annotated[int | None, Form(description="Offset of naive timestamps, minutes east of UTC")] = None,
                            nmea_date: Annotated[str | None, Form(description="YYYY-MM-DD for NMEA files with GGA only")] = None):
    store.require(mission_id)  # ownership/404 before reading the body
    fmt = format.strip().lower()
    if fmt not in ("csv", "gpx", "nmea", "geojson"):
        raise HTTPException(422, "format must be one of csv, gpx, nmea, geojson")
    if utc_offset_min is not None and not -840 <= utc_offset_min <= 840:
        raise HTTPException(422, "utc_offset_min must be within +-840")
    nd = None
    if nmea_date:
        try:
            nd = date.fromisoformat(nmea_date)
        except ValueError:
            raise HTTPException(422, "nmea_date must be YYYY-MM-DD") from None
    data = await _read_limited(file, MAX_TRACK_FILE_BYTES, "track file")
    try:
        result = parsers.parse_nmea(data, nd) if fmt == "nmea" else _PARSERS[fmt](data, utc_offset_min)
    except parsers.TrackParseError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _ingest(mission_id, result, fmt)


@router.get("/missions/{mission_id}/track", response_model=MissionTrack, summary="Recorded track, optionally decimated")
def get_track(mission_id: str, max_points: Annotated[int, Query(ge=2, le=200_000)] = 5000):
    return store.get_track(mission_id, max_points)


@router.post("/missions/{mission_id}/media", response_model=MediaItem, status_code=201,
             summary="Upload an image (JPEG, PNG or WebP, at most 8 MB) with optional time/offset metadata")
async def upload_media(mission_id: str, image: Annotated[UploadFile, File()],
                       metadata: Annotated[str | None, Form(description="MediaMetadata as JSON")] = None):
    store.require(mission_id)
    try:
        meta = MediaMetadata.model_validate_json(metadata) if metadata else MediaMetadata()
    except ValidationError as exc:
        raise HTTPException(422, json.loads(exc.json(include_url=False, include_context=False, include_input=False))) from exc
    data = await _read_limited(image, exif.MAX_IMAGE_BYTES, "image")
    try:
        return _limit(store.add_media, mission_id, image.filename, data, meta, API_PREFIX)
    except exif.ImageError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/missions/{mission_id}/media", response_model=list[MediaItem], summary="Images for a mission")
def list_media(mission_id: str):
    return store.list_media(mission_id, API_PREFIX)


@router.get("/missions/{mission_id}/media/{media_id}", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}}},
            summary="Image bytes")
def get_media(mission_id: str, media_id: str):
    ctype, data = store.media_bytes(mission_id, media_id)
    return Response(data, media_type=ctype, headers={"X-Content-Type-Options": "nosniff",
                                                     "Cache-Control": "private, max-age=3600"})


@router.post("/missions/{mission_id}/reports", response_model=Report, status_code=201, summary="Add a timestamped report")
def add_report(mission_id: str, req: ReportCreate):
    return _limit(store.add_report, mission_id, req)


@router.get("/missions/{mission_id}/reports", response_model=list[Report], summary="Reports for a mission")
def list_reports(mission_id: str):
    return store.list_reports(mission_id)


@router.get("/missions/{mission_id}/storyboard", response_model=Storyboard,
            summary="Track plus images and reports located on it by time")
def storyboard(mission_id: str,
               max_interp_gap_s: Annotated[float, Query(gt=0, le=86_400)] = 300.0,
               max_points: Annotated[int, Query(ge=2, le=50_000)] = 2000):
    return sb.build(mission_id, max_interp_gap_s, max_points, API_PREFIX)


@router.get("/missions/{mission_id}/storyboard.geojson", response_class=Response,
            responses={200: {"content": {"application/geo+json": {}}}},
            summary="Storyboard as a GeoJSON FeatureCollection (track LineString, event Points)")
def storyboard_geojson(mission_id: str, max_interp_gap_s: Annotated[float, Query(gt=0, le=86_400)] = 300.0):
    return JSONResponse(sb.geojson(mission_id, max_interp_gap_s, API_PREFIX), media_type="application/geo+json")
