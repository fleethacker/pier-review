"""Refresh the bounded public shoreline evidence used by Motion demo tests.

Explicit utility only: no request is made by simulation or tests. NOAA's ENC
Online GIS service is not a navigation product. This extracts unsimplified land
and shoreline-construction geometry, clipped to the declared box; it supplies
neither depth nor a complete hazard inventory. No training geometry is invented.

Run: uv run --all-packages python -m mooring.data_simulation.norfolk_shoreline OUTPUT
"""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from shapely.geometry import GeometryCollection, LineString, Polygon, box, mapping

SOURCE = "https://gis.charttools.noaa.gov/arcgis/rest/services/MCS/ENCOnline/MapServer/exts/MaritimeChartService/MapServer/identify"
BOUNDS = (-76.35, 36.95, -76.31, 36.98)


def extract(payload, *, retrieved_at, sha256):
    region = box(*BOUNDS)
    features = []
    for item in payload["results"]:
        attrs, geometry = item["attributes"], item["geometry"]
        if attrs["objectType"] not in ("LNDARE", "SLCONS", "COALNE"):
            continue
        if "rings" in geometry:
            geom = GeometryCollection()
            for ring in geometry["rings"]:
                part = Polygon(ring)
                if not part.is_valid:
                    raise ValueError("Invalid source ring; inspect the public source before replacing evidence")
                geom = geom.symmetric_difference(part)
        elif "paths" in geometry:
            geom = GeometryCollection([LineString(path) for path in geometry["paths"]])
        else:
            continue
        clipped = geom.intersection(region)
        if clipped.is_empty:
            continue
        features.append({"type": "Feature", "properties": {key: attrs[key] for key in
            ("objectType", "LNAM", "cellName", "compilationScale", "OBJNAM", "WATLEV", "SORDAT", "SORIND")
            if key in attrs}, "geometry": mapping(clipped)})
    if not any(f["properties"]["objectType"] == "LNDARE" for f in features):
        raise ValueError("No land geometry returned; cannot establish geographic evidence")
    return {"type": "FeatureCollection", "properties": {
        "source": SOURCE, "retrieved_at_utc": retrieved_at, "response_sha256": sha256,
        "bounds_wgs84": BOUNDS, "attribution": "NOAA Office of Coast Survey, ENC Online public GIS service",
        "derivation": "Selected LNDARE, SLCONS and COALNE; exact polygon/line clipping, no simplification or manual edits.",
        "limitations": "Not for navigation. Source dates vary. No bathymetry, traffic or complete hazard coverage; not a survey of present conditions.",
    }, "features": features}


def fetch(path):
    xmin, ymin, xmax, ymax = BOUNDS
    params = dict(geometry=json.dumps(dict(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax,
        spatialReference={"wkid": 4326})), geometrytype="esriGeometryEnvelope", sr="4326",
        spatialreference="4326", tolerance="0", returngeometry="true",
        mapextent=",".join(map(str, BOUNDS)), imagedisplay="1024,768,96", layers="all:1,4", f="json")
    response = httpx.get(SOURCE, params=params, timeout=30)
    response.raise_for_status()
    result = extract(response.json(), retrieved_at=datetime.now(UTC).isoformat(),
        sha256=hashlib.sha256(response.content).hexdigest())
    Path(path).write_text(json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("supply the output GeoJSON path")
    fetch(sys.argv[1])
