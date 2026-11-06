"""Static mooring analysis service (M4): equilibrium, validity, capacity checks and NSTM rules.

Real: 3-DOF equilibrium over tension-only lines and unilateral fenders (see equilibrium.py), tug force vectors,
M3 loads at the solved pose, per-element utilization and the NSTM rule subset. Limiting wind and the tide sweep are
delegated to `moored.envelopes_real` (S07). Gust risk, optimizer and tug sizing remain behind their own modules.

Separation of concerns (S06): *numerical validity* (convergence, residual, rank, bounds), *load-model validity* (S03),
*data qualification* (S01) and *physical capacity* (utilization of lines/fittings/fenders) are computed independently.
`run_rules=False` disables only the NSTM applicability checks; it never disables validity or capacity.
"""

import math
from collections import defaultdict
from dataclasses import replace

from mooring import qualification, refdata
from mooring.core import store
from mooring.core.envelopes import envelope, resolved_inputs_hash, status_from_pct, worst
from mooring.core.geometry import classify_role, depth_at, line_geometry, ship_heading_true, ship_to_berth
from mooring.core.schemas import (
    AnalyzeRequest, AnalyzeResponse, AnalyzeResult, FenderResult, Finding, LineResult, ManifestRecord, MinMargin, Offset,
    PierFittingResult, ResultManifest, Rule, ShipFittingResult, SolverDiagnostics, SolverResidual, Validity, ValidityReason,
)
from mooring.loads import mean_draft_ft, off_pier, range_findings
from mooring.loads.validity import classify_findings, environment_findings, merge_reasons, wind_basis
from mooring.tugs.validation import assignment_errors
from mooring.mechanics import Pose
from mooring.rules.nstm582 import RULES, CheckContext, check_all, design_factor

from mooring.mechanics import equilibrium as eq

MODEL = "mooring.solver.equilibrium"
VERSION = "1.0.0"
ASSUMPTIONS = [
    "Quasi-static 3-DOF equilibrium (surge, sway, yaw) of a rigid hull; heave, roll, pitch and dynamics are not modeled.",
    "Applied environmental loads include wind and current only; wave and wake loads are not evaluated.",
    "Lines are tension-only; tension = parts x effective MBS x curve(strain) with the catalog stretch curve scaled by the effective (wet/dry) MBS.",
    "Fenders are unilateral springs (catalog linear stiffness) in contact over a parallel body of +/- half the waterline length.",
    "Pier-fitting loads are the 3-D vector sum of attached lines compared with the nominal capacity.",
    "Rest lengths are set at the installation water level and stay fixed; the ship rides the water level.",
]


def rules() -> list[Rule]:
    return RULES


def _record_rev(obj) -> str:
    return resolved_inputs_hash(obj)[:23]


def solve_request(req: AnalyzeRequest, *, start: Pose = Pose(), force_rel_tol: float = eq.REL_TOL):
    """Resolve references and solve. Returns everything the response and the envelopes service need."""
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    try:
        specs = {ln.spec_id: refdata.line(ln.spec_id) for ln in req.config.lines}
    except refdata.NotFound as e:
        raise refdata.InvalidReference(str(e)) from None
    try:
        system = eq.build_system(ship, berth, req.config, specs, req.environment, loading=req.loading, lines_wet=req.lines_wet,
                                 tugs=req.tugs, install_water_level_ft=req.installed_at_water_level_mllw_ft)
    except eq.SystemError as e:
        raise refdata.InvalidReference(str(e)) from None
    refdata.loading(ship, req.loading)
    if system.depth_ft(start) <= 0:
        raise refdata.InvalidReference("Actual water depth must be positive; berth depth plus water level is nonpositive")
    try:
        solution = eq.solve(system, start, force_rel_tol=force_rel_tol)
    except ValueError as exc:
        raise refdata.InvalidReference(f"Invalid equilibrium inputs: {exc}") from None
    return system, solution, specs


