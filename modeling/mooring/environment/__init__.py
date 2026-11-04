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
    create_scenario,
    get_scenario,
    gust_model,
    scenario_snapshot,
    synthetic,
    with_relative,
)


def source_mode() -> str:
    return os.environ.get("MOORING_ENV_SOURCE", "mock")


def now(berth_id, heading_true_deg=None, env_scenario_id=None):
    if env_scenario_id or source_mode() != "coops":
        return _mock.now(berth_id, heading_true_deg, env_scenario_id)
    from . import live
    return live.latest(berth_id, heading_true_deg)


def history(station_id, start, end, step_min=6):
    if source_mode() != "coops":
        return _mock.history(station_id, start, end, step_min)
    from . import live
    return live.history(station_id, start, end, step_min)


def forecast(berth_id, hours=48, step_min=30):
    if source_mode() == "coops":
        from .coops import ProviderError
        raise ProviderError("unavailable", "no forecast provider is enabled (S04c); forecast components are unavailable, not synthesized")
    return _mock.forecast(berth_id, hours, step_min)
