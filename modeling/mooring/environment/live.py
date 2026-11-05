"""Live (CO-OPS) environment service behind the stable `mooring.environment` interface (S04b).

Selected with MOORING_ENV_SOURCE=coops (default `mock`, so CI and demos stay offline). In this mode:
* `now` returns the latest joined observation from the berth's three stations, or raises `ProviderError`; it never falls
  back to synthetic data.
* `history` joins the same three products over a window (at most 31 days per call).
* `forecast` raises: no forecast provider is enabled (S04c); unavailable components stay unavailable.
The fetcher and clock are injectable for deterministic tests.
"""

from datetime import UTC, datetime, timedelta

from mooring import refdata
from mooring.core.schemas import HistorySeries
from mooring.core.envelopes import utcnow

from . import coops
from .replay import ReplaySource, Unavailable

DEFAULT_BIN = 4          # cb0402 real-time bin, about 20.6 ft below the surface (verified 4 Nov 2026)
LOOKBACK = timedelta(hours=3)

_fetcher: coops.Fetcher | None = None
_clock = utcnow


def configure(fetcher: coops.Fetcher | None = None, clock=None) -> None:
    global _fetcher, _clock
    _fetcher = fetcher
    _clock = clock or utcnow


def fetcher() -> coops.Fetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = coops.Fetcher()
    return _fetcher


def _stations(berth_id: str):
    s = refdata.berth(berth_id).env_station_ids
    return s.wind, s.water_level, s.current


def _source(berth_id: str, begin: datetime, end: datetime):
    wind, level, current = _stations(berth_id)
    recs, notes, stale = coops.Coops(fetcher()).window(wind, level, current, begin, end, bin=DEFAULT_BIN, bin_depth_ft=20.6 if current == "cb0402" else None)
    return ReplaySource(recs, source_kind="live", max_gap_s=900, stale_after_s=1800, station=wind), notes, stale


def latest(berth_id: str, heading_true_deg: float | None = None):
    from mooring.environment import with_relative
    end = _clock()
    src, notes, stale = _source(berth_id, end - LOOKBACK, end)
    cov = src.coverage
    if cov is None:
        raise coops.ProviderError("no_data", "CO-OPS returned no usable joined observations in the last 3 hours" + (f" ({notes[0]})" if notes else ""))
    snap = src.at(cov[1], now=end)
    if isinstance(snap, Unavailable):
        raise coops.ProviderError("stale", snap.reason)
    if stale:
        snap = snap.model_copy(update={"metadata": snap.metadata.model_copy(update={"quality": "suspect"})})   # served from a stale cache
    return with_relative(snap, heading_true_deg)


def at(berth_id: str, when: datetime, heading_true_deg: float | None = None):
    """Historical provider snapshot for replay; never substitute synthetic data."""
    from mooring.environment import with_relative

    if when.tzinfo is None or when.utcoffset() is None:
        raise coops.ProviderError("malformed", "Replay time must include a timezone offset")
    when = when.astimezone(UTC)
    src, notes, stale = _source(berth_id, when - timedelta(minutes=12), when + timedelta(minutes=12))
    snap = src.at(when, now=when)
    if isinstance(snap, Unavailable):
        detail = f" ({notes[0]})" if notes else ""
        raise coops.ProviderError("no_data", snap.reason + detail)
    if stale:
        snap = snap.model_copy(update={"metadata": snap.metadata.model_copy(update={"quality": "suspect"})})
    return with_relative(snap.model_copy(update={"source": "replay"}), heading_true_deg)


def history(station_id: str, start: datetime, end: datetime, step_min: int = 6) -> HistorySeries:
    berth = next((b for b in refdata.berths() if b.env_station_ids.wind == station_id), None)
    if berth is None:
        raise refdata.InvalidReference(f"station '{station_id}' is not the wind station of any configured berth")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    src, notes, _ = _source(berth.berth_id, start, end)
    series = []
    for rec in src.records:
        snap = src.at(rec.t, now=rec.t)
        if not isinstance(snap, Unavailable):
            series.append(snap)
    return HistorySeries(station_id=station_id, start_utc=start, end_utc=end, series=series)
