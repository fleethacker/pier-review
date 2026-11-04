"""Swap point: which implementation serves each agent. Change an import when the LLM-backed agent lands."""

from .mock import sheet, vision  # noqa: F401
from .planner import agent as planner  # noqa: F401

BACKENDS: dict[str, str] = {
    "M8 berth vision": "mock",
    "M9 planning agent": "OpenAI tool loop (deterministic fallback)",
    "M10 safety sheet": "real assembly over mock inputs",
}
