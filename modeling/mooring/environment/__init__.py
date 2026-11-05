"""Environment service (M1), used by every phase: wind, current and water level from any source.

This package is the stable interface. Callers import `from mooring import environment` and never `environment.mock`.
`mock.py` is a deterministic synthetic tide and wind and is used only when explicitly configured. Supported modes are
`mock`, `coops`, `replay` and `auto`. Auto tries a fresh, complete CO-OPS snapshot and then the manifest-backed recorded
observation package; it never falls through to mock. `synthetic()` remains available to explicit training and what-if
workflows and is labeled as such in their validity.
"""

import os
from datetime import UTC

from . import mock as _mock
from .mock import (  # noqa: F401
    get_scenario,
    synthetic,
    with_relative,
)

SUPPORTED_SOURCE_MODES = frozenset({"mock", "coops", "replay", "auto"})


class EnvironmentConfigurationError(RuntimeError):
    """The configured environment source is absent or unsupported."""


def gust_model(station_id):
    from .uncertainty import served_gust_model
    return served_gust_model(station_id)


def source_mode() -> str:
    raw = os.environ.get("MOORING_ENV_SOURCE")
    if raw is None or raw == "":
        raise EnvironmentConfigurationError(
            "MOORING_ENV_SOURCE must be set explicitly to one of: auto, coops, mock, replay"
        )
    if raw not in SUPPORTED_SOURCE_MODES:
        raise EnvironmentConfigurationError(
            f"unsupported MOORING_ENV_SOURCE={raw!r}; expected one of: auto, coops, mock, replay"
        )
    return raw


def validate_configuration() -> str:
    """Validate once at application startup and again at dispatch boundaries."""
    return source_mode()


def _missing_capabilities():
    from mooring.core.schemas import EnvironmentComponentAvailability
    return [
        EnvironmentComponentAvailability(
            component="forecast", state="unavailable",
            reason="forecast status requires an as-of time and horizon via POST /api/v1/env/forecast/compose"
        ),
        EnvironmentComponentAvailability(
            component="waves", state="unavailable", reason="no wave provider configured (D4)"
        ),
    ]


def _recorded_package(berth_id):
    from .errors import ProviderError
    from .replay import ReplayError, recorded_real_package
    try:
        package = recorded_real_package()
    except ReplayError as exc:
        raise ProviderError("unavailable", f"recorded replay package failed verification: {exc}") from None
    if not package.supports_berth(berth_id):
        raise ProviderError("no_data", f"recorded replay package {package.package_id!r} is not applicable to berth {berth_id!r}")
    return package


def _recorded_at(berth_id, at, heading_true_deg=None):
    from .errors import ProviderError
    from .replay import Unavailable
    package = _recorded_package(berth_id)
    snap = package.source.at(at, now=at)
    if isinstance(snap, Unavailable):
        raise ProviderError("no_data", snap.reason)
    return with_relative(snap, heading_true_deg)


def _recorded_latest(berth_id, heading_true_deg=None):
    package = _recorded_package(berth_id)
    return _recorded_at(berth_id, package.source.coverage[1], heading_true_deg)


def live_snapshot(berth_id, heading_true_deg=None):
    """Explicit operational source used by saved `live` selections; never consult global fallback mode."""
    from . import live
    return live.latest(berth_id, heading_true_deg)


