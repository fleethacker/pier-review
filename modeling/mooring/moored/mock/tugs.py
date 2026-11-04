"""Mock holding-tug plan for a moored ship (Phase 1): tugs relieve lines that exceed their working limit."""

from mooring import refdata
from mooring.core.envelopes import envelope
from mooring.core.geometry import ship_heading_true
from mooring.core.schemas import AnalyzeRequest, HoldTugRequest, TugPlanResponse
from mooring.tugs import size_tugs

from .solver import solve


def hold_plan(req: HoldTugRequest) -> TugPlanResponse:
    s = solve(AnalyzeRequest(**req.model_dump(exclude={"margin", "available_tug_ids"})), run_rules=False)
    over = [r for r in s.result.lines if r.pct_wll > 100]
    deficit = sum(r.tension_lbf * (1 - 100 / r.pct_wll) * r.breast_efficiency for r in over)
    required = deficit * (1 + req.margin)
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    heading = ship_heading_true(berth, req.config.side_to)
    rationale = ([f"Lines {', '.join(str(r.line_number) for r in over)} exceed WLL; tugs relieve about "
                  f"{deficit:,.0f} lbf."] if over else ["All lines within WLL; no holding tugs needed."])
    result = size_tugs(ship, required, False, req.config.side_to, heading, req.available_tug_ids, rationale)
    return envelope(TugPlanResponse, model="mooring.tugs.hold", request=req, result=result,
                    status="GREEN" if result.feasible else "RED", assumptions=["Deficit from the mock solver."])
