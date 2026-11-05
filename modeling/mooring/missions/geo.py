"""Spherical geometry for track work. WGS84 positions on a sphere of the IUGG mean radius.

The mean-radius sphere is within about 0.3 % of the ellipsoid for distances, which is far inside GPS and clock
uncertainty for the intervals handled here. Interpolation is great-circle, done on unit vectors, so it is correct
across the antimeridian and the poles.
"""

import heapq
import math
from datetime import UTC, datetime, timedelta

import numpy as np

EARTH_RADIUS_M = 6_371_008.8  # IUGG mean radius R1
NM_M = 1852.0
KT_MS = NM_M / 3600.0
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_US = timedelta(microseconds=1)


def to_us(dt: datetime) -> int:
    """Aware datetime -> integer microseconds since the Unix epoch (exact)."""
    return (dt.astimezone(UTC) - EPOCH) // _US


def from_us(us: int) -> datetime:
    return EPOCH + timedelta(microseconds=us)


def _wrap(deg: float) -> float:
    r = deg % 360.0
    return 0.0 if r >= 360.0 else r


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees true in [0, 360)."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return _wrap(math.degrees(math.atan2(y, x)))


def _vec(lat, lon):
    p, l = math.radians(lat), math.radians(lon)
    return (math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p))


def interpolate(lat1, lon1, lat2, lon2, f: float) -> tuple[float, float]:
    """Point at fraction f (0..1) of the great-circle arc from point 1 to point 2."""
    if f <= 0:
        return lat1, lon1
    if f >= 1:
        return lat2, lon2
    a, b = _vec(lat1, lon1), _vec(lat2, lon2)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
    omega = math.acos(dot)
    if omega < 1e-12:
        return lat1, lon1
    if math.pi - omega < 1e-9:
        # Antipodal: the great circle is undefined, so refuse rather than invent a path.
        raise ValueError("cannot interpolate between antipodal points")
    s = math.sin(omega)
    ka, kb = math.sin((1 - f) * omega) / s, math.sin(f * omega) / s
    x, y, z = (ka * a[i] + kb * b[i] for i in range(3))
    lat = math.degrees(math.atan2(z, math.hypot(x, y)))
    lon = math.degrees(math.atan2(y, x))
    return lat, lon


def interpolate_angle(a_deg: float, b_deg: float, f: float) -> float:
    """Circular interpolation along the shorter way round."""
    d = ((b_deg - a_deg + 180.0) % 360.0) - 180.0
    return _wrap(a_deg + f * d)


def decimate_indices(lat: list[float], lon: list[float], max_points: int, forced: list[int] | None = None) -> list[int]:
    """Indices of a shape-preserving subset: Douglas-Peucker in a local equirectangular plane, run as a
    best-first split so the result has at most max_points points (fewer only if the rest is exactly collinear).

    First and last are always kept. `forced` indices (gap endpoints) are kept in the given priority order while the
    budget allows; max_points always wins.
    """
    n = len(lat)
    if n <= max_points:
        return list(range(n))
    if max_points < 2:
        raise ValueError("max_points must be at least 2")
    extra = [i for i in dict.fromkeys(forced or []) if 0 < i < n - 1]
    keep = sorted({0, n - 1, *extra[: max(0, max_points - 2)]})
    la, lo = np.asarray(lat, float), np.asarray(lon, float)
    lon0 = lo[0]
    x = ((lo - lon0 + 180.0) % 360.0 - 180.0) * math.cos(math.radians(float(la.mean()))) * (math.pi / 180) * EARTH_RADIUS_M
    y = la * (math.pi / 180) * EARTH_RADIUS_M

    def farthest(i, j):
        if j - i < 2:
            return 0.0, -1
        px, py = x[i + 1:j], y[i + 1:j]
        dx, dy = x[j] - x[i], y[j] - y[i]
        L2 = dx * dx + dy * dy
        if L2 == 0:
            d = np.hypot(px - x[i], py - y[i])
        else:
            t = np.clip(((px - x[i]) * dx + (py - y[i]) * dy) / L2, 0.0, 1.0)
            d = np.hypot(px - (x[i] + t * dx), py - (y[i] + t * dy))
        k = int(np.argmax(d))
        return float(d[k]), i + 1 + k

    heap = []
    for i, j in zip(keep, keep[1:]):
        d, k = farthest(i, j)
        if k >= 0:
            heapq.heappush(heap, (-d, i, j, k))
    kept = set(keep)
    while heap and len(kept) < max_points:
        negd, i, j, k = heapq.heappop(heap)
        if negd == 0.0:
            break
        kept.add(k)
        for a, b in ((i, k), (k, j)):
            d, m = farthest(a, b)
            if m >= 0:
                heapq.heappush(heap, (-d, a, b, m))
    return sorted(kept)
