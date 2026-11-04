"""Environment service (M1), used by every phase: wind, current and water level from any source.

This package is the stable interface. Callers import `from mooring import environment` and never `environment.mock`.
`mock.py` is a deterministic synthetic tide and wind; the real module (NOAA CO-OPS, CBOFS, NWS adapters) replaces
the one import below, keeping these signatures.
"""

from .mock import (  # noqa: F401
    create_scenario,
    forecast,
    get_scenario,
    gust_model,
    history,
    now,
    scenario_snapshot,
    synthetic,
    with_relative,
)