def _validity(req: AnalyzeRequest, system: eq.System, sol: eq.Solution, specs, load_findings, basis, *, include_nonconvergence=True) -> Validity:
    invalid: list[ValidityReason] = []
    limited: list[ValidityReason] = []
    # numerical
    if not sol.converged:
        if include_nonconvergence:
            invalid.append(ValidityReason(code="NO_EQUILIBRIUM_FOUND", affected_components=sol.active_bounds or ["pose"],
                                          message=f"{sol.failure}. This is a numerical outcome, not a proof that no equilibrium exists."))
    elif sol.rank < 3:
        limited.append(ValidityReason(code="UNDERCONSTRAINED_SUPPORT", affected_components=["pose"],
                                      message=f"Support stiffness has rank {sol.rank} of 3: the equilibrium is not unique (some motions are unrestrained)."))
    elif not sol.positive_definite:
        limited.append(ValidityReason(code="NOT_LOCALLY_STABLE", affected_components=["pose"],
                                      message="The symmetric part of the support stiffness is not positive definite: stability of this equilibrium is not established."))
    # load model (S03)
    for state, reason in classify_findings(load_findings):
        (invalid if state == "invalid" else limited).append(reason)
    limited += basis.reasons
    for state, reason in environment_findings(req.environment):
        (invalid if state == "invalid" else limited).append(reason)
    # data qualification (S01)
    for i in qualification.analysis_issues(system.ship, system.berth, req.config, specs):
        (invalid if i.blocking else limited).append(
            ValidityReason(code=i.code, message=i.message, affected_components=i.element_ids))
    for code, msg, ids in qualification.qualification_reasons(system.ship, system.berth, specs):
        limited.append(ValidityReason(code=code, message=msg, affected_components=ids))
    # arrangement and tugs
    for rec in system.lines:
        if rec.ln.parts == 2:
            limited.append(ValidityReason(code="REEVING_ASSUMED_PARALLEL", affected_components=[f"line-{rec.ln.line_number}"],
                                          message="Two-part (tanker moor) arrangement modeled as identical parallel strands without chock friction."))
    for error in assignment_errors(system.ship, req.tugs, refdata.tugs()):
        invalid.append(ValidityReason(code="TUG_ASSIGNMENT_INVALID", message=error,
                                      affected_components=[t.tug_id for t in req.tugs]))
    fleet = {t.tug_id: t for t in refdata.tugs()}
    for t in system.tugs:
        catalog = fleet.get(t.tug.tug_id)
        if catalog and catalog.provenance.confidence != "published":
            limited.append(ValidityReason(code="TUG_DATA_UNQUALIFIED", message="Tug ratings are catalog estimates, not qualified fleet evidence.",
                                          affected_components=[t.tug.tug_id]))
        if t.tug.direction_true_deg is not None:
            limited.append(ValidityReason(code="TUG_DIRECTIONAL_CAPACITY_UNQUALIFIED", message="A true-direction force is prescribed without a qualified directional tug performance envelope.",
                                          affected_components=[t.tug.tug_id]))
        if t.tug.force_lbf > t.max_force_lbf:
            invalid.append(ValidityReason(code="TUG_FORCE_EXCEEDS_PUSH_POINT_LIMIT", affected_components=[t.tug.push_point_id],
                                          message=f"Tug force {t.tug.force_lbf:.0f} lbf exceeds the {t.max_force_lbf:.0f} lbf push point limit."))
    if not req.config.lines:
        invalid.append(ValidityReason(code="NO_LINES", message="No mooring lines: nothing restrains the ship.", affected_components=["config"]))
    reasons = merge_reasons(invalid + limited)
    state = "invalid" if invalid else "limited" if limited else "valid"
    diag = SolverDiagnostics(
        converged=sol.converged, iterations=sol.iterations,
        residuals=[SolverResidual(name="surge_force", value=sol.residual.fx_lbf, unit="lbf", tolerance=sol.force_tol_lbf),
                   SolverResidual(name="sway_force", value=sol.residual.fy_lbf, unit="lbf", tolerance=sol.force_tol_lbf),
                   SolverResidual(name="yaw_moment", value=sol.residual.mz_ftlbf, unit="ftlbf", tolerance=sol.moment_tol_ftlbf)],
        active_constraints=[f"bound:{b}" for b in sol.active_bounds] + [f"slack:line-{n}" for n in sol.slack_lines]
        + [f"contact:{c}" for c in sol.contacts],
        rank=sol.rank, degrees_of_freedom=3,
        notes=[f"force tolerance {sol.force_tol_lbf:.3g} lbf, moment tolerance {sol.moment_tol_ftlbf:.3g} ft.lbf (numerical, not safety limits)",
               f"locally stable (symmetric stiffness positive definite): {sol.positive_definite}"])
    return Validity(state=state, reasons=reasons, diagnostics=diag)


