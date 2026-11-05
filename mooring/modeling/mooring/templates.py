"""Geometry-based draft line arrangements, independent of any solver.

Templates are starting configurations, not validated procedures or feasible-plan claims.
The supported arrangement requires two rated bitts forward and aft on the chosen side.
"""

from dataclasses import dataclass

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


class TemplateUnsupported(refdata.InvalidReference):
    """An explicit arrangement/data blocker, suitable for an API capability reason."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class TemplateSlot:
    line_number: int
    ship_fitting_id: str
    role: str
    lead_ft: float


def ship_template_slots(ship: ShipClass, side_to: str) -> list[TemplateSlot]:
    """Select by actual side/coordinates, never by class-specific fitting ID syntax.

    Lead offsets are draft search targets in feet, not line reach/strength or operational
    limits. Three bitts per half reproduce the existing six-line arrangement; other
    supported counts retain both breast and spring restraint forward and aft.
    """
    if side_to not in ("port", "starboard"):
        raise TemplateUnsupported("INVALID_SIDE", "side_to must be port or starboard")
    if not ship.fittings:
        raise TemplateUnsupported("NO_FITTINGS", f"{ship.class_id} has no fitting layout")
    fittings = {f.fitting_id: f for f in ship.fittings}
    if len(fittings) != len(ship.fittings):
        raise TemplateUnsupported("DUPLICATE_SHIP_FITTING", "Fitting IDs must be unique")
    bitts = sorted((f for f in ship.fittings if f.side == side_to and f.kind in ("bitt", "recessed_bitt")),
                   key=lambda f: (-f.x_ft, f.fitting_id))
    if len(bitts) > 32:
        raise TemplateUnsupported("TEMPLATE_SIZE_UNSUPPORTED", "Draft templates support at most 32 bitts per side")
    for bitt in bitts:
        if (side_to == "port" and bitt.y_ft < 0 or side_to == "starboard" and bitt.y_ft > 0
                or abs(bitt.x_ft) > ship.loa_ft / 2 or abs(bitt.y_ft) > ship.beam_ft / 2):
            raise TemplateUnsupported("FITTING_FRAME_CONFLICT", f"{bitt.fitting_id} conflicts with the declared hull/ship frame")
        if bitt.swl_lbf is None or bitt.swl_lbf <= 0:
            raise TemplateUnsupported("MISSING_SWL", f"{bitt.fitting_id} needs a positive safe working load")
        if bitt.paired_chock_id:
            chock = fittings.get(bitt.paired_chock_id)
            if chock is None or chock.kind != "chock" or chock.side not in (side_to, "centerline"):
                raise TemplateUnsupported("INVALID_CHOCK", f"{bitt.fitting_id} needs a valid same-side paired chock")
    def lead_x(fitting):
        return fittings[fitting.paired_chock_id].x_ft if fitting.paired_chock_id else fitting.x_ft

    bitts.sort(key=lambda f: (-lead_x(f), f.fitting_id))
    forward = [f for f in bitts if lead_x(f) > 0]
    aft = [f for f in bitts if lead_x(f) <= 0]
    if len(forward) < 2 or len(aft) < 2:
        raise TemplateUnsupported("INSUFFICIENT_SIDE_FITTINGS",
                                  f"{ship.class_id} {side_to} needs at least two rated bitts forward and aft")
    if len({lead_x(f) for f in bitts}) != len(bitts):
        raise TemplateUnsupported("AMBIGUOUS_FITTING_ORDER", "Bitts at the same longitudinal station need an explicit reviewed arrangement")
    fwd_roles = ["breast", "spring_aft"] if len(forward) == 2 else ["bow", "spring_aft"] + ["breast"] * (len(forward) - 2)
    aft_roles = ["spring_fwd", "breast"] if len(aft) == 2 else ["breast"] * (len(aft) - 2) + ["spring_fwd", "stern"]
    lead = {"bow": 100.0, "stern": -100.0, "spring_aft": -140.0, "spring_fwd": 140.0, "breast": 0.0}
    return [TemplateSlot(n, f.fitting_id, role, lead[role])
            for n, (f, role) in enumerate(zip(forward + aft, fwd_roles + aft_roles), 1)]


def template_config(ship: ShipClass, berth: Berth, side_to: str, ship_x_ft: float, spec_id: str,
                    parts: dict[int, int] | None = None, excluded: set[str] | None = None) -> MooringConfig:
    slots = ship_template_slots(ship, side_to)
    fittings = {f.fitting_id: f for f in ship.fittings}
    spec = refdata.line(spec_id)
    if parts and (set(parts) - {s.line_number for s in slots} or any(v not in (1, 2, 3) for v in parts.values())):
        raise TemplateUnsupported("INVALID_TEMPLATE_PARTS", "Parts must refer to selected lines and be 1, 2 or 3")
    if len({i.spec_id for i in ship.standard_line_outfit}) != len(ship.standard_line_outfit):
        raise TemplateUnsupported("DUPLICATE_LINE_INVENTORY", "Line inventory specs must be unique")
    inventory = {i.spec_id: i.count for i in ship.standard_line_outfit}
    needed = sum((parts or {}).get(s.line_number, 1) for s in slots)
    if inventory.get(spec_id, 0) < needed:
        raise TemplateUnsupported("INSUFFICIENT_LINE_INVENTORY", f"Draft needs {needed} parts of {spec_id}; available {inventory.get(spec_id, 0)}")
    for slot in slots:
        fitting = fittings[slot.ship_fitting_id]
        if fitting.max_rope_circ_in is not None and spec.size_circ_in > fitting.max_rope_circ_in:
            raise TemplateUnsupported("LINE_SIZE_INCOMPATIBLE", f"{spec_id} exceeds {fitting.fitting_id}'s line size limit")
    bow_dir = 1 if side_to == "starboard" else -1
    usable = [f for f in berth.fittings if f.condition == "good" and not f.occupied_by
              and f.kind.startswith("bollard") and f.fitting_id not in (excluded or set())]
    if len({f.fitting_id for f in usable}) != len(usable):
        raise TemplateUnsupported("DUPLICATE_PIER_FITTING", "Pier fitting IDs must be unique")
    if len(usable) < len(slots):
        raise TemplateUnsupported("INSUFFICIENT_PIER_FITTINGS", f"Need {len(slots)} distinct usable bollards; found {len(usable)}")
    back_row = [f for f in usable if f.y_ft < -20]  # set-back bollards give breast lines useful length
    used: set[str] = set()
    chosen: dict[int, MooringLine] = {}
    # Breasts first (they need fittings abeam), then bow and stern, then springs.
    priority = {"breast": 0, "bow": 1, "stern": 1, "spring_aft": 2, "spring_fwd": 2}
    for slot in sorted(slots, key=lambda s: priority[s.role]):
        n, role, lead = slot.line_number, slot.role, slot.lead_ft
        bitt = fittings[slot.ship_fitting_id]
        chock = fittings.get(bitt.paired_chock_id or "", bitt)
        target_x = ship_x_ft + bow_dir * (chock.x_ft + lead)
        pool = [f for f in (back_row if role == "breast" and back_row else usable) if f.fitting_id not in used]
        if not pool:
            raise TemplateUnsupported("INSUFFICIENT_PIER_FITTINGS", f"No unused fitting in the supported {role} selection pool")
        choice = min(pool, key=lambda f: (abs(f.x_ft - target_x), f.fitting_id))
        used.add(choice.fitting_id)
        chosen[n] = MooringLine(line_number=n, role=role, spec_id=spec_id, parts=(parts or {}).get(n, 1),
                                ship_fitting_id=bitt.fitting_id, pier_fitting_id=choice.fitting_id)
    return MooringConfig(side_to=side_to, ship_x_ft=ship_x_ft, lines=[chosen[n] for n in sorted(chosen)])
