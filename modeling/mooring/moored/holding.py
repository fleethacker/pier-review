"""Holding-tug assistance for a moored ship (S09).

Tugs are sized by re-solving the real equilibrium with candidate tug forces applied and checking every line, fitting and
fender against its limit at the *solved* pose. There is no scalar sum of overloads: a tug that cures sway but worsens yaw
fails the check. Candidates are tugs on water-side push points acting against the dominant lateral load, at a uniform
fraction of each tug's rating (ratings from the catalog, not certified). The smallest plan that passes is chosen: fewest
tugs, then least total force. Every reported assisted utilization comes from a fresh solve whose envelope is stored and
referenced by `assisted_result_id`. If no candidate passes, the best attempt is returned as infeasible: that says the
search found no plan, not that none exists.
"""

import dataclasses
from itertools import combinations, permutations

from mooring import refdata
from mooring.core.envelopes import envelope, status_with_validity
from mooring.core.schemas import (
    AnalyzeRequest, HoldTugRequest, PushPointForce, TugAssignment, TugPlanResponse, TugPlanResult, Validity, ValidityReason,
)
from mooring.loads.validity import merge_reasons
from mooring.rules.nstm582 import design_factor

from . import solver
from .envelopes_real import utilization

LEVELS = [round(0.1 * i, 1) for i in range(1, 11)]


def _util(system, pose, df):
    return max(utilization(system, pose, df), key=lambda e: e[1])


