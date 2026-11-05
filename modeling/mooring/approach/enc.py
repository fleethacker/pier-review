"""NOAA ENC metadata and depth-area evaluation; not operational chart qualification (DC6)."""
from dataclasses import dataclass
from datetime import datetime
import math
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
    sounding_datum: str
    depth_units: str


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
    limitations: tuple[str, ...] = (
        "DEPARE lower bounds only; soundings, wrecks, obstructions and survey quality are not evaluated.",
        "Coverage is not operational clearance or chart currency qualification.",
    )


def _metadata(cell: str, props: dict[str, Any], datum: dict[str, Any]) -> ENCMetadata:
    fields = {
        "edition": props.get("EDTN"),
        "update number": props.get("UPDN"),
        "issue date": props.get("ISDT"),
        "horizontal datum": datum.get("HDAT"),
        "vertical datum": datum.get("VDAT"),
        "sounding datum": datum.get("SDAT"),
        "depth units": datum.get("DUNI"),
    }
    missing = [name for name, value in fields.items() if value is None or str(value).strip() == ""]
    if missing:
        raise ENCError(f"S-57 metadata is missing: {', '.join(missing)}")
    try:
        if len(str(fields["issue date"])) != 8:
            raise ValueError
        datetime.strptime(str(fields["issue date"]), "%Y%m%d")
        if int(fields["edition"]) <= 0 or int(fields["update number"]) < 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ENCError("S-57 edition, update number or issue date is invalid") from None
    return ENCMetadata(cell=cell, edition=str(fields["edition"]), update_number=str(fields["update number"]),
                       issue_date=str(fields["issue date"]), horizontal_datum=str(fields["horizontal datum"]),
                       vertical_datum=str(fields["vertical datum"]), sounding_datum=str(fields["sounding datum"]),
                       depth_units=str(fields["depth units"]))


def read_metadata(path: str | Path) -> ENCMetadata:
    """Read DSID/DSPM identity; GDAL applies adjacent numbered updates by default."""
    path = str(path)
    layers = set(fiona.listlayers(path))
    if "DSID" not in layers:
        raise ENCError("S-57 dataset lacks DSID metadata")
    with fiona.open(path, layer="DSID", allow_unsupported_drivers=True) as src:
        row = next(iter(src), None)
        if row is None:
            raise ENCError("S-57 DSID metadata is empty")
        record = dict(row["properties"])
    # GDAL S-57 DSID layer exposes DSID/DSSI/DSPM together with prefixed names.
    # https://gdal.org/en/stable/drivers/vector/s57.html#dsid-layer
    props = {key.removeprefix("DSID_"): value for key, value in record.items() if key.startswith("DSID_")}
    datum = {key.removeprefix("DSPM_"): value for key, value in record.items() if key.startswith("DSPM_")}
    if not props.get("DSNM"):
        raise ENCError("S-57 metadata lacks dataset identity")
    return _metadata(Path(str(props["DSNM"])).stem, props, datum)


def read_depth_areas(path: str | Path) -> list[DepthArea]:
    metadata = read_metadata(path)
    # Narrow supported subset: S-57 DSPM HDAT=2 (WGS84), DUNI=1 (metres),
    # SDAT=12 (MLLW). No datum/unit conversion is inferred from VDAT.
    if (metadata.horizontal_datum, metadata.depth_units, metadata.sounding_datum) != ("2", "1", "12"):
        raise ENCError("Depth reader requires WGS84, metres and MLLW sounding datum; no transformation is implemented")
    layers = fiona.listlayers(str(path))
    if "M_SDAT" in layers:
        with fiona.open(str(path), layer="M_SDAT", allow_unsupported_drivers=True) as src:
            if next(iter(src), None) is not None:
                raise ENCError("Local sounding-datum overrides require explicit handling")
    if "DEPARE" not in layers:
        raise ENCError("S-57 dataset lacks DEPARE coverage")
    result = []
    with fiona.open(str(path), layer="DEPARE", allow_unsupported_drivers=True) as src:
        if src.crs.to_epsg() != 4326:
            raise ENCError("Depth-area coordinate reference system must be EPSG:4326")
        for feature in src:
            props = feature["properties"]
            if props.get("DRVAL1") is None or feature["geometry"] is None:
                raise ENCError("DEPARE contains unknown minimum depth or geometry")
            area = DepthArea(shape(feature["geometry"]), float(props["DRVAL1"]),
                             None if props.get("DRVAL2") is None else float(props["DRVAL2"]))
            _validate_area(area)
            result.append(area)
    if not result:
        raise ENCError("DEPARE has no usable minimum-depth values")
    return result


def _polygon(geometry):
    return geometry is not None and geometry.geom_type in ("Polygon", "MultiPolygon") and not geometry.is_empty and geometry.is_valid and geometry.area > 0


def _validate_area(area: DepthArea):
    if not _polygon(area.geometry):
        raise ENCError("Depth-area geometry must be a valid non-empty polygon")
    if not math.isfinite(area.minimum_depth_m) or (area.maximum_depth_m is not None and
            (not math.isfinite(area.maximum_depth_m) or area.maximum_depth_m < area.minimum_depth_m)):
        raise ENCError("Depth-area bounds must be finite and increasing")


def evaluate_corridor(corridor: Any, depth_areas: list[DepthArea]) -> CorridorDepth:
    """Evaluate every part of a precomputed swept polygon, not route waypoints."""
    if not _polygon(corridor):
        raise ENCError("swept corridor must be a valid non-empty polygon")
    for area in depth_areas:
        _validate_area(area)
    covered_geometry = unary_union([area.geometry for area in depth_areas])
    if not covered_geometry.covers(corridor):
        return CorridorDepth(None, False, "ENC depth-area coverage does not cover the full swept corridor")
    values = [area.minimum_depth_m for area in depth_areas if area.geometry.intersects(corridor)]
    return CorridorDepth(min(values), True) if values else CorridorDepth(None, False, "no depth area intersects the swept corridor")
