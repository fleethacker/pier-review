"""Compatibility imports for consumers still using intake.mock's shared report store.

The deterministic implementation now lives in core.py; the backend serves agent.py.
"""

from .core import REPORTS, assess  # noqa: F401
