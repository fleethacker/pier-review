"""S5 locating events on a track, geometry and decimation. Hand-computed on the equator where 1 deg = R*pi/180."""

import math
from datetime import UTC, datetime, timedelta

import pytest
from mooring.missions.geo import (
    EARTH_RADIUS_M,
    NM_M,
    bearing_deg,
    decimate_indices,
    haversine_m,
    interpolate,
    to_us,
)
from mooring.missions.locate import TrackIndex, locate

DEG_M = EARTH_RADIUS_M * math.pi / 180   # metres per degree on the equator / a meridian
T0 = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def at(s):
    return T0 + timedelta(seconds=s)


def index(points):
    """points: (seconds, lat, lon[, quality[, heading]])"""
    rows = [(to_us(at(p[0])), p[1], p[2], p[4] if len(p) > 4 else None, None, None, None,
             p[3] if len(p) > 3 else "good", "test") for p in points]
    return TrackIndex.from_rows(rows)


EQ = index([(0, 0, 0.00), (60, 0, 0.01), (180, 0, 0.03)])   # 60 s then 120 s legs along the equator


def test_haversine_and_bearing_hand_values():
    assert haversine_m(0, 0, 0, 1) == pytest.approx(DEG_M, rel=1e-12)
    assert haversine_m(0, 0, 1, 0) == pytest.approx(DEG_M, rel=1e-12)
    assert bearing_deg(0, 0, 0, 1) == pytest.approx(90)
    assert bearing_deg(0, 0, -1, 0) == pytest.approx(180)
    assert bearing_deg(0, 1, 0, 0) == pytest.approx(270)


def test_exact_fix_within_half_second():
    for dt, expect in ((0.0, 0.01 * 0 + 0.01), (0.4, 0.01), (-0.5, 0.01)):
        loc = locate(EQ, at(60 + dt), 300)
        assert loc.method == "exact_fix" and loc.lon == 0.01 and loc.lat == 0
        assert loc.distance_along_track_nm == pytest.approx(0.01 * DEG_M / NM_M)
        assert loc.validity.state == "valid" and loc.validity.reasons == []
    assert locate(EQ, at(60.6), 300).method == "interpolated"


def test_interpolated_midpoint_distance_speed_heading():
    loc = locate(EQ, at(30), 300)
    assert loc.method == "interpolated"
    assert (loc.lat, loc.lon) == (pytest.approx(0, abs=1e-12), pytest.approx(0.005, abs=1e-12))
    assert loc.distance_along_track_nm == pytest.approx(0.005 * DEG_M / NM_M, rel=1e-9)
    assert loc.sog_kt == pytest.approx(0.01 * DEG_M / 60 / (NM_M / 3600), rel=1e-9)
    assert loc.heading_true_deg == pytest.approx(90)
    assert (loc.fix_before_utc, loc.fix_after_utc, loc.gap_s) == (at(0), at(60), 60)
    assert loc.validity.state == "limited" and [r.code for r in loc.validity.reasons] == ["INTERPOLATED_POSITION"]
    q = locate(EQ, at(90), 300)   # a quarter of the way along the 120 s leg
    assert q.lon == pytest.approx(0.01 + 0.005, abs=1e-12)
    assert q.distance_along_track_nm == pytest.approx(0.015 * DEG_M / NM_M, rel=1e-9)


def test_interpolation_uses_recorded_headings_when_both_present_else_segment_bearing():
    ix = index([(0, 0, 0.0, "good", 350.0), (60, 0, 0.01, "good", 10.0)])
    assert locate(ix, at(30), 300).heading_true_deg == pytest.approx(0.0, abs=1e-9)   # shorter way round 350 -> 10
    stationary = index([(0, 5, 5), (60, 5, 5)])
    assert locate(stationary, at(30), 300).heading_true_deg is None                   # no motion: heading not invented


def test_gap_longer_than_limit_has_no_position():
    loc = locate(EQ, at(120), 100)   # surrounding fixes are 120 s apart, limit 100
    assert loc.method == "gap" and loc.lat is None and loc.lon is None and loc.gap_s == 120
    assert loc.distance_along_track_nm is None
    assert loc.validity.state == "limited" and loc.validity.reasons[0].code == "POSITION_NOT_ESTABLISHED"
    assert locate(EQ, at(120), 120).method == "interpolated"      # boundary: gap == limit is allowed
    assert locate(EQ, at(60.0), 100).method == "exact_fix"        # an exact fix wins even beside a gap


def test_before_and_after_track_are_never_extrapolated():
    b, a = locate(EQ, at(-10), 300), locate(EQ, at(181), 300)
    assert (b.method, b.lat, b.lon) == ("before_track", None, None)
    assert (a.method, a.lat, a.lon) == ("after_track", None, None)
    assert b.fix_after_utc == at(0) and a.fix_before_utc == at(180)
    assert b.validity.reasons[0].code == "POSITION_NOT_ESTABLISHED"


def test_no_track_and_no_time():
    assert locate(TrackIndex(), at(0), 300).method == "no_track"
    n = locate(EQ, None, 300)
    assert n.method == "no_time" and n.lat is None and n.validity.state == "limited"


