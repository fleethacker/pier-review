"""Locate an event at time t on a recorded track. Shared by images and reports.

Methods (never extrapolates, never invents a position):
  exact_fix     t within EXACT_TOL_S of a fix that lies inside the recorded span: that fix's position. Outside the
                span only EDGE_TOL_S (1 ms, clock rounding) counts as the fix itself.
  interpolated  t between fixes whose spacing is <= max_interp_gap_s: great-circle interpolation, linear in time.
  gap           t between fixes spaced further apart than max_interp_gap_s: position null, gap_s reported.
  before_track / after_track   outside the recorded span: position null.
  no_track      no fixes. no_time  the event has no timestamp.
Validity is `valid` only for an exact fix of quality `good` with no other caveat; everything else is `limited`
(an interpolation is `limited` with INTERPOLATED_POSITION, plus FIX_QUALITY_NOT_GOOD if either bracketing fix is not good).
"""

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime

from mooring.core.schemas.common import Validity, ValidityReason
from mooring.core.schemas.missions import LocatedAt, TrackFix

from .geo import (
    KT_MS,
    NM_M,
    bearing_deg,
    from_us,
    haversine_m,
    interpolate,
    interpolate_angle,
    to_us,
)

EXACT_TOL_S = 0.5
EDGE_TOL_S = 0.001
DISAGREE_M = 500.0

CAVEAT_TEXT = {
    "CAMERA_CLOCK_OFFSET_APPLIED": "The event time includes a caller-supplied camera clock offset.",
    "EXIF_UTC_OFFSET_ASSUMED": "The event time used a caller-supplied UTC offset because EXIF had none.",
}


@dataclass
class TrackIndex:
    t: list[int] = field(default_factory=list)       # microseconds since epoch, strictly increasing
    lat: list[float] = field(default_factory=list)
    lon: list[float] = field(default_factory=list)
    heading: list[float | None] = field(default_factory=list)
    cog: list[float | None] = field(default_factory=list)
    sog: list[float | None] = field(default_factory=list)
    hdop: list[float | None] = field(default_factory=list)
    quality: list[str] = field(default_factory=list)
    source: list[str | None] = field(default_factory=list)
    cum_m: list[float] = field(default_factory=list)

    def __len__(self):
        return len(self.t)

    @classmethod
    def from_rows(cls, rows) -> "TrackIndex":
        """rows: (t_us, lat, lon, heading, cog, sog, hdop, quality, source) in increasing t_us."""
        ix = cls()
        for r in rows:
            ix.t.append(r[0]); ix.lat.append(r[1]); ix.lon.append(r[2]); ix.heading.append(r[3])
            ix.cog.append(r[4]); ix.sog.append(r[5]); ix.hdop.append(r[6]); ix.quality.append(r[7]); ix.source.append(r[8])
            ix.cum_m.append(0.0 if len(ix.t) == 1 else ix.cum_m[-1] + haversine_m(ix.lat[-2], ix.lon[-2], r[1], r[2]))
        return ix

    def fix(self, i: int) -> TrackFix:
        return TrackFix(t_utc=from_us(self.t[i]), lat=self.lat[i], lon=self.lon[i], heading_true_deg=self.heading[i],
                        cog_true_deg=self.cog[i], sog_kt=self.sog[i], hdop=self.hdop[i], quality=self.quality[i],
                        source=self.source[i])

    def gaps(self, limit_s: float) -> list[int]:
        """Indices i where the span from fix i to fix i+1 exceeds limit_s."""
        lim = limit_s * 1e6
        return [i for i in range(len(self.t) - 1) if self.t[i + 1] - self.t[i] > lim]

    def max_gap_s(self) -> float:
        return max((b - a for a, b in zip(self.t, self.t[1:])), default=0) / 1e6


def _reason(code, message, comp=None):
    return ValidityReason(code=code, message=message, affected_components=[comp] if comp else [])


def _validity(reasons: list[ValidityReason]) -> Validity:
    return Validity(state="limited", reasons=reasons) if reasons else Validity(state="valid")


def _unknown_validity(code_msg: str, comp):
    return _validity([_reason("POSITION_NOT_ESTABLISHED", code_msg, comp)])


