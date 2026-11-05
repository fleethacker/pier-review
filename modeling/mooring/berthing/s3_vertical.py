"""S3b: pure vertical motion. Heave follows the tide (prescribed); roll/pitch are not simulated
unless supplied stability inputs are complete. No GM, inertia or hydrodynamic coefficient is invented.

Simulator wiring: each step
    v = vertical_state(env.water_level_ft_mllw, t_s=t, stability=None)
    pose.heave_mllw_ft = v.heave_mllw_ft; dofs.heave = v.heave_dof; dofs.roll/pitch = v.roll_dof/v.pitch_dof
(roll/pitch values stay None while their DOF is "not_simulated".)
heave_mllw_ft = water level above MLLW + waterline_offset_ft (default 0: reference waterline on the surface).
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Dof = Literal["simulated", "prescribed", "not_simulated", "unknown"]


@dataclass(frozen=True)
class StabilityInputs:
    """Supplied (never defaulted) loading/stability data. `roll_pitch(t_s)` returns (roll_deg, pitch_deg)."""
    gm_ft: float | None
    displacement_lt: float | None
    roll_pitch: Callable[[float], tuple[float, float]] | None

    def complete(self) -> bool:
        return (self.roll_pitch is not None and self.gm_ft is not None and self.displacement_lt is not None
                and self.gm_ft > 0 and self.displacement_lt > 0)


@dataclass(frozen=True)
class VerticalState:
    heave_mllw_ft: float | None
    heave_dof: Dof
    roll_deg: float | None
    pitch_deg: float | None
    roll_dof: Dof
    pitch_dof: Dof
    note: str


def tide_heave(water_level_ft_mllw: float | None, waterline_offset_ft: float = 0.0) -> float | None:
    if water_level_ft_mllw is None or not math.isfinite(water_level_ft_mllw):
        return None
    return water_level_ft_mllw + waterline_offset_ft


def vertical_state(water_level_ft_mllw: float | None, *, t_s: float = 0.0, waterline_offset_ft: float = 0.0,
                   stability: StabilityInputs | None = None) -> VerticalState:
    h = tide_heave(water_level_ft_mllw, waterline_offset_ft)
    hd: Dof = "prescribed" if h is not None else "not_simulated"
    if stability is not None and stability.complete():
        r, p = stability.roll_pitch(t_s)  # type: ignore[misc]
        return VerticalState(h, hd, r, p, "simulated", "simulated", "roll/pitch from supplied stability model")
    return VerticalState(h, hd, None, None, "not_simulated", "not_simulated",
                         "heave prescribed from water level; roll/pitch not simulated (no supplied stability inputs)")