def _snapshot_availability(berth_id, snap, state, checked_at):
    from mooring import refdata
    from mooring.core.schemas import EnvironmentAvailability, EnvironmentComponentAvailability

    stations = refdata.berth(berth_id).env_station_ids
    station_by_component = {
        "wind": stations.wind,
        "current": stations.current,
        "water_level": stations.water_level,
    }
    component_meta = {item.component: item for item in (snap.metadata.components if snap.metadata else [])}
    rows = []
    for component in ("wind", "current", "water_level"):
        meta = component_meta.get(component)
        valid_at = (meta.valid_to_utc if meta and meta.valid_to_utc else snap.valid_at_utc).astimezone(UTC)
        rows.append(EnvironmentComponentAvailability(
            component=component,
            state=state,
            source=(meta.source if meta else (snap.metadata.source if snap.metadata and snap.metadata.source else f"Explicit {state} environment")),
            basis=(meta.basis if meta else (snap.metadata.basis if snap.metadata else "scenario")),
            age_s=max((checked_at - valid_at).total_seconds(), 0.0),
            age_basis="valid_time",
            issued_at_utc=meta.issued_at_utc if meta else None,
            retrieved_at_utc=meta.retrieved_at_utc if meta else None,
            valid_from_utc=meta.valid_from_utc if meta else snap.valid_at_utc,
            valid_to_utc=meta.valid_to_utc if meta else snap.valid_at_utc,
            quality=meta.quality if meta else (snap.metadata.quality if snap.metadata else "unknown"),
            limitations=list(meta.limitations) if meta else [],
            station_id=station_by_component[component],
            current_depth_ft=snap.metadata.current_depth_ft if component == "current" and snap.metadata else None,
            current_bin=snap.metadata.current_bin if component == "current" and snap.metadata else None,
            vertical_datum=snap.metadata.vertical_datum if component == "water_level" and snap.metadata else None,
            wind_averaging_s=snap.metadata.wind_averaging_s if component == "wind" and snap.metadata else None,
            gust_duration_s=snap.metadata.gust_duration_s if component == "wind" and snap.metadata else None,
            wind_reference_height_m=snap.metadata.wind_reference_height_m if component == "wind" and snap.metadata else None,
        ))
    return EnvironmentAvailability(
        berth_id=berth_id,
        checked_at_utc=checked_at,
        complete_snapshot_available=True,
        components=[*rows, *_missing_capabilities()],
    )


def availability(berth_id):
    """Independent component status; partial or unavailable data still returns a status object."""
    from mooring import refdata
    from mooring.core.envelopes import utcnow
    from .errors import ProviderError

    refdata.berth(berth_id)
    checked = utcnow().astimezone(UTC)
    mode = source_mode()
    if mode == "mock":
        snap = _mock.now(berth_id, None, None)
        return _snapshot_availability(berth_id, snap, "mock", checked)
    if mode == "replay":
        return _snapshot_availability(berth_id, _recorded_latest(berth_id), "replay", checked)
    from . import live
    live_status = live.component_availability(berth_id, checked)
    if mode == "coops" or live_status.complete_snapshot_available:
        return live_status
    try:
        replay_status = _snapshot_availability(berth_id, _recorded_latest(berth_id), "replay", checked)
    except ProviderError as exc:
        note = f"recorded replay fallback unavailable: {exc}"
        rows = [item.model_copy(update={"limitations": [*item.limitations, note]}) for item in live_status.components]
        return live_status.model_copy(update={"components": rows})
    live_reasons = "; ".join(
        f"{item.component}: {item.reason}" for item in live_status.components
        if item.component in {"wind", "current", "water_level"} and item.state == "unavailable"
    )
    rows = [
        item.model_copy(update={"limitations": [*item.limitations, f"auto fallback from live ({live_reasons})"]})
        if item.component in {"wind", "current", "water_level"} else item
        for item in replay_status.components
    ]
    return replay_status.model_copy(update={"components": rows})


def _replay_snapshot(sc, t, berth_id=None):
    """Replay-scenario snapshot from its explicit source; never looped or synthesized."""
    from .coops import ProviderError
    from .replay import Unavailable, recorded_fixture_source
    at = sc.replay_start_utc + (t - sc.created_at_utc)
    if at > sc.replay_end_utc:
        raise ProviderError("no_data", f"replay window exhausted at {sc.replay_end_utc.isoformat()}; scenarios do not loop")
    if sc.replay_source == "recorded_real":
        if berth_id is None:
            raise ProviderError("invalid_request", "recorded_real replay requires a berth_id for applicability validation")
        source = _recorded_package(berth_id).source
    else:
        source = recorded_fixture_source()
    snap = source.at(at, now=at)
    if isinstance(snap, Unavailable):
        raise ProviderError("no_data", snap.reason)
    return snap


def create_scenario(req):
    from mooring import refdata
    from .replay import ReplayError, recorded_fixture_source, recorded_real_source
    if req.replay_source in {"recorded_fixture", "recorded_real"}:
        try:
            source = recorded_real_source() if req.replay_source == "recorded_real" else recorded_fixture_source()
        except ReplayError as exc:
            raise refdata.InvalidReference(f"recorded replay package failed verification: {exc}") from None
        cov = source.coverage
        if req.replay_start_utc < cov[0] or req.replay_end_utc > cov[1]:
            raise refdata.InvalidReference(f"recorded replay covers {cov[0].isoformat()} to {cov[1].isoformat()}; the requested window is outside it")
    return _mock.create_scenario(req)


