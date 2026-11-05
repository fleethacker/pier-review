"""Fetch OpenStreetMap coastline ways around Hampton Roads / Norfolk and write a small simplified GeoJSON fixture used by
modeling/tests/test_s6_presets_coastline.py to check that the S6 demonstration routes do not cross land.

Usage:  uv run --all-packages python scripts/fetch_transit_coastline.py [--out PATH] [--tolerance-m 8]

Data: (c) OpenStreetMap contributors, Open Database License (ODbL) 1.0, https://www.openstreetmap.org/copyright, queried from the
Overpass API (natural=coastline ways). The fixture is a derived, simplified database (Douglas-Peucker, default 8 m); it is
for an offline regression check of demonstration routes only. It is NOT a chart, not survey-accurate and not for navigation.
Overpass is rate limited: the script retries with backoff and exits non-zero (leaving any existing fixture untouched) if it
cannot get an answer.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import polygonize, unary_union

BBOX = (36.88, -76.50, 37.05, -75.98)          # south, west, north, east: Thimble Shoal Channel to NAVSTA Norfolk
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
UA = "psp-transit-coastline-check/1.0 (offline test fixture; mooring planning tool)"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "modeling" / "tests" / "fixtures" / "transit" / "hampton_roads_coastline.geojson"
OPEN_DEG = 0.0005
ATTRIBUTION = "(c) OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright"


def _post(q: str, tries: int = 6) -> dict:
    body = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for k in range(tries):
        for url in ENDPOINTS:
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.load(resp)
            except Exception as exc:  # noqa: BLE001 - report and retry
                last = exc
                print(f"overpass {url}: {exc}", file=sys.stderr)
        time.sleep(15 * (k + 1))
    raise SystemExit(f"Overpass unreachable after {tries} rounds: {last}")


def fetch(bbox=BBOX) -> tuple[dict, dict]:
    """(coastline ways, inland water relations). OSM's natural=coastline stops at the mouth of Hampton Roads (a closing line
    from Sewells Point to Old Point Comfort); the harbour behind it is mapped as water multipolygons, fetched separately."""
    b = f"({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]})"
    coast = _post(f'[out:json][timeout:90];way["natural"="coastline"]{b};out geom;')
    water = _post(f'[out:json][timeout:90];relation["natural"~"^(water|bay)$"]["name"~"^(Hampton Roads|Willoughby Bay|Elizabeth River)$"]{b};out geom;')
    return coast, water


def _assemble_water(water: dict):
    """Each relation: polygonize all member ways; the largest face is the outer ring, smaller faces are islands (holes)."""
    out = []
    for el in water.get("elements", []):
        lines = [LineString([(g["lon"], g["lat"]) for g in m["geometry"]]) for m in el.get("members", []) if len(m.get("geometry", [])) > 1]
        faces = sorted(polygonize(unary_union(lines)), key=lambda p: -p.area)
        if faces:
            out.append((el.get("tags", {}).get("name", str(el["id"])), faces[0].difference(unary_union(faces[1:])) if len(faces) > 1 else faces[0]))
    return out


def _land_from_coastline(lines: list[LineString], bbox=BBOX):
    """Polygonize the coastline ways together with the bbox boundary and keep the faces that lie on the LEFT of the ways
    (OSM convention: land on the left, water on the right)."""
    faces = list(polygonize(unary_union(lines + [box(bbox[1], bbox[0], bbox[3], bbox[2]).boundary])))
    land = []
    for f in faces:
        votes = 0
        for ln in lines:
            c = list(ln.coords)
            for (x1, y1), (x2, y2) in zip(c, c[1:]):
                dx, dy = x2 - x1, y2 - y1
                n = math.hypot(dx, dy)
                if n < 1e-9:
                    continue
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                votes += f.contains(Point(mx - dy / n * 2e-5, my + dx / n * 2e-5)) - f.contains(Point(mx + dy / n * 2e-5, my - dx / n * 2e-5))
        if votes > 0:
            land.append(f)
    return unary_union(land)


def to_geojson(coast: dict, water: dict, tolerance_m: float) -> dict:
    tol = tolerance_m / 110_574.0
    lines, feats = [], []
    for el in coast.get("elements", []):
        if el.get("type") != "way" or len(el.get("geometry", [])) < 2:
            continue
        ln = LineString([(g["lon"], g["lat"]) for g in el["geometry"]])
        lines.append(ln)
        simp = ln.simplify(tol, preserve_topology=False)
        feats.append({"type": "Feature", "properties": {"kind": "coastline", "osm_way": el["id"]},
                      "geometry": {"type": "LineString", "coordinates": [[round(x, 5), round(y, 5)] for x, y in simp.coords]}})
    bays = _assemble_water(water)
    bay_union = unary_union([g for _, g in bays])
    for name, g in bays:
        feats.append({"type": "Feature", "properties": {"kind": "water_body", "name": name}, "geometry": mapping(g.simplify(tol))})
    # OSM's coastline stops at a closing line across the mouth of Hampton Roads and the water relations are crude outlines there, so the
    # difference leaves thin slivers; a morphological opening (erode then dilate by OPEN_DEG, about 55 m) removes them (and any real
    # feature narrower than ~110 m, such as a pier) and changes the land area by about 0.1 %.
    land = _land_from_coastline(lines).difference(bay_union).buffer(-OPEN_DEG).buffer(OPEN_DEG).simplify(tol)
    feats.append({"type": "Feature", "properties": {"kind": "land", "note": "opened (55 m) polygonized coastline land minus the Hampton Roads / Willoughby Bay / Elizabeth River water bodies"},
                  "geometry": mapping(land)})
    return {"type": "FeatureCollection",
            "properties": {"attribution": ATTRIBUTION, "license": "ODbL 1.0", "source": "OpenStreetMap natural=coastline and Hampton Roads / Willoughby Bay / Elizabeth River water relations via Overpass API",
                           "bbox_south_west_north_east": list(BBOX), "simplify_tolerance_m": tolerance_m,
                           "fetched_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                           "note": "Land is on the left of each coastline way (OSM convention). Derived, simplified; not a chart, "
                                   "not for navigation. Used only to check that S6 demonstration routes avoid land."},
            "features": feats}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--tolerance-m", type=float, default=8.0)
    a = ap.parse_args()
    gj = to_geojson(*fetch(), a.tolerance_m)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(gj, separators=(",", ":")) + "\n")
    n = sum(len(f["geometry"]["coordinates"]) for f in gj["features"] if f["geometry"]["type"] == "LineString")
    print(f"wrote {a.out}: {len(gj['features'])} features, {n} coastline points, {a.out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
