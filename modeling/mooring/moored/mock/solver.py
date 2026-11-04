"""Mock static mooring analysis (M4).

Real: line geometry (lengths, lead angles, roles), utilization bookkeeping and the NSTM 582 rule checks.
Mock: load sharing. Lines act as linear springs (k = parts x MBS / (length x strain at break)) under the mock
environmental load, with no equilibrium solve. Workstream B replaces `solve` with the 3-DOF quasi-static solver.
"""

import math
from collections import defaultdict
from datetime import timedelta

from mooring import refdata
from mooring.core.geometry import LineGeometry, depth_at, line_geometry, ship_heading_true, ship_to_berth, standoff_ft
from mooring.core.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalyzeResult,
    FenderResult,
    LimitEnvelopePoint,
    LimitEnvelopeRequest,
    LimitEnvelopeResponse,
    LimitEnvelopeResult,
    LineResult,
    LineTension,
    MinMargin,
    Offset,
    PierFittingResult,
    Rule,
    ShipFittingResult,
    TendingAction,
    TideStep,
    TideSweepRequest,
    TideSweepResponse,
    TideSweepResult,
)
from mooring.rules.nstm582 import RULES, CheckContext, check_all, design_factor

from mooring.environment import mock as environment
from mooring.core.envelopes import envelope, status_from_pct, worst
from mooring.loads import compute_loads, mean_draft_ft, off_pier, range_findings

ASSUMPTIONS = [
    "Mock load sharing: lines are linear springs; no equilibrium solve, heave/roll ignored.",
    "Default pretension 2% of line breaking strength when none is given.",
]


class Solved:
    """Everything a mock solve produces; reused by the risk, tide and envelope mocks."""

    def __init__(self, result: AnalyzeResult, geoms: list[LineGeometry], stiffness: dict[int, float],
                 wll: dict[int, float], status: str):
        self.result, self.geoms, self.stiffness, self.wll, self.status = result, geoms, stiffness, wll, status


