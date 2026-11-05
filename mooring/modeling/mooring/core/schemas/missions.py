"""S5 mission storyboarding: recorded tracks, images and reports tied together by time.

Positions are WGS84 latitude/longitude in decimal degrees. Every timestamp is timezone-aware UTC on the wire; naive
input is rejected unless the caller states its UTC offset. A position at an event time is located on the track by an
explicit method and is never extrapolated beyond the recorded fixes.
"""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .common import Model, Validity

Latitude = Field(ge=-90, le=90)
Longitude = Field(ge=-180, le=180)


class TrackFix(Model):
    """One recorded (or simulated) position. Shared by S5 ingestion and S6 simulated tracks."""

    wire_omitted_defaults = {"heading_true_deg": None, "cog_true_deg": None, "sog_kt": None, "hdop": None,
                             "source": None}
    t_utc: AwareDatetime
    lat: float = Latitude
    lon: float = Longitude
    heading_true_deg: float | None = Field(default=None, ge=0, lt=360, description="Bow heading, if recorded.")
    cog_true_deg: float | None = Field(default=None, ge=0, lt=360, description="Course over ground, if recorded.")
    sog_kt: float | None = Field(default=None, ge=0, description="Speed over ground, if recorded.")
    hdop: float | None = Field(default=None, ge=0)
    quality: Literal["good", "degraded", "unknown"] = "unknown"
    source: str | None = Field(default=None, max_length=120, description="e.g. gps, ais, nmea, simulated:<job_id>.")


class MissionCreate(Model):
    wire_omitted_defaults = {"ship_class_id": None, "description": None}
    name: str = Field(min_length=1, max_length=200)
    vessel_id: str = Field(min_length=1, max_length=120, description="Hull number, MMSI or local identifier.")
    ship_class_id: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=4000)


class Mission(MissionCreate):
    wire_omitted_defaults = {**MissionCreate.wire_omitted_defaults, "start_utc": None, "end_utc": None}
    mission_id: str
    created_at_utc: AwareDatetime
    fix_count: int = Field(ge=0)
    media_count: int = Field(ge=0)
    report_count: int = Field(ge=0)
    start_utc: AwareDatetime | None = None
    end_utc: AwareDatetime | None = None


class TrackIngest(Model):
    """JSON track ingestion. Fixes are merged with any existing track for the mission."""

    fixes: list[TrackFix] = Field(min_length=1, max_length=200_000)


TrackFormat = Literal["csv", "gpx", "nmea", "geojson", "json"]


class TrackIngestResult(Model):
    wire_omitted_defaults = {"start_utc": None, "end_utc": None}
    mission_id: str
    format: TrackFormat
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    duplicates: int = Field(ge=0, description="Fixes with a timestamp already present; the first one is kept.")
    reordered: int = Field(ge=0, description="Fixes received out of time order (stored sorted).")
    errors: list[str] = Field(default_factory=list, max_length=50, description="First errors, with line/record numbers.")
    fix_count: int = Field(ge=0, description="Total fixes now stored for the mission.")
    start_utc: AwareDatetime | None = None
    end_utc: AwareDatetime | None = None


class MissionTrack(Model):
    mission_id: str
    fix_count: int = Field(ge=0, description="Stored fixes, before any display decimation.")
    decimated: bool = Field(description="True when fewer fixes are returned than stored (shape-preserving).")
    fixes: list[TrackFix]


TimeSource = Literal["exif", "supplied"]


class MediaMetadata(Model):
    """Multipart `metadata` JSON for an image upload."""

    wire_omitted_defaults = {"captured_utc": None, "exif_utc_offset_min": None, "caption": None}
    captured_utc: AwareDatetime | None = Field(default=None, description="Overrides EXIF time when given.")
    exif_utc_offset_min: int | None = Field(default=None, ge=-14 * 60, le=14 * 60,
        description="UTC offset of the camera clock when EXIF has no OffsetTimeOriginal. Required to use a naive EXIF time.")
    camera_clock_offset_s: float = Field(default=0.0, ge=-86_400, le=86_400,
        description="Seconds to ADD to the camera time to get true time (camera slow = positive).")
    caption: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=32)


