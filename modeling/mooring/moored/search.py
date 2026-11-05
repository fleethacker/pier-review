"""Constrained mooring-plan search (M7, S12).

Search space: for each line slot (a ship bitt and role from the template, or a locked line) choose a pier fitting among
the nearest usable ones, and choose one line spec and one parts pattern for the plan. Hard constraints (a candidate
violating any is never generated): inventory counts (each part uses one piece), ship-fitting rope size, fitting
condition/occupancy/exclusion, one line per pier fitting, breast lead under 45 degrees, locked lines kept. Every
candidate is then solved with the real equilibrium for *every* case: each MST wind/current alternative (not their
maximum), every supplied forecast condition, at every requested water level (lines installed at the first level). A
candidate is feasible only if every case converges and every line, fitting and fender stays within its limit. The
objective (lowest worst-case utilization, then fewer parts) is applied only among feasible candidates; if none is
feasible the best infeasible ones are returned and labeled infeasible. A bounded search that finds nothing has not
proven that nothing exists. Explicit holding-tug assignments are checked in every case. Forecast-only search is an explicit
restricted basis and does not claim MST design compliance. Real M5 risk is not used to rank candidates because its model is unqualified.
"""

import dataclasses
import itertools
import math
from dataclasses import dataclass, field
from collections import Counter

from mooring import refdata
from mooring.core.envelopes import envelope, status_with_validity
from mooring.core.geometry import ship_heading_true
from mooring.core.schemas import (
    AnalyzeRequest, Berth, Candidate, EnvironmentSnapshot, LimitEnvelopeRequest, LineSpec, MooringConfig, MooringLine,
    RecommendRequest, RecommendResponse, RecommendResult, SearchDiagnostics, ShipClass, Validity, ValidityReason,
)
from mooring.rules.nstm582 import MST_LIMITS, design_factor
from mooring.templates import TEMPLATE

from mooring.mechanics import equilibrium as eq
from . import solver
from .envelopes_real import utilization

MAX_LINE_FT = 300.0       # search bound, not an NSTM rule
MAX_BREAST_LEAD_DEG = 45.0  # NSTM 582-2.4.4.1.a.3 (breast leads)
PATTERNS = {"all single part": lambda role, n: 1, "breasts and springs 3-part": lambda role, n: 3 if role in ("breast", "spring_fwd", "spring_aft") else 1,
            "all 3-part": lambda role, n: 3}


@dataclass(frozen=True)
class Slot:
    line_number: int
    ship_fitting_id: str
    role: str
    lead_ft: float


def template_slots() -> list[Slot]:
    return [Slot(n, f"BITT-{bitt}@", role, lead) for n, bitt, role, lead in TEMPLATE]


@dataclass
class Outcome:
    ranked: list[tuple[tuple, MooringConfig, dict]]
    space_size: int
    evaluated: int
    strategy: str
    complete: bool
    notes: list[str] = field(default_factory=list)
    infeasible_reasons: list[str] = field(default_factory=list)


def design_cases(berth: Berth, side_to: str, mst: str, forecast: list[EnvironmentSnapshot], levels: list[float], *, include_mst: bool = True) -> list[tuple[str, EnvironmentSnapshot]]:
    """Every MST wind/current alternative (off-pier), every forecast condition, at every water level."""
    heading = ship_heading_true(berth, side_to)
    pier_side = (heading + (90 if side_to == "starboard" else 270)) % 360
    base: list[tuple[str, EnvironmentSnapshot]] = []
    for wind_kt, cur_kt in (MST_LIMITS[mst] if include_mst else []):
        base.append((f"MST {mst} design {wind_kt:g} kt wind / {cur_kt:g} kt current off the pier",
                     EnvironmentSnapshot(source="scenario", wind_speed_kt=wind_kt, wind_gust_kt=wind_kt, wind_from_true_deg=pier_side,
                                         current_speed_kt=cur_kt, current_set_true_deg=(pier_side + 180) % 360, water_level_mllw_ft=0.0)))
    for i, e in enumerate(forecast):
        base.append((f"forecast condition {i + 1} ({e.wind_gust_kt:g} kt gust from {e.wind_from_true_deg:g})", e))
    cases = [(f"{label} @ {lvl:+g} ft", env.model_copy(update={"water_level_mllw_ft": lvl})) for label, env in base for lvl in levels]
    # Retain actual coincident forecast tides as well as requested sensitivity levels.
    for i, env in enumerate(forecast):
        if env.water_level_mllw_ft not in levels:
            cases.append((f"forecast condition {i + 1} at actual tide {env.water_level_mllw_ft:+g} ft", env))
    return cases


