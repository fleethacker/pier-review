"""Swap point: which implementation serves each module.

Every module starts as a mock in mooring/mock/. When a workstream's real module is ready, change its import here
(keeping the same function signatures) and update BACKENDS. The routers never import implementations directly.
"""

from mooring.mock import dynamics, planning, risk, scenarios, telemetry, tugs  # noqa: F401
from mooring.mock import environment as env  # noqa: F401
from mooring.mock import forces as loads  # noqa: F401
from mooring.mock import mooring as solver  # noqa: F401

BACKENDS: dict[str, str] = {
    "M1 environment": "mock",
    "M2 reference data": "real (seed YAML)",
    "M3 environmental loads": "mock",
    "M4 static solver": "mock (geometry and rules real)",
    "M5 risk engine": "mock",
    "M6 tug planner": "mock",
    "M7 optimizer and sequence": "mock",
    "M11 berthing simulator": "mock",
    "M12 approach planner": "mock",
    "M13 telemetry ingest": "mock",
}
