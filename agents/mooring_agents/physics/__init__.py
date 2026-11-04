"""Physics/Load agent: the only path from any agent to physics.

A logged tool gateway over the modeling service (client.py, tools.py, toolkit.py). It does no math and uses no
LLM: every number comes from modeling/. See README.md.
"""

from .summary import summarize
from .toolkit import PhysicsToolkit, calls_for
from .tools import tool_definitions

__all__ = ["PhysicsToolkit", "calls_for", "summarize", "tool_definitions"]
