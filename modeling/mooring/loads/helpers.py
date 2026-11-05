"""Load helpers used by every phase. Real (not mock)."""

from mooring import refdata
from mooring.core.schemas import ShipClass


def mean_draft_ft(ship: ShipClass, loading: str) -> float:
    lc = refdata.loading(ship, loading)
    return (lc.draft_fwd_ft + lc.draft_aft_ft) / 2


def off_pier(total_fy_lbf: float, side_to: str) -> float:
    """Lateral force pushing the ship away from the pier (negative = onto the pier).

    Starboard side to: the pier is on the starboard side, so a force to port (+y) is off the pier.
    """
    return total_fy_lbf if side_to == "starboard" else -total_fy_lbf