def scenario_snapshot(env_scenario_id, t, berth_id=None):
    sc = _mock.get_scenario(env_scenario_id)
    if sc.kind == "replay" and sc.replay_source in {"recorded_fixture", "recorded_real"}:
        return _replay_snapshot(sc, t, berth_id)
    return _mock.scenario_snapshot(env_scenario_id, t)


def now(berth_id, heading_true_deg=None, env_scenario_id=None):
    if env_scenario_id:
        from mooring.core.envelopes import utcnow
        return with_relative(scenario_snapshot(env_scenario_id, utcnow(), berth_id), heading_true_deg)
    mode = source_mode()
    if mode == "mock":
        return _mock.now(berth_id, heading_true_deg, None)
    if mode == "replay":
        return _recorded_latest(berth_id, heading_true_deg)
    from .errors import ProviderError
    try:
        return live_snapshot(berth_id, heading_true_deg)
    except ProviderError as live_error:
        if mode == "coops":
            raise
        try:
            return _recorded_latest(berth_id, heading_true_deg)
        except ProviderError as replay_error:
            raise ProviderError(
                "unavailable",
                f"auto source exhausted: live failed ({live_error}); recorded replay failed ({replay_error}); mock is disabled",
            ) from None


def history(station_id, start, end, step_min=6):
    mode = source_mode()
    if mode == "mock":
        return _mock.history(station_id, start, end, step_min)
    if mode in {"coops", "auto"}:
        from . import live
        from .errors import ProviderError
        try:
            return live.history(station_id, start, end, step_min)
        except ProviderError:
            if mode == "coops":
                raise
    from mooring.core.schemas import HistorySeries
    from .errors import ProviderError
    from .replay import Unavailable
    package = _recorded_package("NAVSTA-NORFOLK-P12-N")
    known = {item["station_id"] for item in package.manifest["stations"]}
    if station_id not in known:
        raise ProviderError("no_data", f"station {station_id!r} is not in the recorded replay package")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    coverage = package.source.coverage
    if start < coverage[0] or end > coverage[1]:
        raise ProviderError("no_data", f"requested history is outside recorded coverage {coverage[0].isoformat()}..{coverage[1].isoformat()}")
    series = []
    for record in package.source.records:
        if start <= record.t <= end:
            snap = package.source.at(record.t, now=record.t)
            if not isinstance(snap, Unavailable):
                series.append(snap)
    return HistorySeries(station_id=station_id, start_utc=start, end_utc=end, series=series)


def replay_snapshot(berth_id, at, heading_true_deg=None):
    """Replay the manifest-backed recorded observation at an explicit historical time."""
    from .errors import ProviderError
    if at.tzinfo is None or at.utcoffset() is None:
        raise ProviderError("malformed", "Replay time must include a timezone offset")
    return _recorded_at(berth_id, at, heading_true_deg)


def provider_modules() -> dict[str, str]:
    mode = source_mode()
    coops = {
        "mock": "observations disabled; public predictions available only through bound compose requests",
        "coops": "live observations without fallback; public predictions through bound compose requests",
        "replay": "observations disabled; public predictions available only through bound compose requests",
        "auto": "live observations with recorded replay fallback; public predictions through bound compose requests",
    }[mode]
    return {
        "Provider NOAA CO-OPS": coops,
        "Provider NWS": "bound forecast composition (missing gust/coverage stays unavailable)",
        "Provider CBOFS": "decoded cache artifact only when exact coordinate/depth/layer and publication evidence match",
    }


def forecast(berth_id, hours=48, step_min=30):
    if source_mode() == "mock":
        return _mock.forecast(berth_id, hours, step_min)
    from .coops import ProviderError
    raise ProviderError(
        "unavailable",
        "legacy GET /env/forecast has no public-provider mode; use bound POST /env/forecast/compose (values are not synthesized)",
    )


def compose_forecast(request):
    """Resolve the D2 component-level forecast without changing the legacy compatibility endpoint."""
    from .composed_forecast import compose
    return compose(request)