def build_result(req: AnalyzeRequest, system: eq.System, sol: eq.Solution, specs, *, run_rules: bool = True):
    ship, berth, cfg, env = system.ship, system.berth, req.config, req.environment
    pose = sol.pose
    df = design_factor(req.mst)
    heading0 = ship_heading_true(berth, cfg.side_to)
    nominal_geoms = [line_geometry(rec.ln, ship, berth, cfg, env.water_level_mllw_ft) for rec in system.lines]
    tens = system.line_tensions(pose)
    forward = system.frame.vector_to_berth(1, 0, pose)
    port = system.frame.vector_to_berth(0, 1, pose)
    line_results, states, geoms = [], {}, []
    for (rec, st, t), g in zip(tens, nominal_geoms):
        n = rec.ln.line_number
        mbs = rec.model.mbs_eff_lbf
        wll = mbs / df
        horiz = math.hypot(st.ux, st.uy)
        along_ship = st.ux * forward[0] + st.uy * forward[1]
        across_ship = st.ux * port[0] + st.uy * port[1]
        horiz_angle = math.degrees(math.atan2(abs(along_ship), abs(across_ship))) if horiz > 0 else 90.0
        vert = math.degrees(math.atan2(abs(st.uz), horiz))
        # Rules and displayed line geometry must describe the same solved pose/tide.
        # Installation tide defines rest lengths, not the current line lead or span.
        g = replace(g, length_ft=st.length_ft, horiz_length_ft=st.length_ft*horiz,
                    horiz_angle_deg=horiz_angle, vert_angle_deg=vert, leads_forward=along_ship > 0,
                    role=rec.ln.role or classify_role(ship, g.lead_point.x_ft, horiz_angle, along_ship > 0))
        geoms.append(g)
        pct_wll = 100 * t / wll
        states[n] = (st, t)
        line_results.append(LineResult(
            line_number=n, role=g.role, tension_lbf=round(t), pct_mbs=round(100 * t / mbs, 1), pct_wll=round(pct_wll, 1),
            horiz_angle_deg=round(horiz_angle, 1), vert_angle_deg=round(vert, 1),
            breast_efficiency=round(math.cos(math.radians(horiz_angle)), 3), length_ft=round(st.length_ft, 1),
            status=status_from_pct(pct_wll)))
    by_pier, by_ship = defaultdict(list), defaultdict(list)
    for rec, st, t in tens:
        by_pier[rec.ln.pier_fitting_id].append((rec.ln.line_number, st, t))
        by_ship[rec.ln.ship_fitting_id].append((rec.ln.line_number, st, t))
    pier_by_id = {f.fitting_id: f for f in berth.fittings}
    ship_by_id = {f.fitting_id: f for f in ship.fittings}
    pier_results = []
    for fid, items in by_pier.items():
        fx = sum(t * s.ux for _, s, t in items); fy = sum(t * s.uy for _, s, t in items); fz = sum(t * s.uz for _, s, t in items)
        load = math.sqrt(fx * fx + fy * fy + fz * fz)
        cap = pier_by_id[fid].capacity_nominal_lbf
        pct = 100 * load / cap
        pier_results.append(PierFittingResult(fitting_id=fid, load_lbf=round(load), capacity_lbf=cap, pct=round(pct, 1),
                                              lines=[n for n, _, _ in items], status=status_from_pct(pct)))
    ship_results = []
    for fid, items in by_ship.items():
        fx = sum(t * s.ux for _, s, t in items); fy = sum(t * s.uy for _, s, t in items); fz = sum(t * s.uz for _, s, t in items)
        load = math.sqrt(fx * fx + fy * fy + fz * fz)
        swl = ship_by_id[fid].swl_lbf
        pct = 100 * load / swl if swl else None
        ship_results.append(ShipFittingResult(fitting_id=fid, load_lbf=round(load), swl_lbf=swl,
                                              pct=round(pct, 1) if pct is not None else None,
                                              lines=[n for n, _, _ in items],
                                              status=status_from_pct(pct) if pct is not None else "GREEN"))
    fender_results = []
    for fr, d, _ in system.fender_loads(pose):
        f = fr.model.force(d)
        e = fr.model.energy(d)
        pct_e = 100 * e / fr.model.rated_energy_ftlbf if fr.model.rated_energy_ftlbf else None
        status = "GREEN" if pct_e is None or pct_e <= 80 else "AMBER" if pct_e <= 100 else "RED"
        fender_results.append(FenderResult(fender_id=fr.model.fender_id, reaction_lbf=round(f), compression_ft=round(d, 2),
                                           status=status, energy_ftlbf=round(e), pct_rated_energy=round(pct_e, 1) if pct_e is not None else None))
    elements = [(f"line-{r.line_number}", r.pct_wll) for r in line_results]
    elements += [(p.fitting_id, p.pct) for p in pier_results] + [(s.fitting_id, s.pct) for s in ship_results if s.pct is not None]
    top = max(elements, key=lambda e: e[1]) if elements else ("none", 0.0)

    findings: list[Finding] = []
    if run_rules:
        bow_x, _ = ship_to_berth(ship.loa_ft / 2, 0, ship, berth, cfg)
        findings = check_all(CheckContext(
            ship=ship, berth=berth, env=env, mst=req.mst, heading_true_deg=heading0, geometries=geoms,
            line_results=line_results, specs=specs, pier_results=pier_results, ship_results=ship_results,
            bow_x_berth_ft=bow_x, bow_dir=1 if cfg.side_to == "starboard" else -1))
    # Load-model range findings are always reported, with rules on or off.
    depth = system.depth_ft(pose)
    reynolds = [system.loads_at(pose).current.coefficients["reynolds"]]
    range_f, _ = range_findings(depth, mean_draft_ft(ship, req.loading), env.current_speed_kt, reynolds)
    findings += range_f
    front = 1 if cfg.side_to == "starboard" else -1
    resolved_config = cfg.model_copy(update={"lines": [line.ln.model_copy(update={
        "paid_out_unstretched_length_ft": line.model.rest_length_ft,
        "pretension_lbf": None, "slack_ft": None, "condition": "wet" if line.wet else "dry",
    }) for line in system.lines]})
    result = AnalyzeResult(
        resolved_config=resolved_config,
        offset=Offset(surge_ft=round(pose.dx_ft * front, 2), sway_ft=round(pose.dy_ft, 2), yaw_deg=round(math.degrees(pose.dyaw_rad), 3)),
        lines=line_results, pier_fittings=pier_results, ship_fittings=ship_results, fenders=fender_results,
        min_margin=MinMargin(element_id=top[0], pct_wll=round(top[1], 1)), findings=findings)
    status = worst([r.status for r in line_results] + [p.status for p in pier_results] + [s.status for s in ship_results]
                   + [f.status for f in fender_results] + [f.severity for f in findings])
    return result, status, range_f