def solve(req: AnalyzeRequest, *, run_rules: bool = True) -> Solved:
    ship = refdata.ship(req.ship_class_id)
    berth = refdata.berth(req.berth_id)
    cfg = req.config
    env = req.environment
    heading = ship_heading_true(berth, cfg.side_to)
    depth = depth_at(berth, cfg.ship_x_ft) + env.water_level_mllw_ft
    loads = compute_loads(ship, req.loading, heading, env, depth)

    f_off = off_pier(loads.total.fy_lbf, cfg.side_to)
    for t in req.tugs:
        if t.mode == "push":
            f_off -= t.force_lbf  # tugs pushing the ship onto the pier relieve the lines
        elif t.mode == "pull":
            f_off += t.force_lbf
    f_long = loads.total.fx_lbf  # + = ship pushed forward

    try:
        geoms = [line_geometry(ln, ship, berth, cfg, env.water_level_mllw_ft) for ln in cfg.lines]
        specs = {ln.spec_id: refdata.line(ln.spec_id) for ln in cfg.lines}
    except (KeyError, refdata.NotFound) as e:
        raise refdata.InvalidReference(str(e)) from None

    df = design_factor(req.mst)
    mbs_eff, k, pre = {}, {}, {}
    for g in geoms:
        ln, spec = g.line, specs[g.line.spec_id]
        wet = spec.wet_strength_factor if req.lines_wet else 1.0
        mbs_eff[ln.line_number] = spec.mbs_lbf * ln.parts * wet
        k[ln.line_number] = ln.parts * spec.mbs_lbf / (g.length_ft * spec.load_elongation[-1][1])
        if ln.pretension_lbf is not None:
            pre[ln.line_number] = ln.pretension_lbf
        else:
            pre[ln.line_number] = 0.0 if ln.slack_ft else 0.02 * mbs_eff[ln.line_number]

    tension = dict(pre)
    sway = surge = 0.0
    lat = [g for g in geoms if g.lateral_factor > 0.05]
    if f_off > 0 and lat:
        sway = f_off / sum(k[g.line.line_number] * g.lateral_factor**2 for g in lat)
        for g in lat:
            tension[g.line.line_number] += k[g.line.line_number] * g.lateral_factor * sway
    if abs(f_long) > 0:
        # Pushed forward -> lines leading aft resist; pushed aft -> lines leading forward resist.
        resist = [g for g in geoms if g.longitudinal_factor > 0.05 and g.leads_forward == (f_long < 0)]
        if resist:
            d = abs(f_long) / sum(k[g.line.line_number] * g.longitudinal_factor**2 for g in resist)
            surge = d if f_long > 0 else -d
            for g in resist:
                tension[g.line.line_number] += k[g.line.line_number] * g.longitudinal_factor * d

    wll = {n: m / df for n, m in mbs_eff.items()}
    line_results = []
    for g in geoms:
        n = g.line.line_number
        pct_wll = 100 * tension[n] / wll[n]
        line_results.append(LineResult(
            line_number=n, role=g.role, tension_lbf=round(tension[n]), pct_mbs=round(100 * tension[n] / mbs_eff[n], 1),
            pct_wll=round(pct_wll, 1), horiz_angle_deg=round(g.horiz_angle_deg, 1), vert_angle_deg=round(g.vert_angle_deg, 1),
            breast_efficiency=round(g.breast_efficiency, 3), length_ft=round(g.length_ft, 1),
            status=status_from_pct(pct_wll)))

    pier_loads: dict[str, list[int]] = defaultdict(list)
    ship_loads: dict[str, list[int]] = defaultdict(list)
    for g in geoms:
        pier_loads[g.pier_fitting.fitting_id].append(g.line.line_number)
        ship_loads[g.ship_fitting.fitting_id].append(g.line.line_number)
    pier_by_id = {f.fitting_id: f for f in berth.fittings}
    pier_results = []
    for fid, nums in pier_loads.items():
        load = sum(tension[n] for n in nums)
        cap = pier_by_id[fid].capacity_nominal_lbf
        pct = 100 * load / cap
        pier_results.append(PierFittingResult(fitting_id=fid, load_lbf=round(load), capacity_lbf=cap, pct=round(pct, 1),
                                              lines=nums, status=status_from_pct(pct)))
    ship_by_id = {f.fitting_id: f for f in ship.fittings}
    ship_results = []
    for fid, nums in ship_loads.items():
        load = sum(tension[n] for n in nums)
        swl = ship_by_id[fid].swl_lbf
        pct = 100 * load / swl if swl else None
        ship_results.append(ShipFittingResult(fitting_id=fid, load_lbf=round(load), swl_lbf=swl,
                                              pct=round(pct, 1) if pct is not None else None, lines=nums,
                                              status=status_from_pct(pct) if pct is not None else "GREEN"))

    half = ship.loa_ft / 2
    in_contact = [f for f in berth.fenders if abs(f.x_ft - cfg.ship_x_ft) <= half]
    fender_results = []
    for f in berth.fenders:
        r = (-f_off / len(in_contact)) if (f_off < 0 and f in in_contact) else 0.0
        comp = r / f.stiffness_lbf_per_ft
        fender_results.append(FenderResult(fender_id=f.fender_id, reaction_lbf=round(r), compression_ft=round(comp, 2),
                                           status="AMBER" if comp > 2 else "GREEN"))

    elements = [(f"line-{r.line_number}", r.pct_wll) for r in line_results]
    elements += [(p.fitting_id, p.pct) for p in pier_results]
    elements += [(s.fitting_id, s.pct) for s in ship_results if s.pct is not None]
    top = max(elements, key=lambda e: e[1]) if elements else ("none", 0.0)

    findings = []
    if run_rules:
        bow_x, _ = ship_to_berth(half, 0, ship, berth, cfg)
        findings = check_all(CheckContext(
            ship=ship, berth=berth, env=env, mst=req.mst, heading_true_deg=heading, geometries=geoms,
            line_results=line_results, specs=specs, pier_results=pier_results, ship_results=ship_results,
            bow_x_berth_ft=bow_x, bow_dir=1 if cfg.side_to == "starboard" else -1))
        # Load-model validity warnings (shallow water, fast current) travel with the analysis.
        findings += range_findings(depth, mean_draft_ft(ship, req.loading), env.current_speed_kt,
                                   [loads.current.coefficients.get("reynolds", 0.0)])[0]

    result = AnalyzeResult(
        offset=Offset(surge_ft=round(surge, 2), sway_ft=round(sway, 2), yaw_deg=0.0),
        lines=line_results, pier_fittings=pier_results, ship_fittings=ship_results, fenders=fender_results,
        min_margin=MinMargin(element_id=top[0], pct_wll=round(top[1], 1)), findings=findings)
    status = worst([r.status for r in line_results] + [p.status for p in pier_results] +
                   [s.status for s in ship_results] + [f.severity for f in findings])
    return Solved(result, geoms, k, wll, status)


def ignored_line_fields(req: AnalyzeRequest) -> list[str]:
    """Line fields the mock accepts for forward compatibility but does not model; never ignore silently."""
    notes = []
    for ln in req.config.lines:
        if ln.paid_out_unstretched_length_ft is not None:
            notes.append(f"line {ln.line_number}: paid_out_unstretched_length_ft is ignored by the mock solver.")
        if ln.condition is not None and (ln.condition == "wet") != req.lines_wet:
            notes.append(f"line {ln.line_number}: condition '{ln.condition}' is ignored; lines_wet={req.lines_wet} applies.")
    return notes


def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    s = solve(req)
    return envelope(AnalyzeResponse, model="mooring.solver.static", request=req, result=s.result, status=s.status,
                    assumptions=ASSUMPTIONS + [f"Design factor {design_factor(req.mst)} (MST {req.mst})."]
                    + ignored_line_fields(req),
                    warnings=[f for f in s.result.findings if f.severity != "INFO"])


def _element_pcts(s: Solved) -> dict[str, tuple[float, str]]:
    out = {f"line-{r.line_number}": (r.pct_wll, "WLL") for r in s.result.lines}
    out.update({p.fitting_id: (p.pct, "fitting") for p in s.result.pier_fittings})
    out.update({f.fitting_id: (f.pct, "fitting") for f in s.result.ship_fittings if f.pct is not None})
    return out


