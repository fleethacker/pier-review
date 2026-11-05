"""Environment service (M1), used by every phase: wind, current and water level from any source.

This package is the stable interface. Callers import `from mooring import environment` and never `environment.mock`.
`mock.py` is a deterministic synthetic tide and wind. With MOORING_ENV_SOURCE=coops, `now` and `history` are served by the
CO-OPS adapter (`live.py`) and `forecast` is unavailable until a forecast provider is enabled; a provider failure is
raised, never replaced by synthetic data. `synthetic()` stays the deterministic generator used by risk, windows and tide
sweeps and is labeled as such in their validity.
"""

import os

from . import mock as _mock
from .mock import (  # noqa: F401
    get_scenario,
    gust_model,
    synthetic,
    with_relative,
)


def source_mode() -> str:
    return os.environ.get("MOORING_ENV_SOURCE", "mock")


def _replay_snapshot(sc, t):
    """Replay-scenario snapshot from the recorded fixture; unavailable (never looped or synthesized) outside the window."""
    from datetime import timedelta  # noqa: F401
    from .coops import ProviderError
    from .replay import Unavailable, recorded_fixture_source
    at = sc.replay_start_utc + (t - sc.created_at_utc)
    if at > sc.replay_end_utc:
        raise ProviderError("no_data", f"replay window exhausted at {sc.replay_end_utc.isoformat()}; scenarios do not loop")
    snap = recorded_fixture_source().at(at, now=at)
    if isinstance(snap, Unavailable):
        raise ProviderError("no_data", snap.reason)
    return snap


def create_scenario(req):
    from mooring import refdata
    from .replay import recorded_fixture_source
    if req.replay_source == "recorded_fixture":
        cov = recorded_fixture_source().coverage
        if req.replay_start_utc < cov[0] or req.replay_end_utc > cov[1]:
            raise refdata.InvalidReference(f"recorded fixture covers {cov[0].isoformat()} to {cov[1].isoformat()}; the requested window is outside it")
    return _mock.create_scenario(req)


def scenario_snapshot(env_scenario_id, t):
    sc = _mock.get_scenario(env_scenario_id)
    if sc.kind == "replay" and sc.replay_source == "recorded_fixture":
        return _replay_snapshot(sc, t)
    return _mock.scenario_snapshot(env_scenario_id, t)


def now(berth_id, heading_true_deg=None, env_scenario_id=None):
    if env_scenario_id:
        from mooring.core.envelopes import utcnow
        return with_relative(scenario_snapshot(env_scenario_id, utcnow()), heading_true_deg)
    if source_mode() != "coops":
        return _mock.now(berth_id, heading_true_deg, None)
    from . import live
    return live.latest(berth_id, heading_true_deg)


def history(station_id, start, end, step_min=6):
    if source_mode() != "coops":
        return _mock.history(station_id, start, end, step_min)
    from . import live
    return live.history(station_id, start, end, step_min)


def replay_snapshot(berth_id, at, heading_true_deg=None):
    """Replay a provider observation or explicitly synthetic fixture at an explicit time."""
    from .errors import ProviderError
    if at.tzinfo is None or at.utcoffset() is None:
        raise ProviderError("malformed", "Replay time must include a timezone offset")
    if source_mode() == "coops":
        from . import live
        return live.at(berth_id, at, heading_true_deg)
    from .replay import Unavailable, recorded_fixture_source
    snap = recorded_fixture_source().at(at, now=at)
    if isinstance(snap, Unavailable):
        raise ProviderError("no_data", snap.reason)
    return with_relative(snap, heading_true_deg)


def provider_modules() -> dict[str, str]:
    coops = "live" if source_mode() == "coops" else "mock (disabled)"
    return {
        "Provider NOAA CO-OPS": coops,
        "Provider NWS": "unavailable (DC2 not installed)",
        "Provider CBOFS": "unavailable (DC3 not installed)",
    }


def forecast(berth_id, hours=48, step_min=30):
    if source_mode() == "coops":
        from .coops import ProviderError
        raise ProviderError("unavailable", "no forecast provider is enabled (S04c); forecast components are unavailable, not synthesized")
    return _mock.forecast(berth_id, hours, step_min)