def manifest_for(req: AnalyzeRequest, system: eq.System, specs, sol: eq.Solution, extra: dict | None = None) -> ResultManifest:
    fleet = {t.tug_id: t for t in refdata.tugs()}
    resolved_tugs = {t.tug_id: fleet[t.tug_id].model_dump(mode="json") for t in req.tugs if t.tug_id in fleet}
    snapshot = {"tug_specs": resolved_tugs, "unresolved_tug_ids": sorted({t.tug_id for t in req.tugs if t.tug_id not in fleet}),
                "request": req.model_dump(mode="json"), "ship": system.ship.model_dump(mode="json"),
                "berth": system.berth.model_dump(mode="json"), "line_specs": {k: v.model_dump(mode="json") for k, v in specs.items()},
                "settings": {"max_iter": eq.MAX_ITER, "rel_tol": eq.REL_TOL, "bound_xy_ft": eq.BOUND_XY_FT,
                             "bound_yaw_rad": eq.BOUND_YAW_RAD}, **(extra or {})}
    h = resolved_inputs_hash(snapshot)
    store.save_snapshot(h, snapshot)
    records = [ManifestRecord(kind="ship", id=system.ship.class_id, revision=_record_rev(snapshot["ship"])),
               ManifestRecord(kind="berth", id=system.berth.berth_id, revision=_record_rev(snapshot["berth"]))]
    records += [ManifestRecord(kind="line_spec", id=k, revision=_record_rev(v)) for k, v in snapshot["line_specs"].items()]
    records += [ManifestRecord(kind="tug", id=k, revision=_record_rev(v)) for k, v in resolved_tugs.items()]
    return ResultManifest(resolved_inputs_hash=h, code_version=f"{MODEL}@{VERSION}", records=records,
                          environment_hash=resolved_inputs_hash(req.environment),
                          numerical_settings=snapshot["settings"])


def analyze_full(req: AnalyzeRequest, *, run_rules: bool = True):
    """Solve and assemble (response, system, solution). Used by analyze, the envelope search and tide sweep."""
    system, sol, specs = solve_request(req)
    result, status, load_findings = build_result(req, system, sol, specs, run_rules=run_rules)
    basis = wind_basis(req.environment, True)
    validity = _validity(req, system, sol, specs, load_findings, basis)
    return result, status, validity, system, sol, specs


def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    result, status, validity, system, sol, specs = analyze_full(req)
    assumptions = ASSUMPTIONS + [f"Design factor {design_factor(req.mst)} (MST {req.mst})."]
    assumptions += [f"line {r.ln.line_number}: rest length from {r.how}." for r in system.lines]
    assumptions += wind_basis(req.environment, True).notes
    return envelope(AnalyzeResponse, model=MODEL, request=req, result=result, status=status, assumptions=assumptions,
                    warnings=[f for f in result.findings if f.severity != "INFO"], validity=validity,
                    manifest=manifest_for(req, system, specs, sol), backend="real", model_version=VERSION)


# Limiting wind and tide sweep live in envelopes_real (S07); re-exported for the backend interface.
from .envelopes_real import limit_envelope, tide_sweep  # noqa: E402,F401