def limit_envelope(req: LimitEnvelopeRequest) -> LimitEnvelopeResponse:
    """Mock: element utilization grows with wind speed squared above its calm-weather value."""
    berth = refdata.berth(req.berth_id)
    heading = ship_heading_true(berth, req.config.side_to)
    ref_kt = 30.0
    base_req = AnalyzeRequest(**{**req.model_dump(exclude={"step_deg"}), "environment": req.environment.model_copy(
        update={"wind_speed_kt": 0, "wind_gust_kt": 0, "current_speed_kt": 0}).model_dump()})
    calm = _element_pcts(solve(base_req, run_rules=False))
    points = []
    for rel in range(0, 360, req.step_deg):
        env = req.environment.model_copy(update={
            "wind_speed_kt": ref_kt, "wind_gust_kt": ref_kt, "current_speed_kt": 0,
            "wind_from_true_deg": (heading + rel) % 360})
        loaded = _element_pcts(solve(base_req.model_copy(update={"environment": env}), run_rules=False))
        best: tuple[float, str, str] | None = None
        for eid, (pct, mode) in loaded.items():
            p0 = calm.get(eid, (0.0, mode))[0]
            if pct - p0 > 0.5 and p0 < 100:
                v = ref_kt * math.sqrt((100 - p0) / (pct - p0))
                if best is None or v < best[0]:
                    best = (v, eid, mode)
        if best:
            points.append(LimitEnvelopePoint(wind_rel_deg=rel, limit_wind_kt=round(best[0], 1),
                                             first_failure_element=best[1], failure_mode=best[2]))
        else:
            points.append(LimitEnvelopePoint(wind_rel_deg=rel, limit_wind_kt=None, first_failure_element=None,
                                             failure_mode="none"))
    limited = [p for p in points if p.limit_wind_kt is not None]
    worst_pt = min(limited, key=lambda p: p.limit_wind_kt) if limited else points[0]
    status = "GREEN"
    if worst_pt.limit_wind_kt is not None:
        if worst_pt.limit_wind_kt < req.environment.wind_gust_kt:
            status = "RED"
        elif worst_pt.limit_wind_kt < 1.25 * req.environment.wind_gust_kt:
            status = "AMBER"
    return envelope(LimitEnvelopeResponse, model="mooring.solver.envelope", request=req,
                    result=LimitEnvelopeResult(points=points, worst=worst_pt), status=status,
                    assumptions=["Mock: utilization scaled with wind speed squared from a 30 kt reference; current excluded."]
                    + ignored_line_fields(req))


def tide_sweep(req: TideSweepRequest) -> TideSweepResponse:
    berth = refdata.berth(req.berth_id)
    base_req = AnalyzeRequest(**req.model_dump(exclude={"from_utc", "to_utc", "step_min"}))
    first = solve(base_req, run_rules=False)
    t0 = {r.line_number: r.tension_lbf for r in first.result.lines}
    l0 = {g.line.line_number: g.length_ft for g in first.geoms}
    ship = refdata.ship(req.ship_class_id)
    offset = defaultdict(float)  # length paid out (+) or taken in (-) by tending
    steps, tending = [], []
    t = req.from_utc
    stations = (berth.env_station_ids.wind, berth.env_station_ids.current, berth.env_station_ids.water_level)
    while t <= req.to_utc and len(steps) < 500:
        wl = environment.synthetic(t, "forecast", stations).water_level_mllw_ft
        tensions = []
        for g in first.geoms:
            n = g.line.line_number
            L = line_geometry(g.line, ship, berth, req.config, wl).length_ft
            T = max(0.0, t0[n] + first.stiffness[n] * (L - l0[n] - offset[n]))
            if T > 0.8 * first.wll[n]:
                amount = (T - 0.5 * first.wll[n]) / first.stiffness[n]
                tending.append(TendingAction(at_utc=t, line_number=n, action="slack", amount_ft=round(amount, 2)))
                offset[n] += amount
                T = 0.5 * first.wll[n]
            elif T < 500:
                amount = (0.05 * first.wll[n] - T) / first.stiffness[n]
                tending.append(TendingAction(at_utc=t, line_number=n, action="heave", amount_ft=round(amount, 2)))
                offset[n] -= amount
                T = 0.05 * first.wll[n]
            tensions.append(LineTension(line_number=n, tension_lbf=round(T)))
        steps.append(TideStep(valid_at_utc=t, water_level_mllw_ft=wl, lines=tensions))
        t += timedelta(minutes=req.step_min)
    status = "AMBER" if tending else "GREEN"
    return envelope(TideSweepResponse, model="mooring.solver.tide_sweep", request=req,
                    result=TideSweepResult(steps=steps, tending=tending), status=status,
                    assumptions=["Mock tide curve; tension change = line stiffness x length change.",
                                 "Tending slacks to 50% WLL above 80% WLL, heaves to 5% WLL below 500 lbf."]
                    + ignored_line_fields(req))


def rules() -> list[Rule]:
    return RULES


__all__ = ["analyze", "limit_envelope", "tide_sweep", "rules", "solve", "standoff_ft"]
