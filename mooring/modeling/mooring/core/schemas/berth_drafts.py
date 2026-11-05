"""Geometry conversion for human-confirmed image drafts; capacities are never inferred from pixels."""
from typing import Annotated
from pydantic import Field, model_validator

from .common import Envelope, Model
from .refdata import Berth


Pixel = Annotated[float, Field(ge=0, le=1_000_000)]


class ImageFitting(Model):
    item_id: str = Field(min_length=1, max_length=80)
    kind: str
    center_px: tuple[Pixel, Pixel]
    confidence: float = Field(ge=0, le=1)


class BerthDraftRequest(Model):
    source_berth_id: str
    name: str | None = None
    image_fittings: list[ImageFitting] = Field(default_factory=list, max_length=100)
    scale_ft_per_px: float | None = Field(default=None, gt=0, le=10000)
    pier_face_start_px: tuple[Pixel, Pixel] | None = None
    pier_face_end_px: tuple[Pixel, Pixel] | None = None

    @model_validator(mode='after')
    def image_geometry(self):
        if self.image_fittings and (self.scale_ft_per_px is None or self.pier_face_start_px is None or self.pier_face_end_px is None):
            raise ValueError('Image fittings require scale and two pier-face pixel anchors')
        if self.pier_face_start_px is not None and self.pier_face_start_px == self.pier_face_end_px:
            raise ValueError('Pier-face pixel anchors must be distinct')
        if len({f.item_id for f in self.image_fittings}) != len(self.image_fittings):
            raise ValueError('Image fitting identifiers must be unique')
        return self


class BerthDraftResult(Model):
    draft_berth: Berth
    geometry_source: str
    needs_confirmation: list[str]
    notes: list[str]


class BerthDraftResponse(Envelope[BerthDraftResult]):
    pass
