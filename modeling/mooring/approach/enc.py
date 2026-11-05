"""Qualified NOAA ENC ingestion and swept-corridor depth evaluation (DC6)."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fiona
from shapely.geometry import shape
from shapely.ops import unary_union


class ENCError(ValueError):
    pass


@dataclass(frozen=True)
class ENCMetadata:
    cell: str
    edition: str
    update_number: str
    issue_date: str
    horizontal_datum: str
    vertical_datum: str


@dataclass(frozen=True)
class DepthArea:
    geometry: Any
    minimum_depth_m: float
    maximum_depth_m: float | None = None


@dataclass(frozen=True)
class CorridorDepth:
    minimum_depth_m: float | None
    covered: bool
    reason: str | None = None


def _metadata(cell: str, props: dict[str, Any], datum: dict[str, Any]) -> ENCMetadata:
    fields = {
        "edition": props.get("EDTN"),
        "update number": props.get("UPDN"),
        "issue date": props.get("ISDT"),
        "horizontal datum": datum.get("HDAT"),
        "vertical datum": datum.get("VDAT") if datum.get("VDAT") is not None else datum.get("SDAT"),
    }
    missing = [name for name, value in fields.items() if value is None or str(value).strip() == ""]
    if missing:
        raise ENCError(f"S-57 metadata is missing: {', '.join(missing)}")
    return ENCMetadata(cell=cell, edition=str(fields["edition"]), update_number=str(fields["update number"]),
                       issue_date=str(fields["issue date"]), horizontal_datum=str(fields["horizontal datum"]),
                       vertical_datum=str(fields["vertical datum"]))


def read_metadata(path: str | Path) -> ENCMetadata:
    """Read DSID/DSPM identity; GDAL applies adjacent numbered updates by default."""
    path = str(path)
    layers = set(fiona.listlayers(path))
    if not {"DSID", "DSPM"}.issubset(layers):
        raise ENCError("S-57 dataset lacks DSID or DSPM metadata")
    with fiona.open(path, layer="DSID", allow_unsupported_drivers=True) as src:
        props = dict(next(iter(src))["properties"])
    with fiona.open(path, layer="DSPM", allow_unsupported_drivers=True) as src:
        datum = dict(next(iter(src))["properties"])
    return _metadata(Path(path).stem, props, datum)


def read_depth_areas(path: str | Path) -> list[DepthArea]:
    if "DEPARE" not in fiona.listlayers(str(path)):
        raise ENCError("S-57 dataset lacks DEPARE coverage")
    result = []
    with fiona.open(str(path), layer="DEPARE", allow_unsupported_drivers=True) as src:
        for feature in src:
            props = feature["properties"]
            if props.get("DRVAL1") is not None:
                result.append(DepthArea(shape(feature["geometry"]), float(props["DRVAL1"]),
                                        None if props.get("DRVAL2") is None else float(props["DRVAL2"])))
    if not result:
        raise ENCError("DEPARE has no qualified minimum-depth values")
    return result


def evaluate_corridor(corridor: Any, depth_areas: list[DepthArea]) -> CorridorDepth:
    """Evaluate every part of a precomputed swept polygon, not route waypoints."""
    if corridor.is_empty or corridor.area <= 0:
        raise ENCError("swept corridor must be a non-empty polygon")
    covered_geometry = unary_union([area.geometry for area in depth_areas])
    if not covered_geometry.covers(corridor):
        return CorridorDepth(None, False, "ENC depth-area coverage does not cover the full swept corridor")
    values = [area.minimum_depth_m for area in depth_areas if area.geometry.intersects(corridor)]
    return CorridorDepth(min(values), True) if values else CorridorDepth(None, False, "no depth area intersects the swept corridor")
