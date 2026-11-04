"""Mock line-handling sequence (M7, berthing phase): a rule table based on NSTM 582-2.4.6.

Workstream D replaces it with a rule table reviewed by a deck officer or pilot.
"""

from mooring import refdata
from mooring.core.envelopes import envelope
from mooring.core.schemas import SequenceRequest, SequenceResponse, SequenceResult, SequenceStep, ShipClass


def _station(ship: ShipClass, x_ft: float) -> str:
    if x_ft > 0.25 * ship.loa_ft:
        return "forecastle"
    if x_ft < -0.25 * ship.loa_ft:
        return "fantail"
    return "waist"


def sequence(req: SequenceRequest) -> SequenceResponse:
    ship = refdata.ship(req.ship_class_id)
    fittings = {f.fitting_id: f for f in ship.fittings}
    lines = {ln.line_number: ln for ln in req.config.lines}

    def station(n: int) -> str:
        f = fittings.get(lines[n].ship_fitting_id)
        return _station(ship, f.x_ft) if f else "waist"

    order = [n for n in (2, 5, 3, 4, 1, 6) if n in lines] + sorted(n for n in lines if n not in (1, 2, 3, 4, 5, 6))
    tugs_holding = req.tug_plan_result_id is not None
    steps: list[SequenceStep] = []

    def add(line: int | None, action: str, st: str, trigger: str, caution: str | None = None,
            ref: str = "NSTM 582-2.4.6") -> None:
        steps.append(SequenceStep(step=len(steps) + 1, line_number=line, action=action, station=st, crews=1,
                                  trigger=trigger, caution=caution, reference=ref))

    for i, n in enumerate(order):
        trig = "Bridge orders first line over" if i == 0 else f"Line {order[i - 1]} on its bollard"
        add(n, "pass", station(n), trig)
        add(n, "secure_pier", "pier", f"Line {n} eye ashore",
            ref="NSTM 582-2.4.6.3")
        if tugs_holding and lines[n].role in ("breast", None):
            add(n, "hold", station(n), "Tugs holding the ship alongside",
                caution="Keep this line slack-tended; don't take it to power until the tugs ease off.",
                ref="NSTM 582-2.2.3.1")
    add(None, "hold", "bridge", "All lines on their bollards; tugs ease off" if tugs_holding else "All lines on their bollards")
    for n in order:
        add(n, "take_to_power", station(n), "Bridge orders lines taken to power", ref="NSTM 582-2.4.6.5")
        if lines[n].parts > 1:
            add(n, "double_up", station(n), f"Line {n} tensioned", ref="NSTM 582-2.4.6.4")
    add(None, "tend", "bridge", "All lines doubled up and tensioned",
        caution="Equalize: slack the shortest lines about 1 ft; pre-tension lines over 100 ft.",
        ref="NSTM 582-2.4.4.1.c")
    crews = max(4, min(len(lines), 8))
    if req.line_handling_crews < 4:
        steps[0].caution = f"Only {req.line_handling_crews} crews available; at least 4 are needed (NSTM 582-2.4.6.1)."
    status = "AMBER" if req.line_handling_crews < crews else "GREEN"
    return envelope(SequenceResponse, model="mooring.planning.sequence", request=req,
                    result=SequenceResult(steps=steps, crews_required=crews), status=status,
                    assumptions=["Mock sequence rule table; to be reviewed by a deck officer or pilot."])
