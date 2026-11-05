"""Tug forces on named hull points (SI, body frame). Tug hull kinematics are NOT modeled.

Force direction is relative to the bow, clockwise: 0 ahead, 90 toward starboard, 180 astern, 270 toward port, so the
body-frame force is F (cos th, -sin th) with +y port. The moment about midships is N = x Fy - y Fx. Capacity is the
catalog bollard_pull_ahead for any direction (labeled assumption). The delivered force VECTOR slews toward the
commanded vector at |dF/dt| <= bollard / TUG_SLEW_S (labeled), updated once per integration step and held through
the RK4 stages (zero-order hold).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import coefficients as C
from .geo import norm360

POINTS = {  # (x/LOA, y: +-B/2 or 0)
    "bow": (0.45, 0.0), "stern": (-0.45, 0.0),
    "port_shoulder": (0.30, 1.0), "starboard_shoulder": (0.30, -1.0),
    "port_quarter": (-0.30, 1.0), "starboard_quarter": (-0.30, -1.0),
}


def point_xy(point: str, loa_m: float, beam_m: float) -> tuple[float, float]:
    fx, fy = POINTS[point]
    return fx * loa_m, fy * beam_m / 2


def unit(direction_rel_deg: float) -> tuple[float, float]:
    th = math.radians(direction_rel_deg)
    return math.cos(th), -math.sin(th)


@dataclass
class TugTrack:
    tug_id: str
    capacity_n: float
    point: str | None = None
    x: float = 0.0
    y: float = 0.0
    cmd: tuple[float, float] = (0.0, 0.0)      # commanded body force vector (N)
    out: tuple[float, float] = (0.0, 0.0)      # delivered body force vector (N)
    source: str = "command"
    saturated: bool = False

    def set_point(self, point, x, y):
        if point != self.point:
            self.out = (0.0, 0.0)               # a tug that changes hull point starts from zero force
        self.point, self.x, self.y = point, x, y

    def command(self, force_n: float, direction_rel_deg: float, source: str) -> bool:
        """Set the commanded vector; returns True when the request exceeded bollard pull (clamped)."""
        over = force_n > self.capacity_n * (1 + 1e-12)
        f = min(force_n, self.capacity_n)
        ux, uy = unit(direction_rel_deg)
        self.cmd, self.source = (f * ux, f * uy), source
        return over

    def slew(self, dt: float):
        dx, dy = self.cmd[0] - self.out[0], self.cmd[1] - self.out[1]
        d = math.hypot(dx, dy)
        step = self.capacity_n / C.TUG_SLEW_S * dt
        self.out = self.cmd if d <= step else (self.out[0] + dx / d * step, self.out[1] + dy / d * step)

    def magnitude(self) -> float:
        return math.hypot(*self.out)

    def direction_rel_deg(self) -> float:
        fx, fy = self.out
        return 0.0 if math.hypot(fx, fy) < 1e-9 else norm360(math.degrees(math.atan2(-fy, fx)))

    def wrench(self) -> tuple[float, float, float]:
        fx, fy = self.out
        return fx, fy, self.x * fy - self.y * fx
