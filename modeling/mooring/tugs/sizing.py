"""Compatibility wrapper for the original lateral-force tug sizing (M6).

`size_tugs` keeps its signature for existing callers and now delegates to the wrench allocator (yaw-balanced, unique
assignment, rating-limited). New code should call `mooring.tugs.allocation.allocate` with a full wrench.
"""

from mooring import refdata
from mooring.core.schemas import ShipClass, TugPlanResult

from .allocation import allocate


def size_tugs(ship: ShipClass, required: float, onto_pier: bool, side_to: str, heading: float,
              tug_ids: list[str] | None, rationale: list[str]) -> TugPlanResult:
    """Assign tugs to carry `required` lbf laterally. onto_pier=True means tugs must pull the ship off."""
    water_is_port = side_to == "starboard"            # the water is on the ship's port side when starboard side to
    toward_water = 1.0 if water_is_port else -1.0     # ship +y is port
    fy = required * toward_water * (1.0 if onto_pier else -1.0)
    fleet = [refdata.tug(t) for t in tug_ids] if tug_ids else refdata.tugs()
    plan, _ = allocate(ship, (0.0, fy, 0.0), fleet, heading_true_deg=heading)
    plan.rationale = rationale + plan.rationale
    return plan
