"""Swap point: which implementation serves each agent. Change one import when an agent's real version lands."""

from .intake import agent as intake  # noqa: F401
from .planner import agent as planner  # noqa: F401
from .safety import agent as safety  # noqa: F401
from .safety import sheet  # noqa: F401
from .vision import mock as vision  # noqa: F401

BACKENDS: dict[str, str] = {
    "Environment/Intake agent": "real (deterministic core, optional guarded LLM summary)",
    "Physics/Load agent": "real (logged tool gateway; physics itself is mock in modeling/)",
    "Planner agent (M9)": "real (guarded adjustments, deterministic fallback; modeling capabilities remain mixed)",
    "Safety/Brief agent (M10)": "real deterministic review, guarded brief and warning stream",
    "Berth Map agent (M8)": "mock",
}