def locate(index: TrackIndex, t: datetime | None, max_interp_gap_s: float, *, stated: tuple[float, float] | None = None,
           stated_source: str | None = None, time_caveats: list[str] | tuple = (), component: str | None = None) -> LocatedAt:
    reasons = [_reason(c, CAVEAT_TEXT.get(c, c), component) for c in time_caveats]
    st = {}
    if stated is not None:
        st = dict(stated_lat=stated[0], stated_lon=stated[1], stated_source=stated_source)

    def none(method, why, **extra):
        return LocatedAt(method=method, **st, **extra,
                         validity=_validity([_reason("POSITION_NOT_ESTABLISHED", why, component), *reasons]))

    if t is None:
        return none("no_time", "The event has no timestamp, so it cannot be placed on the track.")
    n = len(index)
    if n == 0:
        return none("no_track", "The mission has no recorded track.")
    tu = to_us(t)
    i = bisect_left(index.t, tu)  # first fix with time >= t
    tol = EXACT_TOL_S * 1e6
    edge_tol = EDGE_TOL_S * 1e6

    def _near(j):
        if not 0 <= j < n:
            return False
        d = index.t[j] - tu
        if (d > 0 and j == 0) or (d < 0 and j == n - 1):  # before the first / after the last fix: no snapping
            return abs(d) <= edge_tol
        return abs(d) <= tol

    near = [j for j in (i - 1, i) if _near(j)]
    if near:
        j = min(near, key=lambda k: abs(index.t[k] - tu))
        lat, lon = index.lat[j], index.lon[j]
        # recorded values first; otherwise derived from the adjoining segment
        a, b = (j, j + 1) if j + 1 < n else (j - 1, j)
        seg = None
        if a >= 0 and b < n and index.t[b] > index.t[a]:
            seg = (haversine_m(index.lat[a], index.lon[a], index.lat[b], index.lon[b]), (index.t[b] - index.t[a]) / 1e6)
        hdg = index.heading[j]
        if hdg is None and seg and seg[0] >= 1.0:
            hdg = bearing_deg(index.lat[a], index.lon[a], index.lat[b], index.lon[b])
        sog = index.sog[j] if index.sog[j] is not None else (seg[0] / seg[1] / KT_MS if seg else None)
        if index.quality[j] != "good":
            reasons.insert(0, _reason("FIX_QUALITY_NOT_GOOD", f"The fix quality is '{index.quality[j]}' (HDOP > 2 or not recorded).", component))
        loc = dict(method="exact_fix", lat=lat, lon=lon, fix_before_utc=from_us(index.t[j]), fix_after_utc=from_us(index.t[j]),
                   distance_along_track_nm=index.cum_m[j] / NM_M, sog_kt=sog, heading_true_deg=hdg)
        return _finish(loc, st, reasons, component)
    if i == 0:
        return none("before_track", f"Event is {(index.t[0] - tu) / 1e6:.1f} s before the first fix; not extrapolated.",
                    fix_after_utc=from_us(index.t[0]))
    if i == n:
        return none("after_track", f"Event is {(tu - index.t[-1]) / 1e6:.1f} s after the last fix; not extrapolated.",
                    fix_before_utc=from_us(index.t[-1]))
    a, b = i - 1, i
    span = (index.t[b] - index.t[a]) / 1e6
    if span > max_interp_gap_s:
        return none("gap", f"The surrounding fixes are {span:.1f} s apart, more than max_interp_gap_s={max_interp_gap_s:g}.",
                    fix_before_utc=from_us(index.t[a]), fix_after_utc=from_us(index.t[b]), gap_s=span)
    f = (tu - index.t[a]) / (index.t[b] - index.t[a])
    dist = haversine_m(index.lat[a], index.lon[a], index.lat[b], index.lon[b])
    try:
        lat, lon = interpolate(index.lat[a], index.lon[a], index.lat[b], index.lon[b], f)
    except ValueError:
        return none("gap", "The surrounding fixes are antipodal; no unique path.",
                    fix_before_utc=from_us(index.t[a]), fix_after_utc=from_us(index.t[b]), gap_s=span)
    if index.heading[a] is not None and index.heading[b] is not None:
        hdg = interpolate_angle(index.heading[a], index.heading[b], f)
    elif dist >= 1.0:
        hdg = bearing_deg(index.lat[a], index.lon[a], index.lat[b], index.lon[b])
    else:
        hdg = None
    reasons.insert(0, _reason("INTERPOLATED_POSITION", f"Interpolated between fixes {span:.1f} s apart.", component))
    if index.quality[a] != "good" or index.quality[b] != "good":
        reasons.insert(1, _reason("FIX_QUALITY_NOT_GOOD", f"A bracketing fix is not of good quality (before: '{index.quality[a]}', "
                                  f"after: '{index.quality[b]}'; HDOP > 2 or not recorded).", component))
    loc = dict(method="interpolated", lat=lat, lon=lon, fix_before_utc=from_us(index.t[a]), fix_after_utc=from_us(index.t[b]),
               gap_s=span, distance_along_track_nm=(index.cum_m[a] + f * dist) / NM_M, sog_kt=dist / span / KT_MS,
               heading_true_deg=hdg)
    return _finish(loc, st, reasons, component)


def _finish(loc, st, reasons, component):
    disc = haversine_m(loc["lat"], loc["lon"], st["stated_lat"], st["stated_lon"]) if st else None
    if disc is not None and disc > DISAGREE_M:
        reasons.append(_reason("STATED_POSITION_DISAGREES",
                               f"The {st['stated_source']} position is {disc:.0f} m from the track position (limit {DISAGREE_M:.0f} m).",
                               component))
    return LocatedAt(**loc, **st, discrepancy_m=disc, validity=_validity(reasons))
