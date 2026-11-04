"""Mock line configuration optimizer (M7, moored phase).

A fixed six-line template per ship (bow, after bow spring, two breasts, forward quarter spring, stern)
snapped to the nearest free pier fittings, offered in three variants and scored with the mock solver.
Workstream D replaces it with a search over fitting assignments and line parts.
"""

import math

from mooring import refdata
from mooring.core.geometry import ship_heading_true
from mooring.core.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    Berth,
    Candidate,
    EnvironmentSnapshot,
    MooringConfig,
    MooringLine,
    RecommendRequest,
    RecommendResponse,
    RecommendResult,
    ShipClass,
)
from mooring.rules.nstm582 import MST_LIMITS

from mooring.core.envelopes import envelope

from mooring.templates import TEMPLATE, template_config  # noqa: F401  (re-exported: moved out of the mock)

from .solver import solve

def design_environment(berth: Berth, side_to: str, mst: str, water_level_ft: float = 0.0) -> EnvironmentSnapshot:
    """MST design condition with wind and current both pushing the ship off the pier (NSTM Table 582-1-1)."""
    wind_kt, current_kt = max(MST_LIMITS[mst])
    heading = ship_heading_true(berth, side_to)
    pier_side = (heading + (90 if side_to == "starboard" else 270)) % 360  # bearing from ship to pier
    return EnvironmentSnapshot(source="scenario", wind_speed_kt=wind_kt, wind_gust_kt=wind_kt,
                               wind_from_true_deg=pier_side, current_speed_kt=current_kt,
                               current_set_true_deg=(pier_side + 180) % 360, water_level_mllw_ft=water_level_ft)


def recommend(req: RecommendRequest) -> RecommendResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    ship_x = req.ship_x_ft if req.ship_x_ft is not None else berth.face_length_ft / 2
    outfit = req.available_lines or ship.standard_line_outfit
    nylon = next((i.spec_id for i in outfit if "NYLON" in i.spec_id), outfit[0].spec_id if outfit else "NYLON-DB-7IN")
    aramid = next((i.spec_id for i in outfit if "ARAMID" in i.spec_id), None)
    design_env = design_environment(berth, req.side_to, req.design_mst)
    excluded = set(req.excluded_fitting_ids)
    variants = [("single part " + nylon, nylon, None),
                ("springs and breasts doubled up (3 parts) " + nylon, nylon, {2: 3, 3: 3, 4: 3, 5: 3}),
                ("all lines doubled up (3 parts) " + nylon, nylon, {n: 3 for n in range(1, 7)})]
    if aramid:
        variants.insert(1, ("single part " + aramid, aramid, None))
    candidates = []
    for label, spec, parts in variants[: req.max_candidates]:
        cfg = template_config(ship, berth, req.side_to, ship_x, spec, parts, excluded)
        if req.locked_lines:
            locked = {ln.line_number: ln for ln in req.locked_lines}
            cfg.lines = [locked.get(ln.line_number, ln) for ln in cfg.lines]
        cfg.config_id = f"cfg-{len(candidates) + 1}"
        areq = AnalyzeRequest(ship_class_id=ship.class_id, loading=req.loading, berth_id=berth.berth_id,
                              config=cfg, environment=design_env, mst=req.design_mst)
        s = solve(areq)
        env = envelope(AnalyzeResponse, model="mooring.solver.static", request=areq, result=s.result,
                       status=s.status)
        top = s.result.min_margin
        limit = (design_env.wind_speed_kt * math.sqrt(100 / top.pct_wll)) if top.pct_wll > 0 else None
        candidates.append(Candidate(
            config=cfg, min_margin_pct_wll=top.pct_wll, limit_wind_kt_worst=round(limit, 1) if limit else None,
            line_count=len(cfg.lines), analysis_result_id=env.result_id,
            why=[f"Template: {label}.", f"Highest utilization {top.pct_wll:.0f}% ({top.element_id}) at MST "
                 f"{req.design_mst} design wind {design_env.wind_speed_kt:.0f} kt off the pier."]))
    candidates.sort(key=lambda c: c.min_margin_pct_wll)
    best = candidates[0].min_margin_pct_wll if candidates else 999
    status = "GREEN" if best <= 80 else "AMBER" if best <= 100 else "RED"
    return envelope(RecommendResponse, model="mooring.planning.optimizer", request=req,
                    result=RecommendResult(candidates=candidates, design_environment=design_env), status=status,
                    assumptions=["Mock optimizer: fixed six-line template snapped to the nearest good bollards."])
