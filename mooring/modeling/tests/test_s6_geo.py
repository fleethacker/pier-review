"""S6 geometry benchmark: local tangent plane vs lat/lon."""

import math
import random

from mooring.transit.geo import LocalPlane, enu_exact


def test_round_trip_is_exact_to_float_precision():
    rnd = random.Random(1)
    for lat0, lon0 in ((36.95, -76.3), (21.3, -157.9), (-33.9, 151.2), (64.0, -22.0)):
        p = LocalPlane(lat0, lon0)
        for _ in range(200):
            e, n = rnd.uniform(-40000, 40000), rnd.uniform(-40000, 40000)
            lat, lon = p.to_geo(e, n)
            e2, n2 = p.to_local(lat, lon)
            assert abs(e - e2) < 1e-6 and abs(n - n2) < 1e-6
            la2, lo2 = p.to_geo(e2, n2)
            assert abs(lat - la2) < 1e-11 and abs(lon - lo2) < 1e-11


def test_origin_and_axes():
    p = LocalPlane(36.95, -76.3)
    assert p.to_local(36.95, -76.3) == (0.0, 0.0)
    e, n = p.to_local(36.96, -76.3)
    assert e == 0.0 and 1100 < n < 1120          # 0.01 deg of latitude is about 1.1 km north
    e, n = p.to_local(36.95, -76.29)
    assert n == 0.0 and 880 < e < 900            # 0.01 deg of longitude at 37 N is about 0.89 km east
    assert p.m_radius < p.n_radius               # meridional radius smaller than prime vertical


def test_error_bound_against_exact_enu(capsys):
    """Measured error of the flat-earth plane against the exact ECEF East-North-Up conversion, at 37 N."""
    p = LocalPlane(36.95, -76.3)
    rows = []
    for rng in (5000.0, 10000.0, 20000.0, 40000.0):
        worst = 0.0
        for ang in range(0, 360, 15):
            e, n = rng * math.sin(math.radians(ang)), rng * math.cos(math.radians(ang))
            lat, lon = p.to_geo(e, n)
            ee, en = enu_exact(36.95, -76.3, lat, lon)
            worst = max(worst, math.hypot(ee - e, en - n))
        rows.append((rng, worst))
    print("S6 geo error vs exact ENU (range m, worst error m):", [(r, round(w, 2)) for r, w in rows])
    errs = dict(rows)
    assert errs[5000.0] < 3.0 and errs[10000.0] < 10.0     # worst case over all bearings; ~0.07 % at 10 km
    assert errs[40000.0] < 150.0                           # ~0.27 % at the documented 40 km limit
    assert 10 < errs[40000.0] / errs[10000.0] < 20         # quadratic growth, as the neglected cos(lat) variation predicts
