"""Reusable mooring line templates, independent of any mock or real solver.

Moved unchanged from `moored/mock/optimizer.py` so examples and callers do not depend on a mock implementation.
"""

from mooring import refdata
from mooring.core.schemas import Berth, MooringConfig, MooringLine, ShipClass

# (line number, bitt number, role, target lead along the ship in ft: + forward)
TEMPLATE = [
    (1, 1, "bow", 100.0),
    (2, 2, "spring_aft", -140.0),
    (3, 3, "breast", 0.0),
    (4, 4, "breast", 0.0),
    (5, 5, "spring_fwd", 140.0),
    (6, 6, "stern", -100.0),
]


def template_config(ship: ShipClass, berth: Berth, side_to: str, ship_x_ft: float, spec_id: str,
                    parts: dict[int, int] | None = None, excluded: set[str] | None = None) -> MooringConfig:
    s = "S" if side_to == "starboard" else "P"
    fittings = {f.fitting_id: f for f in ship.fittings}
    if not fittings:
        raise refdata.InvalidReference(f"{ship.class_id} has no fittings in the seed data yet; use DDG-51-FIIA.")
    bow_dir = 1 if side_to == "starboard" else -1
    usable = [f for f in berth.fittings if f.condition == "good" and not f.occupied_by
              and f.kind.startswith("bollard") and f.fitting_id not in (excluded or set())]
    back_row = [f for f in usable if f.y_ft < -20]  # set-back bollards give breast lines useful length
    used: set[str] = set()
    chosen: dict[int, MooringLine] = {}
    # Breasts first (they need fittings abeam), then bow and stern, then springs.
    priority = {"breast": 0, "bow": 1, "stern": 1, "spring_aft": 2, "spring_fwd": 2}
    for n, bitt_no, role, lead in sorted(TEMPLATE, key=lambda t: priority[t[2]]):
        bitt = fittings[f"BITT-{bitt_no}{s}"]
        chock = fittings.get(bitt.paired_chock_id or "", bitt)
        target_x = ship_x_ft + bow_dir * (chock.x_ft + lead)
        pool = [f for f in (back_row if role == "breast" and back_row else usable) if f.fitting_id not in used]
        choice = min(pool, key=lambda f: abs(f.x_ft - target_x))
        used.add(choice.fitting_id)
        chosen[n] = MooringLine(line_number=n, role=role, spec_id=spec_id, parts=(parts or {}).get(n, 1),
                                ship_fitting_id=bitt.fitting_id, pier_fitting_id=choice.fitting_id)
    return MooringConfig(side_to=side_to, ship_x_ft=ship_x_ft, lines=[chosen[n] for n in sorted(chosen)])
