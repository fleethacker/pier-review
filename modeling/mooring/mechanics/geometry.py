"""Line geometry at a pose, and fitting reactions."""

import math
from dataclasses import dataclass

from .pose import Pose, ShipFrame, Wrench, force_wrench


@dataclass(frozen=True)
class LineState:
    length_ft: float
    ux: float   # unit vector from the ship lead toward the pier fitting (berth frame)
    uy: float
    uz: float
    lead_berth: tuple[float, float]


def line_state(frame: ShipFrame, pose: Pose, lead_ship_xy: tuple[float, float], lead_z_ft: float,
               pier_xyz: tuple[float, float, float]) -> LineState:
    """3-D length and direction of a line from the ship's lead point (chock or bitt) to the pier fitting.

    `lead_z_ft` is the absolute height (water level + height above waterline); heave and roll are not modeled."""
    lx, ly = frame.to_berth(lead_ship_xy[0], lead_ship_xy[1], pose)
    dx, dy, dz = pier_xyz[0] - lx, pier_xyz[1] - ly, pier_xyz[2] - lead_z_ft
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length <= 0:
        raise ValueError("line has zero length")
    return LineState(length, dx / length, dy / length, dz / length, (lx, ly))


def line_wrench(frame: ShipFrame, pose: Pose, lead_ship_xy: tuple[float, float], state: LineState, tension_lbf: float) -> Wrench:
    """Horizontal force and yaw moment the line applies to the ship (about the reference point)."""
    return force_wrench(frame, pose, lead_ship_xy, tension_lbf * state.ux, tension_lbf * state.uy)


def pier_reaction(states_and_tensions: list[tuple[LineState, float]]) -> tuple[float, float, float]:
    """Vector load on a pier fitting from the lines made fast to it (pulled toward the ship)."""
    fx = sum(t * s.ux for s, t in states_and_tensions)
    fy = sum(t * s.uy for s, t in states_and_tensions)
    fz = sum(t * s.uz for s, t in states_and_tensions)
    return fx, fy, fz
