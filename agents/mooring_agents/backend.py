"""Swap point: which implementation serves each agent. Change one import when an agent's real version lands."""

from .intake import mock as intake  # noqa: F401
from .planner import mock as planner  # noqa: F401
from .safety import mock as safety  # noqa: F401
from .safety import sheet  # noqa: F401
from .vision import mock as vision  # noqa: F401

BACKENDS: dict[str, str] = {
    "Environment/Intake agent": "mock (deterministic window detection, no LLM)",
    "Physics/Load agent": "real (logged tool gateway; physics itself is mock in modeling/)",
    "Planner agent (M9)": "mock (deterministic loop over physics tools)",
    "Safety/Brief agent (M10)": "mock review and warnings; real sheet assembly",
    "Berth Map agent (M8)": "mock",
}
