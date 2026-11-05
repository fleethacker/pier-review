"""Swap point: which implementation serves each agent. Change one import when an agent's real version lands."""

from .intake import agent as intake  # noqa: F401
from .planner import agent as planner  # noqa: F401
from .safety import agent as safety  # noqa: F401
from .safety import sheet  # noqa: F401
from .vision import agent as vision  # noqa: F401

BACKENDS: dict[str, str] = {
    "Environment/Intake agent": "real (deterministic core, optional guarded LLM summary)",
    "Physics/Load agent": "real (logged tool gateway; modeling validity and qualification remain authoritative)",
    "Planner agent (M9)": "real (guarded adjustments, deterministic fallback; modeling capabilities remain mixed)",
    "Safety/Brief agent (M10)": "real deterministic review, guarded brief and warning stream",
    "Berth Map agent (M8)": "real draft pipeline; estimated catalog geometry and optional image proposals",
    "Prediction narration agent (A7)": "real deterministic narration of immutable S7 results; model warnings and coverage preserved",
}


def overall_backend() -> str:
    return "real" if all(value.startswith("real") for value in BACKENDS.values()) else "mixed"
