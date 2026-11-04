"""Compatibility imports for consumers migrated from the original mock planner.

The active implementation and plan store live in agent.py. Keep one store so Safety
and the API resolve the same plans during the module transition.
"""
from .agent import PLANS, PlanRecord, _analyze_body, answer, run  # noqa: F401
