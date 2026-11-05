"""Limiting wind and tide sweep (S07) on the real equilibrium solver.

Limit search: for each relative wind bearing, current, water level, tugs and the request's gust ratio are held fixed
and the wind speed is raised from zero. A coarse scan finds the first speed at which any line, fitting or fender limit
is exceeded; the bracket is then refined by bisection. Bisection is only trusted after sampling inside the bracket
shows monotone behavior; otherwise the lowest failing sample is reported and the point is flagged. Outcomes are
distinct: limit found, fails at zero wind, no failure within the searched range, undetermined (a solve failed), invalid
inputs. Failures narrower than the sampling step can be missed; the step is reported in the assumptions.

Tide sweep: rest lengths are installed once (at the installation water level) and never changed implicitly. Only the
explicit `tending` inputs change them. Recommended actions are advisory. The sweep is evaluated internally at a fine
interval so extremes between the reported steps are not missed.
"""

import dataclasses
import math
from datetime import timedelta

from mooring import environment, refdata
from mooring.core.envelopes import envelope
from mooring.core.geometry import ship_heading_true
from mooring.core.schemas import (
    AnalyzeRequest, Finding, LimitEnvelopePoint, LimitEnvelopeRequest, LimitEnvelopeResponse, LimitEnvelopeResult, LineExtreme,
    LineTension, TendingAction, TideStep, TideSweepRequest, TideSweepResponse, TideSweepResult, ValidityReason, Validity,
)
from mooring.mechanics import Pose
from mooring.rules.nstm582 import design_factor

from mooring.mechanics import equilibrium as eq
from mooring.mechanics.equilibrium import utilization  # noqa: F401  (shared evaluator, re-exported)
from .solver import MODEL, VERSION, solve_request

FINE_STEP_MIN = 5.0
ADVISORY_GUST_FRACTION = 0.8  # Application warning policy, not a UFC/NSTM physical coefficient.


def _evaluate(system: eq.System, start: Pose, df: float):
    sol = eq.solve(system, start)
    if not sol.converged:
        return "undetermined", None, None, sol
    worst = max(utilization(system, sol.pose, df), key=lambda e: e[1])
    if worst[1] > 100.0:
        return "fail", worst[0], worst[2], sol
    return "ok", None, None, sol


