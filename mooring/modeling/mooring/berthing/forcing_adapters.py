"""Adapter: D2 ComposedForecast -> S2 replay ForcingSpec. Pure, no I/O, no invention.

Sampling choices (all documented because ForcingSeries is piecewise-linear only):
* current / water level points are instantaneous predictions at ``valid_at_utc``; they are interpolated linearly
  (angles along the shortest arc) between supplied points.
* wind points are *intervals* ``[valid_from_utc, valid_to_utc)``. Each interval value is anchored at the interval
  MIDPOINT and interpolated linearly between midpoints; the first/last interval value is held out to its own outer
  bound only (never beyond). Contiguous intervals are required across the replay window: a gap raises ValueError
  rather than being bridged.
* a component that is unavailable, quality poor/suspect, has no points, or is ``mock`` (unless ``allow_mock``)
  contributes NO channel. The simulator then reports the channel unavailable and the physics uses the scenario base
  value; it is never filled with zero or substituted from another source.
* wind gust missing in any wind point => the gust channel is omitted (not guessed from sustained speed).
* the replay window is the intersection of the contributing components' coverage; the anchor must lie inside it.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from mooring.core.schemas import ComposedForecast, ForcingSample, ForcingSpec

MAX_LABEL = 200
MAX_SAMPLES = 2000
_ANGLE = ("wind_from_true_deg", "current_set_true_deg")


@dataclass
class ForcingAdapterReport:
    manifest_revision: str
    forecast_status: str
    anchor_utc: datetime
    window_end_utc: datetime
    channels: list[str] = field(default_factory=list)
    used: dict = field(default_factory=dict)       # component -> {state, basis, source, content_sha256}
    skipped: dict = field(default_factory=dict)    # component -> reason (missing, never zero)
    notes: list[str] = field(default_factory=list)


def _utc(v: datetime, name: str) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return v.astimezone(UTC)


def _lerp(a, b, f): return a + (b - a) * f


def _lerp_angle(a, b, f): return (a + ((b - a + 180) % 360 - 180) * f) % 360


def _interp(knots, t):
    """knots: [(datetime, {name: value})] sorted; t inside [first, last]."""
    lo, hi = 0, len(knots) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if knots[mid][0] <= t else (lo, mid)
    (t0, a), (t1, b) = knots[lo], knots[hi]
    f = 0.0 if t1 == t0 else min(1.0, max(0.0, (t - t0).total_seconds() / (t1 - t0).total_seconds()))
    return {n: (_lerp_angle(a[n], b[n], f) if n in _ANGLE else _lerp(a[n], b[n], f)) for n in a}


def composed_forecast_to_forcing_detail(forecast: ComposedForecast, anchor_utc: datetime, *, allow_mock: bool = False,
                                        horizon_s: float | None = None, max_gap_s: float = 10800.0):
    """Returns (ForcingSpec, ForcingAdapterReport)."""
    anchor = _utc(anchor_utc, "anchor_utc")
    man = forecast.manifest
    report = ForcingAdapterReport(man.revision, man.status, anchor, anchor)
    knots, coverage, gaps = {}, {}, {}
    for item in man.components:
        av, comp = item.availability, item.availability.component
        if av.state == "unavailable" or not item.points:
            report.skipped[comp] = f"unavailable: {av.reason or 'no points'}"
        elif av.state == "mock" and not allow_mock:
            report.skipped[comp] = "mock-labelled component not used (allow_mock=False)"
        elif av.quality in ("poor", "suspect"):
            report.skipped[comp] = f"source quality {av.quality}"
        else:
            report.used[comp] = {"state": av.state, "basis": av.basis, "source": av.source, "content_sha256": item.content_sha256}
            if comp == "wind":
                pts = [(p.valid_from_utc.astimezone(UTC), p.valid_to_utc.astimezone(UTC), p) for p in item.points]
                gaps[comp] = [(a[1], b[0]) for a, b in zip(pts, pts[1:]) if b[0] > a[1]]
                gust_ok = all(p.wind_gust_kt is not None for _, _, p in pts)
                if not gust_ok:
                    report.notes.append("wind gust missing in a point; gust channel omitted (not guessed).")

                def vals(p, gust_ok=gust_ok):
                    return {"wind_speed_kt": p.wind_speed_kt, "wind_from_true_deg": p.wind_from_true_deg,
                            **({"wind_gust_kt": p.wind_gust_kt} if gust_ok else {})}
                k = [(pts[0][0], vals(pts[0][2]))] + [(a + (b - a) / 2, vals(p)) for a, b, p in pts] + [(pts[-1][1], vals(pts[-1][2]))]
                knots[comp], coverage[comp] = k, (pts[0][0], pts[-1][1])
            else:
                k = []
                for p in item.points:
                    v = ({"water_level_mllw_ft": p.water_level_mllw_ft} if comp == "water_level" else
                         {"current_speed_kt": p.current_speed_kt, "current_set_true_deg": p.current_set_true_deg})
                    k.append((p.valid_at_utc.astimezone(UTC), v))
                gaps[comp] = [(a[0], b[0]) for a, b in zip(k, k[1:]) if (b[0] - a[0]).total_seconds() > max_gap_s]
                knots[comp], coverage[comp] = k, (k[0][0], k[-1][0])
    if not knots:
        raise ValueError(f"forecast {man.revision} has no usable component (status {man.status}); skipped: {report.skipped}")
    start, end = max(c[0] for c in coverage.values()), min(c[1] for c in coverage.values())
    if horizon_s is not None:
        end = min(end, anchor + timedelta(seconds=horizon_s))
    if not (start <= anchor < end):
        raise ValueError(f"anchor {anchor.isoformat()} is outside forecast coverage {start.isoformat()}..{end.isoformat()} "
                         f"(intersection of {sorted(knots)}); refusing to extrapolate")
    for comp, gl in gaps.items():
        if any(g0 < end and g1 > anchor for g0, g1 in gl):
            raise ValueError(f"{comp} forecast has a gap inside the replay window; refusing to bridge it")
    times = {anchor, end}
    for k in knots.values():
        times.update(t for t, _ in k if anchor < t < end)
    times = sorted(times)
    if len(times) > MAX_SAMPLES:
        raise ValueError(f"{len(times)} replay samples exceed {MAX_SAMPLES}; pass a shorter horizon_s")
    samples = []
    for t in times:
        row = {"t_s": (t - anchor).total_seconds()}
        for k in knots.values():
            row.update(_interp(k, t))
        samples.append(ForcingSample(**row))
    report.window_end_utc = end
    report.channels = sorted(n for n in ForcingSample.model_fields if n != "t_s" and getattr(samples[0], n) is not None)
    states = " ".join(f"{c}:{v['state']}" for c, v in report.used.items())
    label = f"REPLAY (not live) composed-forecast {man.revision} @{anchor:%Y-%m-%dT%H:%M:%SZ} used[{states}]"
    if report.skipped:
        label += " missing[" + ",".join(report.skipped) + "]"
    spec = ForcingSpec(kind="replay", label=label[:MAX_LABEL], samples=samples, on_uncovered="stop")
    return spec, report


def composed_forecast_to_forcing(forecast: ComposedForecast, anchor_utc: datetime, **kw) -> ForcingSpec:
    """Replay ForcingSpec with sim t=0 at ``anchor_utc``. ValueError if the anchor is not covered."""
    return composed_forecast_to_forcing_detail(forecast, anchor_utc, **kw)[0]
