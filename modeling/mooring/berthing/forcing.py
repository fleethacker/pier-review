"""Compatibility alias: the S2 forcing resolver lives in mooring.core.forcing (shared by berthing and prediction)."""
from mooring.core.forcing import *  # noqa: F401,F403
from mooring.core.forcing import ForcingSeries, ForcingUncovered, apparent_wind, CHANNELS, ANGLES  # noqa: F401
