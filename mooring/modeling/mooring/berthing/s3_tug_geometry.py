"""S3a: pure tug contact geometry, force limits and slew (no I/O, no simulator state).

Frames (docs/MOTION_FRAME_DESIGN.md): berth +x along the pier, +y off-pier; ship axes surge forward,
sway PORT, yaw CCW from berth +x. A tug at a hull push point acts normal to the hull, so in ship axes
F = (0, fy, 0) with fy>0 toward port; yaw moment about midships is Mz = x_pp * fy (ft*lbf, CCW positive).
Berth-frame force is the ship vector rotated CCW by yaw: (-fy sin(psi), fy cos(psi)).
Command direction_rel_deg follows the simulator: 90 = force toward starboard (tug on port side pushing),
270 = force toward port. Tug kinematic position is returned ONLY if a kinematic model is supplied.

Simulator wiring (per step, replacing tug_force/tug_wrench):
    cmd = TugCommand(tug_id, push_point_id, force_lbf, direction_rel_deg)
    pp = bind_push_point(cmd, ship.push_points, side_to=sc.side_to)        # raises TugGeometryError
    limits = TugLimits.from_specs(tug_spec, pp, slew_s=SLEW_SECONDS)
    cur = slew_force(prev_signed, target_signed(cmd), limits, dt)          # rate limited + clamped
    out = tug_contact(tug_id, pp, cur, yaw_rad, limits, requested=target_signed(cmd), kinematics=None)
    out.wrench_ship  # (fx, fy, mz); out.force_berth_lbf; out.tug_position_ft (None => not modeled)
    total_wrench(contacts) sums the ship-axis wrench over tugs.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

NOT_MODELED = "not_modeled"


class TugGeometryError(ValueError):
    """Invalid push point or command."""


@dataclass(frozen=True)
class PushPointGeom:
    push_point_id: str
    x_ft: float  # ship frame, + forward of midships
    side: Literal["port", "starboard"]
    max_force_lbf: float


@dataclass(frozen=True)
class TugCommand:
    tug_id: str
    push_point_id: str
    force_lbf: float  # magnitude, >= 0
    direction_rel_deg: float  # 90 or 270 (normal to hull)


@dataclass(frozen=True)
class TugLimits:
    """Signed sway-force bounds [lo, hi] (+port) and slew rate (lbf/s)."""
    lo_lbf: float
    hi_lbf: float
    slew_lbf_per_s: float

    @staticmethod
    def from_specs(tug, pp, *, slew_s: float) -> "TugLimits":
        """tug: object with bollard_pull_ahead_lbf/astern_lbf; pp: push point. Ahead = push, astern = pull."""
        if slew_s <= 0:
            raise TugGeometryError("slew_s must be positive")
        push = min(tug.bollard_pull_ahead_lbf, pp.max_force_lbf)
        pull = min(tug.bollard_pull_astern_lbf, pp.max_force_lbf)
        lo, hi = (-push, pull) if pp.side == "port" else (-pull, push)
        return TugLimits(lo, hi, max(abs(lo), abs(hi)) / slew_s)


@dataclass(frozen=True)
class TugContact:
    tug_id: str
    push_point_id: str
    signed_force_lbf: float  # ship sway, + port
    requested_force_lbf: float | None
    clamped: bool
    mode: Literal["push", "pull", "standby"]
    wrench_ship: tuple[float, float, float]  # (fx, fy, mz) about midships, ship axes
    force_berth_lbf: tuple[float, float]
    tug_position_ft: tuple[float, float] | None  # None => not modeled
    position_status: str  # "modeled" | "not_modeled"


def bind_push_point(cmd: TugCommand, push_points: Iterable, *, side_to: str,
                    allowed_ids: Iterable[str] | None = None) -> PushPointGeom:
    """Resolve a command to a permitted, water-side hull push point or raise TugGeometryError."""
    if not math.isfinite(cmd.force_lbf) or cmd.force_lbf < 0:
        raise TugGeometryError("force_lbf must be finite and >= 0")
    if cmd.direction_rel_deg not in (90, 270):
        raise TugGeometryError("only normal hull forces (90 or 270 degrees) are supported")
    allowed = None if allowed_ids is None else set(allowed_ids)
    found = next((p for p in push_points if p.push_point_id == cmd.push_point_id), None)
    if found is None or (allowed is not None and cmd.push_point_id not in allowed):
        raise TugGeometryError(f"push point {cmd.push_point_id!r} is not a permitted hull push point")
    if found.side == side_to:
        raise TugGeometryError("push point is on the pier side of the hull")
    return PushPointGeom(found.push_point_id, found.x_ft, found.side, found.max_force_lbf)


def target_signed(cmd: TugCommand) -> float:
    """Signed ship-sway force (+port): 90 deg = toward starboard (negative)."""
    return -cmd.force_lbf if cmd.direction_rel_deg == 90 else cmd.force_lbf


def clamp_force(signed: float, limits: TugLimits) -> tuple[float, bool]:
    c = min(max(signed, limits.lo_lbf), limits.hi_lbf)
    return c, c != signed


def slew_force(current: float, target: float, limits: TugLimits, dt: float) -> float:
    """Move current toward the (clamped) target by at most slew_rate*dt."""
    if dt < 0:
        raise TugGeometryError("dt must be >= 0")
    target, _ = clamp_force(target, limits)
    step = min(abs(target - current), limits.slew_lbf_per_s * dt)
    return current + math.copysign(step, target - current) if step else current


def tug_contact(tug_id: str, pp: PushPointGeom, signed_force_lbf: float, yaw_rad: float,
                limits: TugLimits, *, requested: float | None = None,
                kinematics: Callable[[], tuple[float, float]] | None = None) -> TugContact:
    """Force vector and yaw moment from contact geometry; the force is clamped to limits."""
    f, clamped = clamp_force(signed_force_lbf, limits)
    clamped = clamped or (requested is not None and clamp_force(requested, limits)[1])
    mz = pp.x_ft * f
    berth = (-f * math.sin(yaw_rad), f * math.cos(yaw_rad))
    pos = kinematics() if kinematics is not None else None
    mode = "standby" if f == 0 else ("push" if (f < 0) == (pp.side == "port") else "pull")
    return TugContact(tug_id, pp.push_point_id, f, requested, clamped, mode, (0.0, f, mz), berth,
                      pos, "modeled" if pos is not None else NOT_MODELED)


def total_wrench(contacts: Iterable[TugContact]) -> tuple[float, float, float]:
    w = [0.0, 0.0, 0.0]
    for c in contacts:
        for i in range(3):
            w[i] += c.wrench_ship[i]
    return (w[0], w[1], w[2])
