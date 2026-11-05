"""Local tangent plane tied to lat/lon (S6).

East/north metres from an origin, using the WGS84 meridional radius M and prime-vertical radius N evaluated at the
ORIGIN latitude:

    east  = (lon - lon0) * N cos(lat0)         north = (lat - lat0) * M          (angles in radians)

This is the standard "flat earth" local approximation (e.g. Fossen, Handbook of Marine Craft Hydrodynamics, 2011,
sec. 2.2; NIMA TR8350.2 for the ellipsoid constants). It is first-order exact at the origin. The neglected terms
are the change of M, N and cos(lat) away from the origin latitude and the curvature of the meridians. The error
bound over a given range is measured, not asserted: `tests/test_s6_geo.py` compares against an exact ECEF-based
East-North-Up conversion. Worst case over all bearings at 37 N: about 1.7 m at 5 km, 6.8 m at 10 km, 27 m at 20 km
and 108 m at 40 km (grows with the square of range, ~0.27 % at 40 km; the dominant term is the variation of cos(lat)
with the north offset). It is a consistent plane in both directions (round trip exact), so simulated distances are
off by at most that fraction relative to geodesic distances. Beyond 40 km S6 adds a validity reason.
"""

from __future__ import annotations

import math

WGS84_A = 6_378_137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)
FT_TO_M = 0.3048
M_PER_NM = 1852.0
RANGE_LIMIT_M = 40_000.0


class LocalPlane:
    def __init__(self, lat0_deg: float, lon0_deg: float):
        self.lat0, self.lon0 = lat0_deg, lon0_deg
        phi = math.radians(lat0_deg)
        s2 = math.sin(phi) ** 2
        w = math.sqrt(1 - WGS84_E2 * s2)
        self.n_radius = WGS84_A / w                                   # prime vertical radius
        self.m_radius = WGS84_A * (1 - WGS84_E2) / w ** 3             # meridional radius
        self.east_per_deg = math.radians(1) * self.n_radius * math.cos(phi)
        self.north_per_deg = math.radians(1) * self.m_radius

    def to_local(self, lat: float, lon: float) -> tuple[float, float]:
        d_lon = (lon - self.lon0 + 180.0) % 360.0 - 180.0
        return d_lon * self.east_per_deg, (lat - self.lat0) * self.north_per_deg

    def to_geo(self, east_m: float, north_m: float) -> tuple[float, float]:
        lon = self.lon0 + east_m / self.east_per_deg
        return self.lat0 + north_m / self.north_per_deg, (lon + 180.0) % 360.0 - 180.0


def wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def norm360(deg: float) -> float:
    """Wrap to [0, 360); guards the float case where a tiny negative angle % 360 rounds up to exactly 360."""
    v = deg % 360.0
    return 0.0 if v >= 360.0 else v


def bearing_deg(de: float, dn: float) -> float:
    """True bearing (clockwise from north, [0,360)) of an east/north vector."""
    return norm360(math.degrees(math.atan2(de, dn)))


def enu_exact(lat0, lon0, lat, lon) -> tuple[float, float]:
    """Exact WGS84 East/North of a point in the tangent plane at (lat0, lon0) via ECEF; benchmark reference."""
    def ecef(la, lo):
        p, l = math.radians(la), math.radians(lo)
        n = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(p) ** 2)
        return (n * math.cos(p) * math.cos(l), n * math.cos(p) * math.sin(l), n * (1 - WGS84_E2) * math.sin(p))
    a, b = ecef(lat0, lon0), ecef(lat, lon)
    d = [b[i] - a[i] for i in range(3)]
    p0, l0 = math.radians(lat0), math.radians(lon0)
    east = -math.sin(l0) * d[0] + math.cos(l0) * d[1]
    north = -math.sin(p0) * math.cos(l0) * d[0] - math.sin(p0) * math.sin(l0) * d[1] + math.cos(p0) * d[2]
    return east, north
