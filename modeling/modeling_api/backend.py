"""Swap point: which implementation serves each module.

Every module starts as a mock (`mock.py` or a `mock/` subpackage inside its package). When a workstream's real
module is ready, change its import here (same function signatures) and update BACKENDS. Routers never import
implementations directly.
"""

# Shared across phases
from mooring import scenarios  # noqa: F401
from mooring.environment import mock as env  # noqa: F401
from mooring.loads import service as loads  # noqa: F401
from mooring.telemetry import mock as telemetry  # noqa: F401

# Phase 3: approach
from mooring.approach.mock import planner as approach_planner  # noqa: F401
from mooring.approach.mock import simulator as approach_sim  # noqa: F401

# Phase 1c/2: berthing
from mooring.berthing.mock import sequence  # noqa: F401
from mooring.berthing.mock import simulator as berthing_sim  # noqa: F401
from mooring.berthing.mock import tugs as berthing_tugs  # noqa: F401

# Phase 1: moored
from mooring.moored.mock import optimizer, risk, solver  # noqa: F401
from mooring.moored.mock import tugs as moored_tugs  # noqa: F401

BACKENDS: dict[str, str] = {
    "M1 environment": "mock",
    "M2 reference data": "real (seed YAML)",
    "M3 environmental loads": "real",
    "M4 static solver (moored)": "mock (geometry and rules real)",
    "M5 risk engine (moored)": "mock",
    "M6 tug planner (moored, berthing)": "mock",
    "M7 optimizer (moored) and sequence (berthing)": "mock",
    "M11 berthing simulator": "mock",
    "M12 approach planner": "mock",
    "M13 telemetry ingest": "mock",
}


def overall_backend() -> str:
    """'real' if every module is real, 'mock' if none is, else 'mixed'. Drives /health and X-Mooring-Backend."""
    real = [v.startswith("real") for v in BACKENDS.values()]
    return "real" if all(real) else "mock" if not any(real) else "mixed"
