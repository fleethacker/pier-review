"""Swap point: which implementation serves each agent. Change an import when the LLM-backed agent lands."""

from .mock import planner, sheet, vision  # noqa: F401

BACKENDS: dict[str, str] = {
    "M8 berth vision": "mock",
    "M9 planning agent": "mock (deterministic loop over modeling tools)",
    "M10 safety sheet": "real assembly over mock inputs",
}