def test_exact_fix_quality_and_time_caveats_limit_validity():
    ix = index([(0, 0, 0, "unknown"), (60, 0, 0.01, "degraded"), (120, 0, 0.02, "good")])
    assert [locate(ix, at(s), 300).validity.state for s in (0, 60, 120)] == ["limited", "limited", "valid"]
    assert locate(ix, at(0), 300).validity.reasons[0].code == "FIX_QUALITY_NOT_GOOD"
    loc = locate(ix, at(120), 300, time_caveats=["CAMERA_CLOCK_OFFSET_APPLIED"], component="img_1")
    assert loc.validity.state == "limited" and loc.validity.reasons[0].code == "CAMERA_CLOCK_OFFSET_APPLIED"
    assert loc.validity.reasons[0].affected_components == ["img_1"]


def test_stated_position_discrepancy_hand_computed():
    stated = (0.0, 0.0105)    # 0.0005 deg east of the interpolated midpoint
    loc = locate(EQ, at(30), 300, stated=(0.0, 0.0055), stated_source="exif")
    assert loc.discrepancy_m == pytest.approx(0.0005 * DEG_M, rel=1e-6)
    assert (loc.stated_lat, loc.stated_lon, loc.stated_source) == (0.0, 0.0055, "exif")
    assert "STATED_POSITION_DISAGREES" not in [r.code for r in loc.validity.reasons]
    far = locate(EQ, at(30), 300, stated=(0.0, 0.005 + 600 / DEG_M), stated_source="report")
    assert far.discrepancy_m == pytest.approx(600, rel=1e-6)
    assert [r.code for r in far.validity.reasons] == ["INTERPOLATED_POSITION", "STATED_POSITION_DISAGREES"]
    ok = locate(EQ, at(30), 300, stated=(0.0, 0.005 + 499 / DEG_M), stated_source="report")
    assert "STATED_POSITION_DISAGREES" not in [r.code for r in ok.validity.reasons]
    # stated position is reported even when the track cannot place the event, with no discrepancy
    out = locate(EQ, at(-5), 300, stated=stated, stated_source="exif")
    assert (out.stated_lat, out.stated_lon, out.discrepancy_m, out.lat) == (0.0, 0.0105, None, None)


def test_antimeridian_interpolation():
    lat, lon = interpolate(0, 179.99, 0, -179.99, 0.5)
    assert lat == pytest.approx(0, abs=1e-12) and abs(lon) == pytest.approx(180, abs=1e-9)
    ix = index([(0, 0, 179.99), (60, 0, -179.99)])
    loc = locate(ix, at(15), 300)       # a quarter of the way: 179.995
    assert loc.lon == pytest.approx(179.995, abs=1e-9)
    assert loc.distance_along_track_nm == pytest.approx(0.005 * DEG_M / NM_M, rel=1e-9)
    assert loc.heading_true_deg == pytest.approx(90)


def test_interpolate_polar_and_antipodal_guard():
    lat, lon = interpolate(89.0, 0.0, 89.0, 180.0, 0.5)      # over the pole
    assert lat == pytest.approx(90.0, abs=1e-9)
    with pytest.raises(ValueError):
        interpolate(0, 0, 0, 180, 0.5)
    ix = index([(0, 0, 0), (60, 0, 180)])
    assert locate(ix, at(30), 3600).method == "gap"           # explicit handling: no invented path


def test_heading_never_reaches_360():
    assert 0 <= bearing_deg(0, 0, -1e-15, 0) < 360


# ---- decimation

def zigzag(n):
    return [(i, 0.001 * i if i % 2 else 0.0) for i in range(n)]  # (lat-like x index, lon)


def test_decimation_keeps_endpoints_gap_boundaries_and_budget():
    n = 1000
    lat = [1e-9 * i * i for i in range(n)]   # curved, so no exactly collinear stretch
    lon = [0.0001 * i for i in range(n)]
    for cap in (2, 3, 10, 100, 999):
        keep = decimate_indices(lat, lon, cap)
        assert len(keep) == cap and keep[0] == 0 and keep[-1] == n - 1 and keep == sorted(set(keep))
    assert decimate_indices(lat, lon, n) == list(range(n))
    keep = decimate_indices(lat, lon, 20, forced=[400, 401, 700, 701])
    assert {0, 400, 401, 700, 701, n - 1} <= set(keep) and len(keep) == 20
    tight = decimate_indices(lat, lon, 4, forced=[400, 401, 700, 701])   # budget wins; priority order kept
    assert len(tight) == 4 and tight == [0, 400, 401, n - 1]


def test_decimation_is_shape_preserving_on_an_l_shape():
    # 100 points east, then 100 north: the corner must survive any budget >= 3
    lat = [0.0] * 100 + [0.0001 * i for i in range(1, 101)]
    lon = [0.0001 * i for i in range(100)] + [0.0099] * 100
    keep = decimate_indices(lat, lon, 3)
    assert keep == [0, 99, 199]


def test_decimation_deterministic_and_antimeridian_safe():
    lon = [((179.99 + 0.0001 * i + 180) % 360) - 180 for i in range(200)]
    lat = [0.0] * 200
    assert decimate_indices(lat, lon, 5) == decimate_indices(lat, lon, 5)
    assert decimate_indices(lat, lon, 5)[0] == 0
