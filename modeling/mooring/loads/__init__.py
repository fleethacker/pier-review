"""Environmental loads (M3), used by every phase.

`compute_loads` is the single entry point for wind and current forces. It currently points at the mock drag
model in `mock.py`; chunk 1 adds the UFC 4-159-03 implementation in this package and switches it here.
Callers never import `mock.py` directly.
"""

from .helpers import mean_draft_ft, off_pier
from .mock import crude_loads as compute_loads

__all__ = ["compute_loads", "mean_draft_ft", "off_pier"]
