"""Berth Map agent schemas (M8). The image is sent as multipart form data."""

from typing import Literal

from pydantic import Field

from mooring.core.schemas import Envelope, Model, SideTo
from mooring.core.schemas import MooringConfig
from mooring.core.schemas import Berth


class GeorefPoint(Model):
    px: tuple[float, float] = Field(description="Pixel [x, y] in the uploaded image.")
    lat: float
    lon: float


class Georef(Model):
    points: list[GeorefPoint] | None = Field(default=None, description="Two or more known points.")
    scale_ft_per_px: float | None = Field(default=None, gt=0)


class VisionMetadata(Model):
    """Sent as the `metadata` form field (a JSON string) next to the `image` file."""

    wire_omitted_defaults = {"berth_id": None, "pier_face_start_px": None, "pier_face_end_px": None}
    berth_id: str | None = Field(default=None, description="Catalog berth supplying surveyed face location and notional fittings; absent uses an explicitly labeled demo template.")
    pier_face_start_px: tuple[float, float] | None = None
    pier_face_end_px: tuple[float, float] | None = None
    image_kind: Literal["satellite", "chart", "berthing_plan", "photo"]
    georef: Georef | None = None
    berth_name: str | None = None
    ship_class_id: str | None = None
    side_to: SideTo | None = None


class Detection(Model):
    item_id: str
    kind: str = Field(description="Pier fitting kind, 'fender', 'camel', 'pier_face' or 'obstruction'.")
    wire_omitted_defaults = {"center_px": None}
    center_px: tuple[float, float] | None = None
    bbox_px: tuple[float, float, float, float] | None = Field(description="[x, y, width, height] in image pixels; null when not measured from the image.")
    confidence: float = Field(ge=0, le=1)
    needs_confirmation: bool


class VisionResult(Model):
    wire_omitted_defaults = {"extraction_source": None, "extraction_note": None, "geometry_result_id": None, "image_sha256": None, "recommendation_result_id": None}
    recommendation_result_id: str | None = None
    extraction_source: Literal["deterministic", "llm"] | None = None
    extraction_note: str | None = None
    geometry_result_id: str | None = None
    image_sha256: str | None = None
    draft_berth: Berth
    detections: list[Detection]
    recommended_config: MooringConfig | None
    questions: list[str]


class VisionResponse(Envelope[VisionResult]):
    pass


class VisionConfirm(Model):
    berth: Berth
