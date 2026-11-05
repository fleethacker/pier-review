"""Live (CO-OPS) environment service behind the stable `mooring.environment` interface (S04b).

Selected with MOORING_ENV_SOURCE=coops. In this mode:
* `now` returns the latest joined observation from the berth's three stations, or raises `ProviderError`; it never falls
  back to synthetic data.
* `history` joins the same three products over a window (at most 31 days per call).
* `forecast` raises: no forecast provider is enabled (S04c); unavailable components stay unavailable.
The fetcher and clock are injectable for deterministic tests.
"""

from datetime import UTC, datetime, timedelta

from mooring import refdata
from mooring.core.schemas import EnvironmentAvailability, EnvironmentComponentAvailability, HistorySeries
from mooring.core.envelopes import utcnow

from . import coops
from .replay import ReplaySource, Unavailable

DEFAULT_BIN = 4          # cb0402 real-time bin, about 20.6 ft below the surface (verified 4 Nov 2026)
LOOKBACK = timedelta(hours=3)
FRESH_AFTER = timedelta(minutes=30)

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
    eligible = [record.t for record in src.records if record.t <= end]
    if not eligible:
        raise coops.ProviderError("no_data", "CO-OPS returned no usable joined observations in the last 3 hours" + (f" ({notes[0]})" if notes else ""))
    if stale:
        raise coops.ProviderError("stale", "CO-OPS response came from stale cache")
    snap = src.at(max(eligible), now=end)
    if isinstance(snap, Unavailable):
        raise coops.ProviderError("stale", snap.reason)
    return with_relative(snap, heading_true_deg)


def _unavailable(component: str, source: str, station_id: str, reason: str, **kw):
    return EnvironmentComponentAvailability(
        component=component,
        state="unavailable",
        source=source,
        basis="observation",
        station_id=station_id,
        reason=reason,
        **kw,
    )


def component_availability(berth_id: str, checked_at: datetime | None = None) -> EnvironmentAvailability:
    """Fetch component statuses independently so one outage does not hide the others."""
    checked = (checked_at or _clock()).astimezone(UTC)
    wind_station, level_station, current_station = _stations(berth_id)
    begin = checked - LOOKBACK
    specs = (
        (
            "wind",
            wind_station,
            f"NOAA CO-OPS station {wind_station}",
            coops.request_params("wind", wind_station, begin, checked),
            coops.parse_wind,
            ("wind_speed_kt", "wind_gust_kt", "wind_from_true_deg"),
            {"limitations": ["wind averaging and gust duration are not documented by this response"]},
        ),
        (
            "current",
            current_station,
            f"NOAA CO-OPS station {current_station} bin {DEFAULT_BIN}",
            coops.request_params("currents", current_station, begin, checked, bin=DEFAULT_BIN),
            coops.parse_currents,
            ("current_speed_kt", "current_set_true_deg"),
            {
                "current_depth_ft": 20.6 if current_station == "cb0402" else None,
                "current_bin": str(DEFAULT_BIN),
                "limitations": [
                    "current direction is treated as toward and remains pending authoritative confirmation",
                    "requested current bin and depth are not silently substituted",
                ],
            },
        ),
        (
            "water_level",
            level_station,
            f"NOAA CO-OPS station {level_station}, MLLW",
            coops.request_params("water_level", level_station, begin, checked, datum="MLLW"),
            coops.parse_water_level,
            ("water_level_ft",),
            {"vertical_datum": "MLLW", "limitations": []},
        ),
    )
    rows: list[EnvironmentComponentAvailability] = []
    valid_times: dict[str, datetime] = {}
    for component, station, source, params, parser, required, extra in specs:
        try:
            fetched = fetcher().get(params)
            records = [
                item for item in parser(fetched.doc)
                if item["t"] <= checked
                and item.get("quality") != "poor"
                and all(item.get(field) is not None for field in required)
            ]
        except coops.ProviderError as exc:
            rows.append(_unavailable(component, source, station, f"provider {exc.kind}: {exc}", **extra))
            continue
        if not records:
            rows.append(_unavailable(component, source, station, "no usable observation in the lookback window", **extra))
            continue
        record = max(records, key=lambda item: item["t"])
        valid_at = record["t"]
        age_s = (checked - valid_at).total_seconds()
        retrieved = checked - timedelta(seconds=max(fetched.age_s, 0.0))
        common = dict(
            source=source,
            basis="observation",
            age_s=age_s,
            age_basis="valid_time",
            retrieved_at_utc=retrieved,
            valid_from_utc=valid_at,
            valid_to_utc=valid_at,
            quality=record.get("quality", "unknown"),
            station_id=station,
            **extra,
        )
        if fetched.stale:
            rows.append(EnvironmentComponentAvailability(
                component=component,
                state="unavailable",
                reason="provider response came from stale cache",
                **common,
            ))
        elif age_s > FRESH_AFTER.total_seconds():
            rows.append(EnvironmentComponentAvailability(
                component=component,
                state="unavailable",
                reason=f"latest observation is {age_s:.0f} s old; stale after {FRESH_AFTER.total_seconds():.0f} s",
                **common,
            ))
        else:
            rows.append(EnvironmentComponentAvailability(component=component, state="live", reason=None, **common))
            valid_times[component] = valid_at

    if len(valid_times) == 3:
        reference = valid_times["wind"]
        for index, row in enumerate(rows):
            if row.component in valid_times and abs((valid_times[row.component] - reference).total_seconds()) > coops.ALIGN_TOLERANCE_S:
                rows[index] = row.model_copy(update={
                    "state": "unavailable",
                    "reason": f"latest observation is not aligned with wind within {coops.ALIGN_TOLERANCE_S:g} s",
                })
    rows.extend([
        EnvironmentComponentAvailability(
            component="forecast", state="unavailable", reason="no composed forecast configured (D2)"
        ),
        EnvironmentComponentAvailability(
            component="waves", state="unavailable", reason="no wave provider configured (D4)"
        ),
    ])
    complete = all(row.state != "unavailable" for row in rows if row.component in {"wind", "current", "water_level"})
    return EnvironmentAvailability(
        berth_id=berth_id,
        checked_at_utc=checked,
        complete_snapshot_available=complete,
        components=rows,
    )


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