def _slot_options(ship: ShipClass, berth: Berth, slot: Slot, side_to: str, ship_x: float, excluded: set[str], neighbors: int, side_tag: str):
    from mooring.core.geometry import ship_to_berth
    cfg0 = MooringConfig(side_to=side_to, ship_x_ft=ship_x, lines=[])
    bitt = next((f for f in ship.fittings if f.fitting_id == slot.ship_fitting_id.replace("@", side_tag)), None)
    if bitt is None:
        return None, []
    chock = next((f for f in ship.fittings if f.fitting_id == bitt.paired_chock_id), bitt)
    bow_dir = 1 if side_to == "starboard" else -1
    target_x = ship_x + bow_dir * (chock.x_ft + slot.lead_ft)
    usable = [f for f in berth.fittings if f.condition == "good" and not f.occupied_by and f.kind.startswith("bollard")
              and f.fitting_id not in excluded]
    pool = [f for f in usable if f.y_ft < -20] if slot.role == "breast" and any(f.y_ft < -20 for f in usable) else usable
    ranked = sorted(pool, key=lambda f: abs(f.x_ft - target_x))
    return bitt, [f.fitting_id for f in ranked[: neighbors * 2]]  # a few extra: lead filtering below may drop some


def search_plans(ship: ShipClass, berth: Berth, specs: dict[str, LineSpec], slots: list[Slot], cases: list[tuple[str, EnvironmentSnapshot]], *,
                 side_to: str, ship_x_ft: float, loading: str, mst: str, inventory: dict[str, int] | None = None,
                 locked: list[MooringLine] | None = None, excluded: set[str] | None = None, neighbors: int = 3, max_evals: int = 1500,
                 lines_wet: bool = True, install_level_ft: float = 0.0, side_tag: str | None = None, standoff_ft: float | None = None, tugs=None, ctx=None) -> Outcome:
    df = design_factor(mst)
    side_tag = side_tag or ("S" if side_to == "starboard" else "P")
    locked_items = list(locked or [])
    locked = {ln.line_number: ln for ln in locked_items}
    excluded = set(excluded or ())
    notes, reasons = [], []
    inv = inventory if inventory is not None else {k: 10**6 for k in specs}
    if len(locked) != len(locked_items) or not set(locked).issubset({slot.line_number for slot in slots}):
        return Outcome([], 0, 0, "none", True, notes, ["Locked line numbers must be unique and belong to the searched slots; no lock is silently discarded."])
    ship_fittings = {f.fitting_id: f for f in ship.fittings}
    pier_fittings = {f.fitting_id: f for f in berth.fittings}

    def usable_line(ln):
        spec, bitt, pf = specs.get(ln.spec_id), ship_fittings.get(ln.ship_fitting_id), pier_fittings.get(ln.pier_fitting_id)
        if spec is None or bitt is None or pf is None:
            return False
        if pf.fitting_id in excluded or pf.condition != "good" or pf.occupied_by or not pf.kind.startswith("bollard"):
            return False
        if bitt.kind not in ("bitt", "recessed_bitt", "cleat"):
            return False
        chock_id = ln.chock_id or bitt.paired_chock_id
        chock = ship_fittings.get(chock_id) if chock_id else None
        if chock_id and (chock is None or chock.kind != "chock"):
            return False
        return all(f.max_rope_circ_in is None or spec.size_circ_in <= f.max_rope_circ_in for f in (bitt, chock) if f)

    locked_need = Counter()
    for ln in locked_items:
        locked_need[ln.spec_id] += ln.parts
    if any(not usable_line(ln) for ln in locked_items) or any(count > inv.get(spec, 0) for spec, count in locked_need.items()):
        return Outcome([], 0, 0, "none", True, notes, ["Locked lines violate inventory, fitting availability/exclusion, or rope/chock compatibility."])
    variants = [(spec_id, pname) for spec_id in specs if inv.get(spec_id, 0) > 0 for pname in PATTERNS]
    if not variants:
        return Outcome([], 0, 0, "none", True, notes, ["No line inventory available: nothing can be moored."])
    # per-slot pier-fitting options
    options: list[tuple[Slot, object, list[str]]] = []
    for slot in slots:
        if slot.line_number in locked:
            options.append((slot, None, [locked[slot.line_number].pier_fitting_id]))
            continue
        bitt, opts = _slot_options(ship, berth, slot, side_to, ship_x_ft, excluded | {l.pier_fitting_id for l in locked.values()}, neighbors, side_tag)
        if bitt is None:
            return Outcome([], 0, 0, "none", True, notes, [f"No ship fitting for line {slot.line_number} ({slot.ship_fitting_id.replace('@', side_tag)})."])
        if not opts:
            return Outcome([], 0, 0, "none", True, notes, [f"No usable pier fitting for line {slot.line_number}: none is in good condition, free, a bollard and not excluded."])
        options.append((slot, bitt, opts))
    # compatibility filter: rope size must fit the ship fitting
    def spec_ok(spec_id, bitt):
        return bitt is None or bitt.max_rope_circ_in is None or specs[spec_id].size_circ_in <= bitt.max_rope_circ_in
    variants = [(s, p) for s, p in variants if all(spec_ok(s, b) for _, b, _ in options)]
    if not variants:
        return Outcome([], 0, 0, "none", True, notes, ["No inventoried line spec fits the ship fittings (rope size exceeds a fitting's maximum)."])
    space = len(variants)
    for _, _, o in options:
        space *= min(len(o), neighbors)
    sets = [o[:neighbors] for _, _, o in options]
    evaluated = 0
    results: dict[tuple, tuple[tuple, MooringConfig, dict]] = {}

    def build(choice: tuple[str, ...], variant) -> MooringConfig | None:
        spec_id, pname = variant
        if len(set(choice)) != len(choice):
            return None                                   # one line per pier fitting
        lines, need = [], Counter()
        for (slot, bitt, _), pf in zip(options, choice):
            if slot.line_number in locked:
                ln = locked[slot.line_number]
                lines.append(ln)
                need[ln.spec_id] += ln.parts
                continue
            parts = PATTERNS[pname](slot.role, slot.line_number)
            need[spec_id] += parts
            lines.append(MooringLine(line_number=slot.line_number, role=slot.role, spec_id=spec_id, parts=parts,
                                     ship_fitting_id=bitt.fitting_id, pier_fitting_id=pf))
        if any(count > inv.get(spec, 0) for spec, count in need.items()):
            return None                                   # inventory counts
        cfg = MooringConfig(side_to=side_to, ship_x_ft=ship_x_ft, standoff_ft=standoff_ft, lines=lines)
        # geometric hard constraints from the installed geometry
        from mooring.core.geometry import line_geometry
        for ln in lines:
            if not usable_line(ln):
                return None
            try:
                g = line_geometry(ln, ship, berth, cfg, install_level_ft)
            except KeyError:
                return None
            if g.length_ft > MAX_LINE_FT or (ln.role == "breast" and g.horiz_angle_deg >= MAX_BREAST_LEAD_DEG):
                return None
        return cfg

    def evaluate(choice, variant):
        nonlocal evaluated
        key = (choice, variant)
        if ctx is not None:
            ctx.check_cancelled()
        if key in results:
            return results[key]
        if evaluated >= max_evals:
            return None
        cfg = build(choice, variant)
        if cfg is None:
            results[key] = None
            return None
        evaluated += 1
        if ctx is not None:
            ctx.progress(min(evaluated / max_evals, 0.9), "Evaluating line configurations")
        worst, worst_case, feasible, checked = 0.0, "", True, 0
        from mooring import qualification
        if any(issue.blocking for issue in qualification.analysis_issues(ship, berth, cfg, specs)):
            results[key] = None
            return None
        from mooring.loads.helpers import mean_draft_ft
        for label, env in cases:
            checked += 1
            from mooring.loads.validity import environment_findings
            if any(state == "invalid" for state, _ in environment_findings(env)):
                feasible, worst, worst_case = False, math.inf, label + " (invalid environmental inputs)"
                break
            try:
                sysm = eq.build_system(ship, berth, cfg, specs, env, loading=loading, lines_wet=lines_wet, install_water_level_ft=install_level_ft, tugs=tugs)
            except eq.SystemError:
                results[key] = None
                return None
            if sysm.depth_ft(eq.Pose()) <= mean_draft_ft(ship, loading):
                feasible, worst, worst_case = False, math.inf, label + " (depth not above draft; invalid floating-mooring inputs)"
                break
            try:
                sol = eq.solve(sysm)
            except ValueError as exc:
                feasible, worst, worst_case = False, math.inf, label + f" (invalid solve inputs: {exc})"
                break
            if not sol.converged:
                feasible, worst, worst_case = False, math.inf, label + " (solve failed)"
                break
            if sysm.depth_ft(sol.pose) <= mean_draft_ft(ship, loading):
                feasible, worst, worst_case = False, math.inf, label + " (depth not above draft; invalid floating-mooring inputs)"
                break
            el, pct, mode = max(utilization(sysm, sol.pose, df), key=lambda e: e[1])
            if pct > worst:
                worst, worst_case = pct, f"{label}: {el} ({mode})"
            feasible = feasible and pct <= 100.0
        score = (0 if feasible else 1, worst, sum(l.parts for l in cfg.lines))
        results[key] = (score, cfg, {"worst": worst, "worst_case": worst_case, "feasible": feasible, "spec": variant[0], "pattern": variant[1], "cases_evaluated": checked})
        return results[key]

    if space <= max_evals:
        strategy, complete = "exhaustive", True
        for variant in variants:
            for choice in itertools.product(*sets):
                evaluate(choice, variant)
    else:
        strategy, complete = "bounded_descent", False
        notes.append(f"Space of {space} candidates exceeds the budget of {max_evals}: coordinate descent from the nearest-fitting plan. "
                     "Absence of a feasible plan here is not proof that none exists.")
        for variant in variants:
            if evaluated >= max_evals:
                break
            current = tuple(s[0] for s in sets)
            best = evaluate(current, variant)
            improved = True
            while improved and evaluated < max_evals:
                improved = False
                for i in range(len(sets)):
                    for alt in sets[i]:
                        if evaluated >= max_evals:
                            break
                        trial = current[:i] + (alt,) + current[i + 1:]
                        r = evaluate(trial, variant)
                        if r and (best is None or r[0] < best[0]):
                            best, current, improved = r, trial, True
    ranked = sorted((v for v in results.values() if v is not None), key=lambda r: r[0])
    if not ranked:
        reasons.append("No candidate satisfied the hard constraints (inventory, lead, reach or fitting compatibility).")
    return Outcome(ranked, space, evaluated, strategy, complete, notes, reasons)


