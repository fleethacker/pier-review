"""Modeled ultimate-load gust threshold search (P6/R6) on the real equilibrium solver.

Wind is raised from zero along each relative bearing with current, level and tugs held and the request's gust ratio held.
At every speed the full equilibrium is solved. Stopping rules are separate from warnings:
* crossing WLL is recorded and continues (it is a warning, not a stop);
* a line reaching its supplied ultimate capacity is the target event;
* a line beyond its supplied material-law range, a fitting beyond its rating, a fender beyond rated energy or a failed
  solve stops the search and makes the direction indeterminate unless the line ultimate is reached alone.
The capacity basis is an input. Nothing here supplies a capacity or derives one from WLL/MBS by a design factor.
"""

import dataclasses

from mooring.core.envelopes import envelope
from mooring.core.geometry import ship_heading_true
from mooring.core.schemas import Validity, ValidityReason
from mooring.core.schemas.ultimate import UltimateDirectionResult, UltimateGustRequest, UltimateGustResponse, UltimateGustResult
from mooring.mechanics import Pose
from mooring.mechanics import equilibrium as eq
from mooring.rules.nstm582 import design_factor
from mooring.loads.validity import merge_reasons, wind_basis
from . import solver

MODEL = "mooring.solver.ultimate_gust"
VERSION = "0.1.0"


@dataclasses.dataclass
class Probe:
    converged: bool
    ultimate: dict[str, float] = dataclasses.field(default_factory=dict)   # line -> tension / ultimate capacity
    material: list[str] = dataclasses.field(default_factory=list)          # lines beyond the supported material range
    component: list[str] = dataclasses.field(default_factory=list)         # fittings/fenders beyond rating
    wll: bool = False
    pose: Pose | None = None

    @property
    def stopped(self) -> bool:
        return bool(self.ultimate or self.material or self.component)


def probe(system: eq.System, warm: Pose, caps: dict[int, tuple[float, float]], df: float, validate=None) -> Probe:
    sol = eq.solve(system, warm)
    if validate is not None:
        validate(system, sol)
    if not sol.converged:
        return Probe(False)
    p = Probe(True, pose=sol.pose)
    for rec, st, t in system.line_tensions(sol.pose):
        n = rec.ln.line_number
        cap, max_strain = caps[n]
        if t >= cap:
            p.ultimate[f"line-{n}"] = t / cap
        elif rec.model.strain(st.length_ft) > max_strain:
            p.material.append(f"line-{n}")
        if t > rec.model.mbs_eff_lbf / df:
            p.wll = True
    p.component = sorted({el for el, pct, mode in eq.utilization(system, sol.pose, df) if mode in ("fitting", "fender") and pct > 100.0})
    return p