class MediaItem(Model):
    wire_omitted_defaults = {"captured_utc": None, "exif_lat": None, "exif_lon": None, "caption": None,
                             "time_note": None}
    media_id: str
    mission_id: str
    filename: str
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    bytes: int = Field(ge=1)
    sha256: str
    captured_utc: AwareDatetime | None = Field(default=None, description="True time after offsets; null if unknown.")
    time_source: TimeSource | None = None
    time_note: str | None = Field(default=None, description="How the time was derived, or why it is unknown.")
    camera_clock_offset_s: float = 0.0
    exif_lat: float | None = Field(default=None, ge=-90, le=90)
    exif_lon: float | None = Field(default=None, ge=-180, le=180)
    caption: str | None = None
    tags: list[str] = Field(default_factory=list)
    url: str = Field(description="GET path for the image bytes.")


class ReportCreate(Model):
    wire_omitted_defaults = {"author": None, "lat": None, "lon": None}
    t_utc: AwareDatetime
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=20_000)
    author: str | None = Field(default=None, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90, description="Position stated in the report, if any.")
    lon: float | None = Field(default=None, ge=-180, le=180)
    tags: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def position_pair(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be given together")
        return self


class Report(ReportCreate):
    report_id: str
    mission_id: str


LocateMethod = Literal["exact_fix", "interpolated", "gap", "before_track", "after_track", "no_track", "no_time"]


class LocatedAt(Model):
    """Where the ship was at an event time, and how that was established. Null position means not established."""

    wire_omitted_defaults = {"lat": None, "lon": None, "fix_before_utc": None, "fix_after_utc": None, "gap_s": None,
                             "distance_along_track_nm": None, "sog_kt": None, "heading_true_deg": None,
                             "stated_lat": None, "stated_lon": None, "stated_source": None, "discrepancy_m": None}
    method: LocateMethod
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    fix_before_utc: AwareDatetime | None = None
    fix_after_utc: AwareDatetime | None = None
    gap_s: float | None = Field(default=None, ge=0, description="Span between the bracketing fixes.")
    distance_along_track_nm: float | None = Field(default=None, ge=0)
    sog_kt: float | None = Field(default=None, ge=0, description="Speed over ground between the bracketing fixes.")
    heading_true_deg: float | None = Field(default=None, ge=0, lt=360)
    stated_lat: float | None = Field(default=None, ge=-90, le=90, description="Position from EXIF or the report.")
    stated_lon: float | None = Field(default=None, ge=-180, le=180)
    stated_source: Literal["exif", "report"] | None = None
    discrepancy_m: float | None = Field(default=None, ge=0, description="Track position vs stated position.")
    validity: Validity


class StoryboardEvent(Model):
    wire_omitted_defaults = {"t_utc": None, "media_url": None, "body": None}
    kind: Literal["image", "report"]
    event_id: str = Field(description="media_id or report_id.")
    t_utc: AwareDatetime | None = None
    title: str
    body: str | None = None
    media_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    located: LocatedAt


class TrackStats(Model):
    wire_omitted_defaults = {"start_utc": None, "end_utc": None}
    fix_count: int = Field(ge=0)
    start_utc: AwareDatetime | None = None
    end_utc: AwareDatetime | None = None
    duration_s: float = Field(ge=0)
    distance_nm: float = Field(ge=0)
    max_gap_s: float = Field(ge=0)
    gaps_over_limit: int = Field(ge=0, description="Gaps longer than max_interp_gap_s.")


class Storyboard(Model):
    mission: Mission
    max_interp_gap_s: float = Field(gt=0)
    stats: TrackStats
    track: list[TrackFix] = Field(description="Shape-preserving decimated track for display.")
    events: list[StoryboardEvent] = Field(description="Time order; events without a time come last.")
    validity: Validity
