"""Rigid-body pose of the ship in the berth frame and wrench bookkeeping.

Berth frame: +x along the face, +y into the water, +z up, yaw positive counterclockwise seen from above.
A ship moored starboard side to has its bow toward +x (heading angle psi0 = 0); port side to, psi0 = pi.
Ship frame: +x forward, +y to port. Pose = displacement of the midships reference point plus a yaw change.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Pose:
    dx_ft: float = 0.0
    dy_ft: float = 0.0
    dyaw_rad: float = 0.0


@dataclass(frozen=True)
class Wrench:
    fx_lbf: float
    fy_lbf: float
    mz_ftlbf: float

    def __add__(self, o: "Wrench") -> "Wrench":
        return Wrench(self.fx_lbf + o.fx_lbf, self.fy_lbf + o.fy_lbf, self.mz_ftlbf + o.mz_ftlbf)

    def vec(self) -> tuple[float, float, float]:
        return (self.fx_lbf, self.fy_lbf, self.mz_ftlbf)


ZERO = Wrench(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class ShipFrame:
    """Where the ship's reference point sits when the pose is zero."""

    side_to: str
    ref_x_ft: float        # berth-frame x of midships
    ref_y_ft: float        # berth-frame y of midships (standoff + beam / 2)

    @property
    def psi0(self) -> float:
        return 0.0 if self.side_to == "starboard" else math.pi

    def psi(self, pose: Pose) -> float:
        return self.psi0 + pose.dyaw_rad

    def reference(self, pose: Pose) -> tuple[float, float]:
        return self.ref_x_ft + pose.dx_ft, self.ref_y_ft + pose.dy_ft

    def to_berth(self, xs: float, ys: float, pose: Pose) -> tuple[float, float]:
        """Ship-frame (xs, ys) -> berth-frame (x, y) at `pose`."""
        psi = self.psi(pose)
        cx, cy = self.reference(pose)
        c, s = math.cos(psi), math.sin(psi)
        return cx + c * xs - s * ys, cy + s * xs + c * ys

    def arm(self, xs: float, ys: float, pose: Pose) -> tuple[float, float]:
        """Vector from the reference point to a ship-fixed point, in the berth frame."""
        psi = self.psi(pose)
        c, s = math.cos(psi), math.sin(psi)
        return c * xs - s * ys, s * xs + c * ys

    def vector_to_berth(self, fx_ship: float, fy_ship: float, pose: Pose) -> tuple[float, float]:
        """Rotate a ship-frame vector (forces) into the berth frame."""
        psi = self.psi(pose)
        c, s = math.cos(psi), math.sin(psi)
        return c * fx_ship - s * fy_ship, s * fx_ship + c * fy_ship

    def heading_true_deg(self, face_bearing_true_deg: float, pose: Pose) -> float:
        """True heading of the bow. Counterclockwise yaw turns the bow toward lower bearings."""
        base = face_bearing_true_deg if self.side_to == "starboard" else face_bearing_true_deg + 180
        return (base - math.degrees(pose.dyaw_rad)) % 360


def force_wrench(frame: ShipFrame, pose: Pose, point_ship: tuple[float, float], fx: float, fy: float) -> Wrench:
    """Berth-frame force (fx, fy) applied at a ship-fixed point, as a wrench about the reference point."""
    rx, ry = frame.arm(point_ship[0], point_ship[1], pose)
    return Wrench(fx, fy, rx * fy - ry * fx)


def force_wrench_at(frame: ShipFrame, pose: Pose, point_berth: tuple[float, float], fx: float, fy: float) -> Wrench:
    """Same, for a point given in the berth frame (e.g. the hull contact point)."""
    cx, cy = frame.reference(pose)
    rx, ry = point_berth[0] - cx, point_berth[1] - cy
    return Wrench(fx, fy, rx * fy - ry * fx)