def limit_envelope(req: LimitEnvelopeRequest) -> LimitEnvelopeResponse:
    base, sol0, specs = solve_request(req)
    ratio = req.environment.wind_gust_kt / req.environment.wind_speed_kt if req.environment.wind_speed_kt > 0 else 1.0
    heading = ship_heading_true(base.berth, req.config.side_to)
    df = design_factor(req.mst)
    points: list[LimitEnvelopePoint] = []
    for rel in range(0, 360, req.step_deg):
        from_true = (heading + rel) % 360

        def at(v: float, warm: Pose):
            env = req.environment.model_copy(update={"wind_speed_kt": v, "wind_gust_kt": v * ratio, "wind_from_true_deg": from_true})
            return _evaluate(dataclasses.replace(base, env=env), warm, df)

        state, el, mode, sol = at(0.0, Pose())
        if state == "fail":
            points.append(LimitEnvelopePoint(wind_rel_deg=rel, limit_wind_kt=0.0, first_failure_element=el, failure_mode=mode,
                                             outcome="fails_at_zero_wind", search_max_kt=req.max_search_kt))
            continue
        if state == "undetermined":
            points.append(LimitEnvelopePoint(wind_rel_deg=rel, limit_wind_kt=None, first_failure_element=None, failure_mode="none",
                                             outcome="undetermined", undetermined_at_kt=0.0, search_max_kt=req.max_search_kt))
            continue
        lo, warm, point = 0.0, sol.pose, None
        v = req.sampling_step_kt
        while v <= req.max_search_kt + 1e-9:
            state, el, mode, sol = at(v, warm)
            if state == "undetermined":
                point = LimitEnvelopePoint(wind_rel_deg=rel, limit_wind_kt=None, first_failure_element=None, failure_mode="none",
                                           outcome="undetermined", undetermined_at_kt=v, search_max_kt=req.max_search_kt)
                break
            if state == "fail":
                hi, hi_el, hi_mode = v, el, mode
                # sample inside the bracket: pass-then-fail pattern must be monotone before bisecting
                inner = [lo + (hi - lo) * k / 5 for k in range(1, 5)]
                flags = [at(x, warm)[0] for x in inner]
                nonmono = any(f == "fail" and g == "ok" for f, g in zip(flags, flags[1:]))
                if nonmono or "undetermined" in flags:
                    first_fail = next((x for x, f in zip(inner, flags) if f != "ok"), hi)
                    hi = first_fail
                    point = LimitEnvelopePoint(wind_rel_deg=rel, limit_wind_kt=round(lo, 2), first_failure_element=hi_el,
                                               failure_mode=hi_mode, outcome="limit_found" if "undetermined" not in flags else "undetermined",
                                               bracket_kt=[round(lo, 2), round(hi, 2)], search_max_kt=req.max_search_kt,
                                               nonmonotone_in_bracket=nonmono or None,
                                               undetermined_at_kt=hi if "undetermined" in flags else None)
                    break
                for x, f in zip(inner, flags):
                    if f == "ok":
                        lo = x
                    else:
                        hi = x
                        break
                while hi - lo > req.tolerance_kt:
                    mid = 0.5 * (lo + hi)
                    st_m, el_m, mode_m, _ = at(mid, warm)
                    if st_m == "ok":
                        lo = mid
                    elif st_m == "fail":
                        hi, hi_el, hi_mode = mid, el_m, mode_m
                    else:
                        break
                point = LimitEnvelopePoint(wind_rel_deg=rel, limit_wind_kt=round(lo, 2), first_failure_element=hi_el, failure_mode=hi_mode,
                                           outcome="limit_found", bracket_kt=[round(lo, 2), round(hi, 2)], search_max_kt=req.max_search_kt)
                break
            lo, warm = v, sol.pose
            v += req.sampling_step_kt
        if point is None:
            point = LimitEnvelopePoint(wind_rel_deg=rel, limit_wind_kt=None, first_failure_element=None, failure_mode="none",
                                       outcome="no_failure_in_range", search_max_kt=req.max_search_kt)
        points.append(point)
    for point in points:
        if point.outcome == "undetermined":
            point.limit_wind_kt = None
        if point.limit_wind_kt is not None:
            point.limit_gust_kt = point.limit_wind_kt * ratio
            point.advisory_gust_kt = point.limit_gust_kt * ADVISORY_GUST_FRACTION
    found = [p for p in points if p.limit_wind_kt is not None]
    worst = min(found, key=lambda p: p.limit_wind_kt) if found else next(
        (p for p in points if p.outcome == "undetermined"), points[0])
    # response-level status and validity
    from .solver import _validity
    from mooring.loads.validity import wind_basis
    from mooring.moored import solver as svc
    result0, status0, load_findings = svc.build_result(req, base, sol0, specs, run_rules=False)
    validity = _validity(req, base, sol0, specs, load_findings, wind_basis(req.environment, True))
    gust = req.environment.wind_gust_kt
    status = "GREEN"
    if worst.limit_gust_kt is not None:
        status = "RED" if worst.limit_gust_kt < gust else "AMBER" if worst.advisory_gust_kt < gust else "GREEN"
    if any(p.outcome in ("undetermined", "fails_at_zero_wind") for p in points):
        status = "RED" if any(p.outcome == "fails_at_zero_wind" for p in points) else max(status, "AMBER", key=["GREEN", "AMBER", "RED"].index)
    if any(p.outcome == "undetermined" for p in points) and validity.state != "invalid":
        validity = Validity(state="limited", reasons=validity.reasons + [ValidityReason(
            code="SEARCH_UNDETERMINED", affected_components=[f"wind-rel-{p.wind_rel_deg:g}" for p in points if p.outcome == "undetermined"][:10],
            message="The equilibrium solve failed for some wind bearings; those limits are undetermined, not proven safe.")])
    if validity.state == "invalid":
        status = "RED"
    from .solver import manifest_for
    return envelope(LimitEnvelopeResponse, model="mooring.solver.envelope", request=req,
                    result=LimitEnvelopeResult(points=points, worst=worst), status=status, backend="real", model_version=VERSION,
                    assumptions=[f"Wind raised from 0 kt to {req.max_search_kt:g} kt in {req.sampling_step_kt:g} kt samples, then refined to {req.tolerance_kt:g} kt; "
                                 "failures narrower than the sample step can be missed.",
                                 f"Gust/sustained ratio {ratio:.2f} from the request is held; current, water level and tugs are held.",
                                 "Limit = highest verified speed within every line, fitting and fender limit (MBS design factor "
                                 f"{df:g}); no failure within the range is not 'unlimited'."] + svc.ASSUMPTIONS,
                    validity=validity, manifest=manifest_for(req, base, specs, sol0, {"search": {"step_deg": req.step_deg,
                                                                                                "max_search_kt": req.max_search_kt}}))


