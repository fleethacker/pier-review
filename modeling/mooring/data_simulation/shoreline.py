"""Bounded public shoreline evidence and conservative footprint intersection checks.

This module transforms the checked-in NOAA fixture without simplifying, closing
source lines or inventing a navigable-water polygon. These checks establish only
intersection with known features, never depth, current occupancy or safe water.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Polygon, box, shape
from shapely.ops import transform, unary_union

from mooring.transit.geo import LocalPlane

SOURCE_PATH = Path(__file__).parent / "data/norfolk_piers_shoreline.geojson"
NORFOLK_BERTHS = frozenset(("NAVSTA-NORFOLK-P12-N", "NAVSTA-NORFOLK-P12-S"))


class ShorelineIntersection(ValueError):
    """A whole-body footprint touches a feature in the supplied shoreline fixture."""


@lru_cache(maxsize=1)
def _source():
    return json.loads(SOURCE_PATH.read_text())


@lru_cache(maxsize=8)
def _local_geometry(lat, lon, bearing):
    plane, angle = LocalPlane(lat, lon), math.radians(bearing)

    def local(longitude, latitude):
        east, north = plane.to_local(latitude, longitude)
        return ((east*math.sin(angle)+north*math.cos(angle))/.3048,
                (east*math.sin(angle-math.pi/2)+north*math.cos(angle-math.pi/2))/.3048)

    source = _source()
    features = [(feature["properties"], transform(local, shape(feature["geometry"])))
                for feature in source["features"]]
    coverage = transform(local, box(*source["properties"]["bounds_wgs84"]))
    return features, coverage, unary_union([geometry for _, geometry in features])


def geometry_for(berth):
    """Return source features, bounded coverage and known features in berth feet."""
    if berth.berth_id not in NORFOLK_BERTHS:
        return None
    return _local_geometry(berth.origin_lat, berth.origin_lon, berth.face_bearing_true_deg)


def rectangle(x_ft, y_ft, yaw_rad, length_ft, beam_ft):
    """Full LOA/beam envelope; conservative relative to the tapered display hull."""
    c, s = math.cos(yaw_rad), math.sin(yaw_rad)
    return Polygon([(x_ft+x*c-y*s, y_ft+x*s+y*c) for x, y in (
        (-length_ft/2, -beam_ft/2), (length_ft/2, -beam_ft/2),
        (length_ft/2, beam_ft/2), (-length_ft/2, beam_ft/2))])


def validate_footprints(berth, footprints):
    """Reject known intersections; uncovered and incomplete coverage stays unknown."""
    geometry = geometry_for(berth)
    if geometry is None:
        return
    features, _, hazards = geometry
    for identifier, footprint in footprints:
        if footprint.intersects(hazards):
            hit = next(props for props, geom in features if footprint.intersects(geom))
            name = hit.get("OBJNAM") or hit.get("LNAM") or hit["objectType"]
            raise ShorelineIntersection(
                f"Initial {identifier} footprint intersects known NOAA shoreline ({name}). "
                "Choose another initial pose; unmarked areas are not established navigable water.")


def validate_initial(berth, ship, initial, tug_configs):
    footprints = [("ship", rectangle(initial.x_ft, initial.y_ft,
        math.radians(berth.face_bearing_true_deg-initial.heading_true_deg), ship.loa_ft, ship.beam_ft))]
    footprints.extend((f"tug {config.tug_id}", rectangle(config.initial_state.x_ft, config.initial_state.y_ft,
        math.radians(config.initial_state.yaw_deg), config.length_ft, config.beam_ft)) for config in tug_configs)
    validate_footprints(berth, footprints)


def validate_model_state(model):
    """Validate a prepared Motion replacement before any caller-owned state changes."""
    if not getattr(model, "motion_geography", False):
        return
    footprints = [("ship", rectangle(*model.integrator.state[:3], model.ship.loa_ft, model.ship.beam_ft))]
    fleet = model.tug_dynamics
    if fleet is not None:
        auxiliary = model.auxiliary_at()
        footprints.extend((f"tug {tid}", rectangle(*auxiliary[fleet.offsets[tid]:fleet.offsets[tid]+3],
            fleet.configs[tid].length_ft, fleet.configs[tid].beam_ft)) for tid in fleet.ids)
    validate_footprints(model.berth, footprints)


def scene_context(berth):
    geometry = geometry_for(berth)
    if geometry is None:
        return None
    features, coverage, _ = geometry
    rows = []

    def positions(coords):
        return [{"x_ft": x, "y_ft": y, "z_mllw_ft": None} for x, y in coords]

    kinds = {"LNDARE": "land", "SLCONS": "shoreline_construction", "COALNE": "coastline"}
    for props, geom in features:
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        for index, part in enumerate(parts):
            rings = ([positions(part.exterior.coords), *(positions(ring.coords) for ring in part.interiors)]
                     if part.geom_type == "Polygon" else [positions(part.coords)])
            rows.append(dict(feature_id=f"{props['LNAM']}:{index}", kind=kinds[props['objectType']],
                name=props.get("OBJNAM"), geometry_type=part.geom_type, rings=rings,
                source_date=props.get("SORDAT")))
    source = _source()["properties"]
    return dict(coordinate_frame="berth_ft", coverage="partial", coverage_outline=positions(coverage.exterior.coords),
        features=rows, source=source["source"], attribution=source["attribution"],
        retrieved_at_utc=source["retrieved_at_utc"], runtime_collision_checks=False,
        limitations=[source["limitations"],
            "Geography outside the coverage outline is unknown; missing features inside it do not establish navigable water.",
            "Initial ship and independent tug footprints are checked against these known features; runtime shoreline collision is not modeled.",
            "Open shoreline construction lines remain open; no surveyed berth planform is inferred."])