def search_direction(base: eq.System, caps, df, ratio, from_true, rel, max_kt, step, tol, validate=None) -> UltimateDirectionResult:
    def at(v, warm):
        env = base.env.model_copy(update={"wind_speed_kt": v, "wind_gust_kt": v * ratio, "wind_from_true_deg": from_true})
        return probe(dataclasses.replace(base, env=env), warm, caps, df, validate)

    def res(outcome, **kw):
        return UltimateDirectionResult(wind_rel_deg=rel, wind_from_true_deg=from_true, outcome=outcome, **kw)

    def limited(p: Probe, lo, hi, wll_br, nonmono):
        others = sorted(set(p.material) | set(p.component) | set(p.ultimate))
        only_material = p.material and not p.component
        return res("indeterminate_material_range" if only_material else "indeterminate_component_failed_first", stop_kt=round(hi, 2),
                   stop_elements=others, bracket_kt=[round(lo, 2), round(hi, 2)], wll_crossing_bracket_kt=wll_br, nonmonotone_in_bracket=nonmono or None,
                   reason=("A line left the supported material-law range" if only_material else "A fitting or fender reached its rating")
                   + " no later than any line ultimate; the line ultimate cannot be established as first.")

    p0 = at(0.0, Pose())
    if not p0.converged:
        return res("indeterminate_nonconvergence", stop_kt=0.0, reason="Equilibrium did not converge at zero wind.")
    if p0.stopped:
        if p0.ultimate and not p0.material and not p0.component:
            g = max(p0.ultimate, key=p0.ultimate.get)
            return res("ultimate_at_zero_wind", threshold_wind_kt=0.0, threshold_gust_kt=0.0, governing_line=g,
                       governing_utilization_of_ultimate=p0.ultimate[g], bracket_kt=[0.0, 0.0], reason="Modeled ultimate capacity reached with no wind.")
        return limited(p0, 0.0, 0.0, None, False)
    lo, warm, wll_br = 0.0, p0.pose, None
    v = min(step, max_kt)
    while True:
        p = at(v, warm)
        if not p.converged:
            return res("indeterminate_nonconvergence", stop_kt=v, wll_crossing_bracket_kt=wll_br,
                       reason=f"Equilibrium did not converge at {v:g} kt; this is not proof of survival.")
        if p.wll and wll_br is None:
            wll_br = [round(lo, 2), round(v, 2)]
        if p.stopped:
            hi, hp = v, p
            inner = [lo + (hi - lo) * k / 5 for k in range(1, 5)]
            probes = [at(x, warm) for x in inner]
            bad = next((x for x, q in zip(inner, probes) if not q.converged), None)
            if bad is not None:
                return res("indeterminate_nonconvergence", stop_kt=round(bad, 2), wll_crossing_bracket_kt=wll_br, reason="Equilibrium failed inside the bracket.")
            nonmono = any(a.stopped and not b.stopped for a, b in zip(probes, probes[1:]))
            for x, q in zip(inner, probes):
                if q.stopped:
                    hi, hp = x, q
                    break
                lo = x
            while hi - lo > tol:
                mid = 0.5 * (lo + hi)
                q = at(mid, warm)
                if not q.converged:
                    return res("indeterminate_nonconvergence", stop_kt=round(mid, 2), wll_crossing_bracket_kt=wll_br, reason="Equilibrium failed during bisection.")
                if q.stopped:
                    hi, hp = mid, q
                else:
                    lo = mid
            if hp.material or hp.component:
                return limited(hp, lo, hi, wll_br, nonmono)
            g = max(hp.ultimate, key=hp.ultimate.get)
            return res("threshold_found", threshold_wind_kt=round(lo, 2), threshold_gust_kt=round(lo * ratio, 2), bracket_kt=[round(lo, 2), round(hi, 2)],
                       governing_line=g, governing_utilization_of_ultimate=hp.ultimate[g], wll_crossing_bracket_kt=wll_br,
                       nonmonotone_in_bracket=nonmono or None)
        lo, warm = v, p.pose
        if v >= max_kt - 1e-9:
            break
        v = min(v + step, max_kt)
    return res("indeterminate_search_ceiling", stop_kt=max_kt, wll_crossing_bracket_kt=wll_br,
               reason=f"No stop up to the {max_kt:g} kt search ceiling; the threshold is above it or unsearched, not unlimited.")


def _unavailable(req, reasons) -> UltimateGustResponse:
    validity = Validity(state="unknown", reasons=[ValidityReason(code=c, message=m, affected_components=["ultimate-capacity"]) for c, m in reasons])
    result = UltimateGustResult(outcome="unavailable", reasons=[m for _, m in reasons])
    return envelope(UltimateGustResponse, model=MODEL, request=req, result=result, status="AMBER", backend="real", model_version=VERSION, validity=validity,
                    assumptions=["No ultimate threshold is computed without a complete supplied capacity basis; no capacity or design factor is invented."])


class InvalidSearchInputs(Exception):
    def __init__(self, validity):
        self.validity = validity


def _invalid_inputs(req, validity):
    basis = req.capacity_basis
    result = UltimateGustResult(outcome="unavailable", reasons=[r.message for r in validity.reasons],
                                basis_id=basis.basis_id, evidence_status=basis.evidence_status, citation=basis.citation,
                                wind_basis=basis.wind_basis)
    return envelope(UltimateGustResponse, model=MODEL, request=req, result=result, status="RED", backend="real",
                    model_version=VERSION, validity=validity,
                    assumptions=["Invalid physical inputs invalidate the entire search; no ultimate gust or margin is established."])


