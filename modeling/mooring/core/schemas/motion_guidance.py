"""Explicit training guidance state, not navigation approval."""
from typing import Literal
from .common import Model

class MotionGuidanceState(Model):
    active: bool
    route_id: str
    waypoint_index: int
    waypoint_name: str
    target_speed_kt: float
    cross_track_ft: float
    remaining_ft: float
    completed: bool
    source: Literal["synthetic"] = "synthetic"