def _tide_levels(req: TideSweepRequest, berth) -> list:
    stations = (berth.env_station_ids.wind, berth.env_station_ids.current, berth.env_station_ids.water_level)
    out, t = [], req.from_utc
    fine = timedelta(minutes=min(FINE_STEP_MIN, req.step_min))
    while t <= req.to_utc and len(out) < 2000:
        out.append((t, environment.synthetic(t, "forecast", stations).water_level_mllw_ft))
        t += fine
    return out


def tide_sweep(req: TideSweepRequest) -> TideSweepResponse:
    from mooring import qualification  # noqa: F401
    from mooring.moored import solver as svc

    berth = refdata.berth(req.berth_id)
    base_req = AnalyzeRequest(**req.model_dump(exclude={"from_utc", "to_utc", "step_min", "tending"}))
    install = base_req.installed_at_water_level_mllw_ft if base_req.installed_at_water_level_mllw_ft is not None else base_req.environment.water_level_mllw_ft
    base_req = base_req.model_copy(update={"installed_at_water_level_mllw_ft": install})
    system0, sol0, specs = solve_request(base_req)
    levels = _tide_levels(req, berth)
    df = design_factor(req.mst)
    fine_min = min(FINE_STEP_MIN, req.step_min)
    report_every = max(1, round(req.step_min / fine_min))
    rest0 = {r.ln.line_number: r.model.rest_length_ft for r in system0.lines}
    tend = sorted(req.tending, key=lambda x: x.at_utc)
    unknown = [x.line_number for x in tend if x.line_number not in rest0]
    if unknown:
        raise refdata.InvalidReference(f"tending refers to unknown line numbers {sorted(set(unknown))}")
    steps, recommended, applied, failed_times = [], [], [], []
    ext: dict[int, dict] = {}
    pose = Pose()
    initial_t = {r.ln.line_number: t for r, _, t in system0.line_tensions(sol0.pose)}
    initial_len = {r.ln.line_number: s.length_ft for r, s, _ in system0.line_tensions(sol0.pose)}
    recommended_for: dict[tuple[int, str], bool] = {}
    for i, (t, wl) in enumerate(levels):
        system = dataclasses.replace(system0, env=req.environment.model_copy(update={"water_level_mllw_ft": wl}),
                                     lines=[dataclasses.replace(r, model=dataclasses.replace(r.model)) for r in system0.lines])
        for r in system.lines:  # rest lengths follow explicit tending only
            adj = sum((x.amount_ft if x.action == "slack" else -x.amount_ft) for x in tend if x.line_number == r.ln.line_number and x.at_utc <= t)
            r.model.rest_length_ft = rest0[r.ln.line_number] + adj
        sol = eq.solve(system, pose)
        report = i % report_every == 0
        if not sol.converged:
            failed_times.append(t.isoformat())
            if report:
                steps.append(TideStep(valid_at_utc=t, water_level_mllw_ft=wl, lines=[], valid=False))
            continue
        pose = sol.pose
        tens = {r.ln.line_number: (s, tt, r) for r, s, tt in system.line_tensions(pose)}
        pct = {n: 100 * tt / (r.model.mbs_eff_lbf / df) for n, (s, tt, r) in tens.items()}
        for n, (s, tt, r) in tens.items():
            e = ext.setdefault(n, {"max": tt, "max_t": t, "min": tt, "min_t": t, "pct": pct[n]})
            if tt > e["max"]:
                e["max"], e["max_t"] = tt, t
            if tt < e["min"]:
                e["min"], e["min_t"] = tt, t
            e["pct"] = max(e["pct"], pct[n])
            # advisory only, once per line and direction, at fine-step resolution
            if pct[n] > 80 and not recommended_for.get((n, "slack")):
                recommended_for[(n, "slack")] = True
                recommended.append(TendingAction(at_utc=t, line_number=n, action="slack", amount_ft=round(abs(s.length_ft - initial_len[n]), 2) or 0.01))
            elif tt < 0.25 * initial_t[n] and not recommended_for.get((n, "heave")):
                recommended_for[(n, "heave")] = True
                recommended.append(TendingAction(at_utc=t, line_number=n, action="heave", amount_ft=round(abs(s.length_ft - initial_len[n]), 2) or 0.01))
        if report:
            steps.append(TideStep(valid_at_utc=t, water_level_mllw_ft=wl, valid=True,
                                  lines=[LineTension(line_number=n, tension_lbf=round(tt)) for n, (s, tt, r) in sorted(tens.items())],
                                  max_pct_wll=round(max(pct.values()), 1) if pct else None))
    _, status0, load_findings = svc.build_result(base_req, system0, sol0, specs, run_rules=False)
    from mooring.loads.validity import wind_basis
    validity = svc._validity(base_req, system0, sol0, specs, load_findings, wind_basis(base_req.environment, True))
    if failed_times:
        shown = ", ".join(failed_times[:3]) + (f" and {len(failed_times) - 3} more" if len(failed_times) > 3 else "")
        validity = Validity(state="invalid", reasons=validity.reasons + [ValidityReason(
            code="STEP_SOLVE_FAILED", affected_components=["sweep"],
            message=f"Equilibrium did not converge at {len(failed_times)} of {len(levels)} evaluated times ({shown}); those times are undetermined.")],
            diagnostics=validity.diagnostics)
    peak = max((e["pct"] for e in ext.values()), default=0.0)
    status = "RED" if peak > 100 else "AMBER" if peak > 80 or recommended else "GREEN"
    if validity.state == "invalid":
        status = "RED"
    result = TideSweepResult(
        steps=steps, tending=recommended, time_resolution_min=fine_min, applied_tending=[TendingAction(at_utc=x.at_utc, line_number=x.line_number, action=x.action, amount_ft=x.amount_ft) for x in tend] or None,
        line_extremes=[LineExtreme(line_number=n, max_tension_lbf=round(e["max"]), max_at_utc=e["max_t"], max_pct_wll=round(e["pct"], 1),
                                   min_tension_lbf=round(e["min"]), min_at_utc=e["min_t"]) for n, e in sorted(ext.items())])
    return envelope(TideSweepResponse, model="mooring.solver.tide_sweep", request=req, result=result, status=status, backend="real",
                    model_version=VERSION, validity=validity,
                    assumptions=[f"Rest lengths installed at water level {install:g} ft MLLW and held; only explicit tending inputs change them. Nothing is retensioned silently.",
                                 f"Evaluated every {fine_min:g} min (reported every {req.step_min} min); extremes between reported steps are captured at that resolution.",
                                 "Water level from the environment service (mock tide model until S04 providers are enabled).",
                                 "Recommended tending is advisory: it is not applied to the reported tensions."] + svc.ASSUMPTIONS,
                    manifest=svc.manifest_for(base_req, system0, specs, sol0, {"sweep": {"from": req.from_utc.isoformat(), "to": req.to_utc.isoformat(),
                                                                                         "step_min": req.step_min, "tending": [x.model_dump(mode="json") for x in tend]}}))