def ultimate_gust(req: UltimateGustRequest) -> UltimateGustResponse:
    basis = req.capacity_basis
    if basis is None:
        return _unavailable(req, [("ULTIMATE_CAPACITY_BASIS_MISSING", "No sourced ultimate capacity / material-law basis was supplied; the ultimate gust threshold is unavailable.")])
    need = {ln.line_number for ln in req.config.lines}
    have = {c.line_number: c for c in basis.lines}
    missing = sorted(need - set(have))
    if missing:
        return _unavailable(req, [("ULTIMATE_CAPACITY_INCOMPLETE", f"No supplied capacity/material range for line(s) {missing}; a governing line cannot be established.")])
    wind = req.environment.wind_speed_kt
    ratio = req.environment.wind_gust_kt / wind if wind > 0 else 1.0
    base, sol0, specs = solver.solve_request(req)
    input_reasons = []

    def validate(system, sol):
        candidate = req.model_copy(update={"environment": system.env})
        _, _, findings = solver.build_result(candidate, system, sol, specs, run_rules=False)
        # Numerical failure has its own per-direction indeterminate outcome. It must not hide an input failure.
        validity = solver._validity(candidate, system, sol, specs, findings, wind_basis(system.env, True), include_nonconvergence=False)
        input_reasons.extend(validity.reasons)
        if validity.state == "invalid":
            raise InvalidSearchInputs(validity)

    caps = {n: (have[n].ultimate_capacity_lbf, have[n].material_law_max_strain) for n in need}
    df = design_factor(req.mst)
    heading = ship_heading_true(base.berth, req.config.side_to)
    args = dict(base=base, caps=caps, df=df, ratio=ratio, max_kt=req.max_search_kt, step=req.sampling_step_kt, tol=req.tolerance_kt, validate=validate)
    try:
        validate(base, sol0)
        dirs = [search_direction(from_true=(heading + rel) % 360, rel=float(rel), **args) for rel in range(0, 360, req.step_deg)]
        assessed = search_direction(from_true=req.environment.wind_from_true_deg, rel=round((req.environment.wind_from_true_deg - heading) % 360, 4), **args)
    except InvalidSearchInputs as exc:
        return _invalid_inputs(req, exc.validity)
    every = dirs + [assessed]
    found = [d for d in every if d.threshold_wind_kt is not None]
    complete = len(found) == len(every)
    governing = min(found, key=lambda d: d.threshold_wind_kt) if found else None
    reasons, vreasons = [], []
    if governing is None:
        reasons.append("No searched direction produced a modeled ultimate threshold; see per-direction outcomes.")
    elif not complete:
        reasons.append("Some directions are indeterminate; the governing value is the lowest found, not a proven minimum.")
    for d in every:
        if d.threshold_wind_kt is None:
            vreasons.append(ValidityReason(code=d.outcome.upper(), affected_components=[f"wind-rel-{d.wind_rel_deg:g}", *d.stop_elements], message=d.reason or d.outcome))
    if any(d.nonmonotone_in_bracket for d in every):
        vreasons.append(ValidityReason(code="NONMONOTONE_BRACKET", affected_components=["search"], message="Stop pattern was not monotone inside a bracket; the lowest sampled stop was used."))
    vreasons.append(ValidityReason(code="RUPTURE_PREDICTION_NOT_VALIDATED", affected_components=["ultimate-capacity"],
                                   message="Reaching modeled ultimate capacity is not a validated prediction of physical rupture; that claim needs its own validation evidence."))
    if basis.evidence_status != "sourced":
        vreasons.append(ValidityReason(code="CAPACITY_BASIS_NOT_SOURCED", affected_components=[basis.basis_id], message="The capacity basis is a synthetic test fixture, not sourced evidence."))
    validity = Validity(state="limited", reasons=merge_reasons(input_reasons + vreasons))
    ag = assessed.threshold_gust_kt
    result = UltimateGustResult(
        outcome="threshold_found" if governing is not None else "indeterminate", reasons=reasons, basis_id=basis.basis_id,
        evidence_status=basis.evidence_status, citation=basis.citation, wind_basis=basis.wind_basis, complete=complete, governing=governing,
        assessed=assessed, assessed_gust_kt=req.environment.wind_gust_kt,
        assessed_gust_margin_kt=None if ag is None else round(ag - req.environment.wind_gust_kt, 2), directions=dirs)
    status = "RED" if ag is not None and ag <= req.environment.wind_gust_kt else "AMBER"
    return envelope(UltimateGustResponse, model=MODEL, request=req, result=result, status=status, backend="real", model_version=VERSION, validity=validity,
                    assumptions=[f"Wind raised 0-{req.max_search_kt:g} kt in {req.sampling_step_kt:g} kt samples, refined to {req.tolerance_kt:g} kt; narrower stops can be missed.",
                                 f"Gust/sustained ratio {ratio:.2f} held; current, level and tugs held. Gust basis: {basis.wind_basis}.",
                                 f"Ultimate capacity and material-law range are the supplied inputs; WLL (design factor {df:g}) crossings are warnings only and do not stop the search.",
                                 *solver.ASSUMPTIONS],
                    manifest=solver.manifest_for(req, base, specs, sol0, {"ultimate": {"basis_id": basis.basis_id, "max_search_kt": req.max_search_kt}}))
