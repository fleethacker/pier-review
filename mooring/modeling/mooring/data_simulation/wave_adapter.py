"""Adapter: D4 OffshoreWaveSeries -> S4 WaveSurrogateRequest. Offshore source, NOT berth forcing.

One representation only: total_sea (default) OR provider partitions (swell / wind_sea), never both. A reported total
accompanying partitions is passed only as ``reported_total_hs_ft`` (consistency check, never added). Spectrum-only
points are NotImplemented => unavailable with a reason. The surrogate needs a PEAK period, so periods whose basis is
not peak/dominant/provider_partition are refused unless ``allow_period_proxy`` (then noted).
Unavailable anywhere => ``spectrum=None`` => the surrogate reports unavailable, never zero waves.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from mooring.core.schemas import OffshoreWaveSeries
from mooring.core.schemas.wave_surrogate import WaveSpectrumComponent, WaveSpectrumInput, WaveSurrogateRequest

OFFSHORE_LABEL = "offshore source, not berth forcing"
_PEAKISH = {"peak", "dominant"}


@dataclass
class WaveAdapterReport:
    available: bool
    label: str = OFFSHORE_LABEL
    reasons: list[str] = field(default_factory=list)
    point_valid_at_utc: datetime | None = None
    representation: str | None = None
    series_content_sha256: str | None = None
    notes: list[str] = field(default_factory=list)


def offshore_waves_to_surrogate(series: OffshoreWaveSeries, at_utc: datetime, seed: int, *,
                                representation: Literal["total", "partitions"] = "total",
                                max_hold_s: float = 3 * 3600.0, allow_period_proxy: bool = False, **request_kw):
    """Returns (WaveSurrogateRequest, WaveAdapterReport). Latest point at/before at_utc: no look-ahead, no interpolation."""
    rep = WaveAdapterReport(False, series_content_sha256=series.content_sha256)

    def unavailable(reason):
        rep.reasons.append(reason)
        return WaveSurrogateRequest(seed=seed, spectrum=None, **request_kw), rep

    if at_utc.tzinfo is None:
        raise ValueError("at_utc must be timezone-aware")
    at = at_utc.astimezone(UTC)
    av = series.availability
    if series.coverage == "unavailable" or av.state == "unavailable" or not series.points:
        return unavailable(f"offshore wave series unavailable: {av.reason or 'no points'}")
    if av.quality in ("poor", "suspect"):
        return unavailable(f"offshore wave source quality {av.quality}")
    prior = [p for p in series.points if p.valid_at_utc.astimezone(UTC) <= at]
    if not prior:
        return unavailable("no offshore wave point at or before the requested time (no look-ahead)")
    # Bulk summaries and spectra are separately timed points; use the latest point carrying the requested representation.
    has = (lambda p: p.total_sea is not None) if representation == "total" else (lambda p: bool(p.partitions))
    usable = [p for p in prior if has(p)]
    if not usable:
        if any(p.spectrum is not None for p in prior) and not any(p.total_sea or p.partitions for p in prior):
            return unavailable("spectrum-only series: NotImplemented (no spectrum-to-surrogate conversion)")
        return unavailable(f"no point with {representation} representation at or before the requested time")
    pt = usable[-1]
    rep.point_valid_at_utc = pt.valid_at_utc
    if at - pt.valid_at_utc.astimezone(UTC) > timedelta(seconds=max_hold_s):
        return unavailable(f"latest offshore wave point is older than the {max_hold_s:g} s hold limit")
    if representation == "total":
        bulk, reported = [pt.total_sea], None
    else:
        bulk, reported = list(pt.partitions), (pt.total_sea.significant_height_ft if pt.total_sea else None)
    comps = []
    for b in bulk:
        if b.component not in ("total_sea", "swell", "wind_sea"):
            return unavailable(f"provider partition {b.provider_partition_id!r} has no surrogate label")
        if b.period_s is None:
            return unavailable(f"{b.component}: no period; a peak period is required")
        if b.period_basis not in _PEAKISH | {"provider_partition"} and not allow_period_proxy:
            return unavailable(f"{b.component}: period basis {b.period_basis!r} is not a peak period; set allow_period_proxy to use it as one")
        if b.period_basis not in _PEAKISH:
            rep.notes.append(f"{b.component}: {b.period_basis} period used as the peak period (proxy)")
        comps.append(WaveSpectrumComponent(label=b.component, hs_ft=b.significant_height_ft, peak_period_s=b.period_s,
                                           from_true_deg=b.direction_from_true_deg))
    src = (f"{OFFSHORE_LABEL}: {series.provider} {series.station_id or series.model_id} {series.role} "
           f"point {pt.valid_at_utc.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ} sha256:{series.content_sha256}")
    spectrum = WaveSpectrumInput(kind="total" if representation == "total" else "partitions", components=comps,
                                 reported_total_hs_ft=reported, source=src)
    rep.available, rep.representation = True, representation
    return WaveSurrogateRequest(seed=seed, spectrum=spectrum, **request_kw), rep


def offshore_waves_to_surrogate_request(series: OffshoreWaveSeries, at_utc: datetime, seed: int, **kw) -> WaveSurrogateRequest:
    return offshore_waves_to_surrogate(series, at_utc, seed, **kw)[0]
