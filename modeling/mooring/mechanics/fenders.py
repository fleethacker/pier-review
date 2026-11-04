"""Unilateral fender contact with a force/deflection curve and energy integration."""

import math
from dataclasses import dataclass

from .curves import UnsupportedMechanics
from .pose import Pose, ShipFrame


@dataclass
class FenderModel:
    """A fender on the pier face at berth-frame x.

    `face_y_ft` is the undeflected face of the fender (distance from the pier face). The ship's pier-side hull is
    modeled as a straight line parallel to the centerline over +/- half_contact_length_ft (parallel body assumption).
    Force acts normal to the pier face, away from the pier (+y), and only when the hull penetrates the fender
    (unilateral: never tension, never a pull toward the pier). `curve` is (deflection ft, force lbf) from (0, 0).
    """

    fender_id: str
    x_ft: float
    face_y_ft: float
    length_ft: float
    curve: list[tuple[float, float]]
    rated_energy_ftlbf: float | None = None

    def __post_init__(self):
        pts = self.curve
        if len(pts) < 2 or tuple(pts[0]) != (0.0, 0.0):
            raise UnsupportedMechanics("fender curve must start at (0, 0) and have at least two points")
        if any(not (math.isfinite(d) and math.isfinite(f)) for d, f in pts):
            raise UnsupportedMechanics("fender curve has non-finite values")
        if any(b[0] <= a[0] or b[1] < a[1] for a, b in zip(pts, pts[1:])):
            raise UnsupportedMechanics("fender curve needs increasing deflection and non-decreasing force")

    @classmethod
    def linear(cls, fender_id: str, x_ft: float, face_y_ft: float, length_ft: float, stiffness_lbf_per_ft: float,
               rated_energy_ftlbf: float | None = None, max_deflection_ft: float = 10.0) -> "FenderModel":
        return cls(fender_id, x_ft, face_y_ft, length_ft, [(0.0, 0.0), (max_deflection_ft, stiffness_lbf_per_ft * max_deflection_ft)],
                   rated_energy_ftlbf)

    def force(self, deflection_ft: float) -> float:
        if deflection_ft <= 0:
            return 0.0
        pts = self.curve
        for (d0, f0), (d1, f1) in zip(pts, pts[1:]):
            if deflection_ft <= d1:
                return f0 + (deflection_ft - d0) / (d1 - d0) * (f1 - f0)
        (d0, f0), (d1, f1) = pts[-2], pts[-1]
        return f1 + (deflection_ft - d1) / (d1 - d0) * (f1 - f0)

    def energy(self, deflection_ft: float) -> float:
        """Absorbed energy = integral of force over deflection (exact for the piecewise-linear curve)."""
        if deflection_ft <= 0:
            return 0.0
        total, pts = 0.0, self.curve
        for (d0, f0), (d1, f1) in zip(pts, pts[1:]):
            if deflection_ft <= d0:
                break
            top = min(deflection_ft, d1)
            ft = f0 + (top - d0) / (d1 - d0) * (f1 - f0)
            total += 0.5 * (f0 + ft) * (top - d0)
        if deflection_ft > pts[-1][0]:
            (d0, f0), (d1, f1) = pts[-2], pts[-1]
            slope = (f1 - f0) / (d1 - d0)
            extra = deflection_ft - d1
            total += f1 * extra + 0.5 * slope * extra**2
        return total

    def hull_y(self, frame: ShipFrame, pose: Pose, hull_side_y_ship_ft: float, half_contact_length_ft: float):
        """Berth-frame y of the pier-side hull above this fender and the ship-frame x there; None if beyond the body."""
        psi = frame.psi(pose)
        c, s = math.cos(psi), math.sin(psi)
        cx, cy = frame.reference(pose)
        if abs(c) < 1e-9:
            return None
        xs = ((self.x_ft - cx) + s * hull_side_y_ship_ft) / c
        if abs(xs) > half_contact_length_ft:
            return None
        return cy + s * xs + c * hull_side_y_ship_ft, xs

    def deflection(self, frame: ShipFrame, pose: Pose, hull_side_y_ship_ft: float, half_contact_length_ft: float) -> tuple[float, float | None]:
        """(deflection ft >= 0, hull y or None). Zero when out of contact or beyond the hull body."""
        hit = self.hull_y(frame, pose, hull_side_y_ship_ft, half_contact_length_ft)
        if hit is None:
            return 0.0, None
        y, _ = hit
        return max(0.0, self.face_y_ft - y), y