def recommend(req: RecommendRequest, ctx=None) -> RecommendResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    refdata.loading(ship, req.loading)
    specs = {s.spec_id: s for s in refdata.lines()}
    outfit = req.available_lines or ship.standard_line_outfit
    inventory = {i.spec_id: i.count for i in outfit} if outfit else None
    if inventory is not None:
        unknown = [k for k in inventory if k not in specs]
        if unknown:
            raise refdata.InvalidReference(f"Unknown line specs in inventory: {unknown}")
        specs = {k: v for k, v in specs.items() if k in inventory}
    ship_x = req.ship_x_ft if req.ship_x_ft is not None else berth.face_length_ft / 2
    cases = design_cases(berth, req.side_to, req.design_mst, req.forecast_env, req.tide_levels_ft, include_mst=req.design_basis != "forecast_only")
    from mooring.tugs.validation import assignment_errors
    errors = assignment_errors(ship, req.tugs, refdata.tugs())
    if errors:
        raise refdata.InvalidReference("; ".join(errors))
    side_tag = "S" if req.side_to == "starboard" else "P"
    out = search_plans(ship, berth, specs, template_slots(), cases, side_to=req.side_to, ship_x_ft=ship_x, loading=req.loading, mst=req.design_mst,
                       inventory=inventory, locked=req.locked_lines, excluded=set(req.excluded_fitting_ids), neighbors=req.neighbors_per_line,
                       max_evals=req.max_evaluations, install_level_ft=req.tide_levels_ft[0], side_tag=side_tag, standoff_ft=req.standoff_ft, tugs=req.tugs, ctx=ctx)
    design_env = cases[0][1]
    candidates, top_results = [], []
    seen_cfg = set()
    for score, cfg, info in out.ranked:
        if ctx is not None:
            ctx.check_cancelled()
        sig = tuple((l.pier_fitting_id, l.parts, l.spec_id) for l in cfg.lines)
        if sig in seen_cfg:
            continue
        seen_cfg.add(sig)
        if len(candidates) >= req.max_candidates:
            break
        areq = AnalyzeRequest(ship_class_id=req.ship_class_id, loading=req.loading, berth_id=req.berth_id, config=cfg, environment=design_env,
                              mst=req.design_mst, tugs=req.tugs, installed_at_water_level_mllw_ft=req.tide_levels_ft[0])
        resp = solver.analyze(areq)
        lim = solver.limit_envelope(LimitEnvelopeRequest(**areq.model_dump(), step_deg=45, sampling_step_kt=10.0, tolerance_kt=1.0))
        worst_lim = lim.result.worst.limit_wind_kt
        candidates.append(Candidate(
            config=cfg, tugs=req.tugs, min_margin_pct_wll=round(info["worst"], 1) if math.isfinite(info["worst"]) else 999.0, limit_wind_kt_worst=worst_lim,
            line_count=len(cfg.lines), analysis_result_id=resp.result_id, feasible=info["feasible"], worst_case=info["worst_case"], cases_evaluated=info["cases_evaluated"],
            why=[f"{info['pattern']}, {info['spec']}.", f"Worst case across {len(cases)} cases: {info['worst_case']} at {info['worst']:.0f}%." if math.isfinite(info["worst"]) else f"Assessment stopped: {info['worst_case']}.",
                 "Feasible: every case solved and every element within its limit." if info["feasible"] else "NOT feasible: at least one case exceeds a limit or did not solve."]))
        top_results.append(resp)
    feasible_found = sum(1 for _, _, i in out.ranked if i["feasible"])
    reasons: list[ValidityReason] = []
    if not candidates:
        reasons.append(ValidityReason(code="NO_CANDIDATE_GENERATED", affected_components=["search"], message=" ".join(out.infeasible_reasons) or "No candidate generated."))
    elif not any(c.feasible for c in candidates):
        reasons.append(ValidityReason(code="NO_FEASIBLE_PLAN_FOUND", affected_components=["search"],
                                      message="No evaluated plan is within every limit in every case. " + ("The whole space was evaluated." if out.complete else "The search was bounded; this does not prove that no plan exists.")))
    for r in top_results[:1]:
        reasons += [x for x in r.validity.reasons if x.code != "NO_FENDERS"]
    seen, merged = set(), []
    for r in reasons:
        if r.code not in seen:
            seen.add(r.code); merged.append(r)
    state = "invalid" if (top_results and top_results[0].validity.state == "invalid") else "limited" if merged else "valid"
    validity = Validity(state=state, reasons=merged)
    best_ok = any(c.feasible for c in candidates)
    status = "RED" if not best_ok else ("AMBER" if candidates[0].min_margin_pct_wll > 80 else "GREEN")
    return envelope(RecommendResponse, model="mooring.planning.search", request=req, backend="real", model_version="1.0.0",
                    result=RecommendResult(candidates=candidates, design_environment=design_env, cases=[c[0] for c in cases],
                                           search=SearchDiagnostics(strategy=out.strategy, complete=out.complete, space_size=out.space_size, evaluated=out.evaluated,
                                                                    budget=req.max_evaluations, feasible_found=feasible_found, notes=out.notes + out.infeasible_reasons)),
                    status=status_with_validity(status, validity), validity=validity,
                    assumptions=["Hard constraints before objective; objective = lowest worst-case utilization over every MST alternative, forecast case and water level, then fewer parts.",
                                 f"Design basis: {req.design_basis or 'mst_and_forecast'}; forecast_only does not establish MST design compliance.",
                                 "Fixed holding assistance is evaluated in every case and requires continuous availability." if req.tugs else "No holding assistance used.", "Risk (M5) is not used to rank: its model is unqualified.",
                                 *solver.ASSUMPTIONS])