def hold_plan(req: HoldTugRequest) -> TugPlanResponse:
    from mooring.moored import equilibrium as eq

    base_req = AnalyzeRequest(**req.model_dump(exclude={"margin", "available_tug_ids"}))
    system, sol, specs = solver.solve_request(base_req)
    df = design_factor(req.mst)
    target = 100.0 / (1.0 + req.margin)
    ship = system.ship
    try:
        fleet = [refdata.tug(t) for t in req.available_tug_ids] if req.available_tug_ids else refdata.tugs()
    except refdata.NotFound as e:
        raise refdata.InvalidReference(str(e)) from None
    used_tugs = {t.tug_id for t in req.tugs}
    used_points = {t.push_point_id for t in req.tugs}
    fleet = [t for t in fleet if t.tug_id not in used_tugs]
    water_side = "port" if req.config.side_to == "starboard" else "starboard"
    points = [p for p in ship.push_points if p.side == water_side and p.push_point_id not in used_points]
    rationale: list[str] = []
    base_worst = _util(system, sol.pose, df) if sol.converged else ("pose", float("inf"), "undetermined")
    chosen = None
    attempts = 0
    if not sol.converged:
        rationale.append("The unassisted equilibrium did not converge; tug sizing is undetermined.")
    elif base_worst[1] <= target:
        rationale.append(f"Highest utilization {base_worst[1]:.0f}% is within the {target:.0f}% target; no holding tugs needed.")
        chosen = ([], 0.0, base_worst)
    else:
        applied_fy = system.applied_wrench(sol.pose).fy_lbf
        mode = "push" if applied_fy > 0 else "pull"   # push onto the pier when the load is off-pier, else pull off
        rationale.append(f"{base_worst[0]} at {base_worst[1]:.0f}% ({base_worst[2]}); target {target:.0f}% (margin {req.margin:.0%}). "
                         f"Tugs on {water_side}-side points will {mode}.")
        best_try = None
        for k in range(1, min(len(fleet), len(points)) + 1):
            for tug_set in combinations(fleet, k):
                for pt_set in permutations(points, k):
                    for phi in LEVELS:
                        attempts += 1
                        assigns = [TugAssignment(tug_id=t.tug_id, push_point_id=p.push_point_id, mode=mode,
                                                 force_lbf=round(phi * min(t.bollard_pull_ahead_lbf if mode == "push" else t.bollard_pull_astern_lbf, p.max_force_lbf)))
                                   for t, p in zip(tug_set, pt_set)]
                        cand = dataclasses.replace(system, tugs=system.tugs + eq.build_system(
                            system.ship, system.berth, system.cfg, specs, system.env, loading=system.loading, lines_wet=base_req.lines_wet,
                            tugs=assigns, install_water_level_ft=base_req.installed_at_water_level_mllw_ft).tugs)
                        s2 = eq.solve(cand, sol.pose)
                        if not s2.converged:
                            continue
                        w = _util(cand, s2.pose, df)
                        total = sum(a.force_lbf for a in assigns)
                        if best_try is None or w[1] < best_try[2][1]:
                            best_try = (assigns, total, w)
                        if w[1] <= target:
                            chosen = (assigns, total, w)
                            break
                    if chosen:
                        break
                if chosen:
                    break
            if chosen:
                break
        if chosen is None:
            chosen = None
            best = best_try
    if chosen is not None:
        assigns, total, worst_el = chosen
        final_req = base_req.model_copy(update={"tugs": list(req.tugs) + assigns})
        final = solver.analyze(final_req)  # fresh solve; stored and cited
        feasible = True
        rationale.append(f"Assisted worst element {worst_el[0]} at {worst_el[1]:.0f}% from a fresh equilibrium solve" + (f" with {len(assigns)} tug(s)." if assigns else "."))
    else:
        assigns, total, worst_el = (best[0], best[1], best[2]) if sol.converged and best_try else ([], 0.0, base_worst)
        final = solver.analyze(base_req.model_copy(update={"tugs": list(req.tugs) + assigns}))
        feasible = False
        rationale.append(f"No tested plan reached the {target:.0f}% target ({attempts} candidates with the requested fleet and water-side points); "
                         "the best attempt is shown. This is a search result, not proof that no plan exists.")
    by_point = [PushPointForce(push_point_id=a.push_point_id, force_lbf=a.force_lbf, mode=a.mode) for a in assigns]
    tug_by = {t.tug_id: t for t in fleet}
    pct = max([l.pct_wll for l in final.result.lines] + [p.pct for p in final.result.pier_fittings] + [s.pct or 0 for s in final.result.ship_fittings])
    result = TugPlanResult(required_lateral_lbf=round(total), required_by_point=by_point, assignments=assigns, total_bollard_pull_lbf=round(total),
                           total_power_hp=round(sum(tug_by[a.tug_id].power_hp for a in assigns)), recommended_tug_count=len(assigns),
                           feasible=feasible, rationale=rationale, binding_constraints=[] if feasible else [f"{worst_el[0]} ({worst_el[2]}) still above target"],
                           ratings_basis="Catalog bollard pull (seed/estimated), not certified ratings; uniform fraction of rating per tug.",
                           assisted_max_pct_wll=round(pct, 1), assisted_result_id=final.result_id)
    validity = final.validity
    reasons = list(validity.reasons)
    if any(t.provenance.confidence != "published" for t in tug_by.values()) and assigns:
        reasons.append(ValidityReason(code="TUG_RATINGS_NOT_CERTIFIED", affected_components=[a.tug_id for a in assigns],
                                      message="Catalog bollard pull is not a certified rating."))
    if not feasible:
        reasons.append(ValidityReason(code="NO_TESTED_PLAN_MEETS_TARGET", affected_components=["fleet"],
                                      message="No candidate in the search met the utilization target; undetermined, not proven infeasible."))
    state = "invalid" if validity.state == "invalid" else "limited" if reasons else "valid"
    v = Validity(state=state, reasons=merge_reasons(reasons), diagnostics=validity.diagnostics)
    return envelope(TugPlanResponse, model="mooring.tugs.hold", request=req, result=result, backend="real", model_version="1.0.0",
                    status=status_with_validity("GREEN" if feasible else "RED", v), validity=v, manifest=final.manifest,
                    assumptions=["Candidates re-solved with the real equilibrium; utilization checked for every line, fitting and fender.",
                                 f"Utilization target {target:.0f}% = 100% / (1 + margin {req.margin:.0%}).", *solver.ASSUMPTIONS])
