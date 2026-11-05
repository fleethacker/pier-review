"""Offline check that the S6 demonstration routes stay on OpenStreetMap water (fixture built by scripts/fetch_transit_coastline.py).

The land polygon is the OSM coastline land minus the Hampton Roads / Willoughby Bay / Elizabeth River water relations (ODbL, see the
fixture's attribution). Limits of the check: OSM's Hampton Roads outline is crude near Sewells Point, so the NAVSTA Pier 12 final point
(from the berth catalog) lies about 640 m inside the polygon's land; legs are therefore exempt within PIER_ZONE_M of the final point.
This is a coastline check only (no depths, channels, bridges or traffic): "demonstration route checked only against OSM coastline;
not a navigational route"."""

import json
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, shape

from mooring.transit import presets as P
from mooring.transit import simulator as S

FIXTURE = Path(__file__).parent / "fixtures" / "transit" / "hampton_roads_coastline.geojson"
GJ = json.loads(FIXTURE.read_text())
LAND = next(shape(f["geometry"]) for f in GJ["features"] if f["properties"]["kind"] == "land")
DEG_M = 110_000.0
PIER_ZONE_M = 1000.0
MIN_CLEARANCE_M = 100.0
PIER = Point(P.pier_point()[1], P.pier_point()[0])
ZONE = PIER.buffer(PIER_ZONE_M / DEG_M)


def test_fixture_carries_odbl_attribution_and_the_expected_features():
    assert "OpenStreetMap" in GJ["properties"]["attribution"] and GJ["properties"]["license"].startswith("ODbL")
    kinds = {f["properties"]["kind"] for f in GJ["features"]}
    assert {"coastline", "water_body", "land"} <= kinds
    assert FIXTURE.stat().st_size < 100_000


def test_fixture_land_and_water_are_sane():
    assert LAND.contains(Point(-76.25, 36.90))          # Norfolk / Virginia Beach side
    assert not LAND.contains(Point(-76.16, 36.995))     # Thimble Shoal Channel
    assert not LAND.contains(Point(-76.27, 36.985))     # Hampton Roads


@pytest.mark.parametrize("p", P.presets(), ids=lambda p: p.preset_id)
def test_every_preset_leg_avoids_land(p):
    for v in p.request.vessels:
        pts = [(v.start.lon, v.start.lat)] + [(w.lon, w.lat) for w in v.route]
        for a, b in zip(pts, pts[1:]):
            seg = LineString([a, b]).difference(ZONE)           # the final approach to the pier is exempt (see module docstring)
            if seg.is_empty:
                continue
            assert not seg.intersects(LAND), (p.preset_id, v.vessel_id, a, b)
            assert seg.distance(LAND) * DEG_M > MIN_CLEARANCE_M, (p.preset_id, v.vessel_id, seg.distance(LAND) * DEG_M)


@pytest.mark.parametrize("pid", ["ddg-inbound-own-thrust", "ddg-outbound-own-thrust"])
def test_simulated_tracks_stay_off_land_outside_the_pier_zone(pid):
    preset = next(p for p in P.presets() if p.preset_id == pid)
    r = S.run(preset.request)
    for v in r.vessels:
        for fix in v.track:
            pt = Point(fix.lon, fix.lat)
            if ZONE.contains(pt):
                continue
            assert not LAND.contains(pt), (pid, fix.t_utc, fix.lat, fix.lon)


def test_preset_descriptions_carry_the_route_label():
    for p in P.presets():
        assert "checked only against OSM coastline" in p.description and "not a navigational route" in p.description
