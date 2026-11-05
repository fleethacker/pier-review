"""S5 mission storyboarding: tracks, images and reports tied together by time. Implementation: mooring.missions."""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from mooring.core.schemas import (Mission, MissionCreate, MediaItem, MissionTrack, Report, ReportCreate, Storyboard,
                                  TrackIngest, TrackIngestResult)

router = APIRouter(tags=["S5 Missions"])


def _todo():
    raise HTTPException(status_code=501, detail="S5 not implemented yet")


@router.post("/missions", response_model=Mission, status_code=201, summary="Create a mission")
def create_mission(req: MissionCreate):
    _todo()


@router.get("/missions", response_model=list[Mission], summary="Missions visible to the caller")
def list_missions():
    _todo()


@router.get("/missions/{mission_id}", response_model=Mission, summary="One mission")
def get_mission(mission_id: str):
    _todo()


@router.post("/missions/{mission_id}/track", response_model=TrackIngestResult, summary="Add recorded fixes (JSON)")
def ingest_track(mission_id: str, req: TrackIngest):
    _todo()


@router.post("/missions/{mission_id}/track/file", response_model=TrackIngestResult,
             summary="Add recorded fixes from a CSV, GPX, NMEA 0183 (RMC/GGA) or GeoJSON file")
async def ingest_track_file(mission_id: str,
                            file: Annotated[UploadFile, File(description="Track file, at most 20 MB")],
                            format: Annotated[str, Form(description="csv | gpx | nmea | geojson")],
                            utc_offset_min: Annotated[int | None, Form(description="Offset of naive timestamps, minutes east of UTC")] = None,
                            nmea_date: Annotated[str | None, Form(description="YYYY-MM-DD for NMEA files with GGA only")] = None):
    _todo()


@router.get("/missions/{mission_id}/track", response_model=MissionTrack, summary="Recorded track, optionally decimated")
def get_track(mission_id: str, max_points: Annotated[int, Query(ge=2, le=200_000)] = 5000):
    _todo()


@router.post("/missions/{mission_id}/media", response_model=MediaItem, status_code=201,
             summary="Upload an image (JPEG, PNG or WebP, at most 8 MB) with optional time/offset metadata")
async def upload_media(mission_id: str, image: Annotated[UploadFile, File()],
                       metadata: Annotated[str | None, Form(description="MediaMetadata as JSON")] = None):
    _todo()


@router.get("/missions/{mission_id}/media", response_model=list[MediaItem], summary="Images for a mission")
def list_media(mission_id: str):
    _todo()


@router.get("/missions/{mission_id}/media/{media_id}", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}}},
            summary="Image bytes")
def get_media(mission_id: str, media_id: str):
    _todo()


@router.post("/missions/{mission_id}/reports", response_model=Report, status_code=201, summary="Add a timestamped report")
def add_report(mission_id: str, req: ReportCreate):
    _todo()


@router.get("/missions/{mission_id}/reports", response_model=list[Report], summary="Reports for a mission")
def list_reports(mission_id: str):
    _todo()


@router.get("/missions/{mission_id}/storyboard", response_model=Storyboard,
            summary="Track plus images and reports located on it by time")
def storyboard(mission_id: str,
               max_interp_gap_s: Annotated[float, Query(gt=0, le=86_400)] = 300.0,
               max_points: Annotated[int, Query(ge=2, le=50_000)] = 2000):
    _todo()


@router.get("/missions/{mission_id}/storyboard.geojson", response_class=Response,
            responses={200: {"content": {"application/geo+json": {}}}},
            summary="Storyboard as a GeoJSON FeatureCollection (track LineString, event Points)")
def storyboard_geojson(mission_id: str, max_interp_gap_s: Annotated[float, Query(gt=0, le=86_400)] = 300.0):
    _todo()
