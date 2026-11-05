"""Gust risk (M5, S11): Monte Carlo exceedance, forecast timeline and live alerts on the real equilibrium solver.

Honest by construction:
* The requested sample count is run or rejected by the schema (20,000 maximum); it is never silently capped.
* Every sample is accounted for: valid, or failed (equilibrium did not converge). Failed samples are reported and bound
  the probability; they are not dropped from the denominator without disclosure.
* Probabilities carry 95% Wilson intervals. The error criterion is the interval half-width, not a fixed accuracy claim.
* A probability is only as good as its uncertainty model. The default model is synthetic and unqualified, so the result is
  limited and labeled a scenario output.
* The instantaneous probability is not a probability over a horizon. A horizon probability is produced only from
  time-correlated trajectories (`include_horizon`), with the event stated; otherwise the result says it is pointwise only.
* Lines are compared with WLL and MBS; fittings with rated capacity; fenders with rated energy. No MBS is invented for
  elements that have none.
* The dynamic factor is a force multiplier on the wind force, applied once (wind speed scaled by sqrt(factor)).
"""

import dataclasses
import math
import statistics
from collections.abc import Callable
from datetime import timedelta

from mooring import refdata
from mooring.core.envelopes import envelope, new_id, status_with_validity, utcnow
from mooring.core.schemas import (
    Alert, AnalyzeRequest, ElementRisk, EnvironmentSnapshot, ExceedanceRequest, ExceedanceResponse, ExceedanceResult, Finding,
    HorizonRisk, TimelineRequest, TimelineResponse, TimelineResult, TimelineStep, Validity, ValidityReason,
)
from mooring.environment import uncertainty as unc
from mooring.mechanics import Pose
from mooring.rules.nstm582 import design_factor

from mooring.mechanics import equilibrium as eq
from . import solver
from .envelopes_real import utilization

STALE_AFTER_S = 1800.0
Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion; (0, 1) when n = 0."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def get_model(model_id: str | None):
    try:
        return unc.load_model(model_id or unc.SYNTHETIC_DEMO.model_id)
    except KeyError:
        raise refdata.InvalidReference(f"Unknown uncertainty model '{model_id}'; available: {', '.join(unc.available_models())}") from None


@dataclasses.dataclass
class Tally:
    n: int = 0
    failed: int = 0
    any_wll: int = 0
    any_mbs: int = 0


def monte_carlo(draw: Callable[[], object], evaluate: Callable[[object], dict | None], n: int, progress: Callable[[int], None] | None = None):
    """Generic sampler: `evaluate` returns {element: (load, wll_limit, mbs_limit | None)} or None for a failed sample."""
    tally, per = Tally(n=n), {}
    for i in range(n):
        if progress and i % 50 == 0:
            progress(i)
        out = evaluate(draw())
        if out is None:
            tally.failed += 1
            continue
        hit_wll = hit_mbs = False
        for el, (load, wll, mbs) in out.items():
            rec = per.setdefault(el, {"loads": [], "wll": 0, "mbs": 0, "has_mbs": mbs is not None})
            rec["loads"].append(load)
            if load > wll:
                rec["wll"] += 1
                hit_wll = True
            if mbs is not None and load >= mbs:
                rec["mbs"] += 1
                hit_mbs = True
        tally.any_wll += hit_wll
        tally.any_mbs += hit_mbs
    if progress:
        progress(n)
    return tally, per


def _quantile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1)))]


def _eval_env(system: eq.System, warm: Pose, df: float):
    """Solve for one environment; returns per-element (load, wll, mbs) or None if the solve failed."""
    sol = eq.solve(system, warm)
    if not sol.converged:
        return None
    out = {}
    for rec, st, t in system.line_tensions(sol.pose):
        mbs = rec.model.mbs_eff_lbf
        out[f"line-{rec.ln.line_number}"] = (t, mbs / df, mbs)
    acc_p: dict[str, list[float]] = {}
    acc_s: dict[str, list[float]] = {}
    for rec, st, t in system.line_tensions(sol.pose):
        for acc, fid in ((acc_p, rec.ln.pier_fitting_id), (acc_s, rec.ln.ship_fitting_id)):
            v = acc.setdefault(fid, [0.0, 0.0, 0.0])
            v[0] += t * st.ux; v[1] += t * st.uy; v[2] += t * st.uz
    cap = {f.fitting_id: f.capacity_nominal_lbf for f in system.berth.fittings}
    for fid, v in acc_p.items():
        out[fid] = (math.sqrt(sum(c * c for c in v)), cap[fid], None)
    ship_cap = {f.fitting_id: f.swl_lbf for f in system.ship.fittings}
    for fid, v in acc_s.items():
        if ship_cap[fid]:
            out[fid] = (math.sqrt(sum(c * c for c in v)), ship_cap[fid], None)
    for fr, d, _ in system.fender_loads(sol.pose):
        if fr.model.rated_energy_ftlbf:
            out[fr.model.fender_id] = (fr.model.energy(d), fr.model.rated_energy_ftlbf, None)
    return out


def _with_dynamic(env: EnvironmentSnapshot, factor: float) -> EnvironmentSnapshot:
    """Scale the wind force by `factor` exactly once: force ~ speed^2, so scale the speed by sqrt(factor)."""
    if factor == 1.0:
        return env
    return env.model_copy(update={"wind_gust_kt": env.wind_gust_kt * math.sqrt(factor)})


def exceedance(req: ExceedanceRequest, ctx=None) -> ExceedanceResponse:
    model = get_model(req.uncertainty_model_id)
    base_req = AnalyzeRequest(**req.model_dump(exclude={"horizon_hours", "n_samples", "seed", "gust_dynamic_factor", "uncertainty_model_id",
                                                        "include_horizon", "n_trajectories", "horizon_step_min"}))
    system, sol0, specs = solver.solve_request(base_req)
    df = design_factor(req.mst)
    sampler = unc.Sampler(model, req.seed)
    warm = sol0.pose

    def evaluate(env):
        return _eval_env(dataclasses.replace(system, env=_with_dynamic(env, req.gust_dynamic_factor)), warm, df)

    def progress(i):
        if ctx is not None:
            ctx.check_cancelled()
            ctx.progress(0.9 * i / req.n_samples, f"{i} of {req.n_samples} samples")

    tally, per = monte_carlo(lambda: sampler.instant(req.environment), evaluate, req.n_samples, progress)
    n_valid = tally.n - tally.failed
    elements = []
    for el, rec in per.items():
        k = rec["wll"]
        elements.append(ElementRisk(
            element_id=el, p_exceed_wll=k / n_valid, p_exceed_mbs=(rec["mbs"] / n_valid) if rec["has_mbs"] else None,
            tension_p50_lbf=round(statistics.median(rec["loads"])), tension_p95_lbf=round(_quantile(rec["loads"], 0.95)),
            p_exceed_wll_ci95=[round(x, 6) for x in wilson(k, n_valid)]))
    governing = max(elements, key=lambda e: (e.p_exceed_wll, e.tension_p95_lbf)).element_id if elements else "none"
    p_any = tally.any_wll / n_valid if n_valid else 0.0
    lo, hi = wilson(tally.any_wll, n_valid)
    horizon = None
    if req.include_horizon:
        horizon = _horizon(req, system, specs, sol0, model, df, ctx)
        if ctx is not None:
            ctx.progress(0.99, "horizon done")
    result = ExceedanceResult(
        n_samples=tally.n, p_any_exceeds_wll=p_any, p_any_exceeds_mbs=(tally.any_mbs / n_valid) if n_valid else 0.0, elements=elements,
        governing_element=governing, n_valid=n_valid, n_failed=tally.failed, p_any_ci95=[round(lo, 6), round(hi, 6)],
        p_any_bounds=[tally.any_wll / tally.n, (tally.any_wll + tally.failed) / tally.n], seed=req.seed, uncertainty_model=model,
        pointwise_only=horizon is None, horizon=horizon,
        error_criterion=f"95% Wilson interval half-width {(hi - lo) / 2:.4f} at n_valid={n_valid}; no fixed accuracy claim.")
    reasons = []
    if model.qualification != "qualified":
        reasons.append(ValidityReason(code="UNQUALIFIED_UNCERTAINTY_MODEL", affected_components=[model.model_id],
                                      message="; ".join(model.qualification_reasons[:3]) + " The probabilities are scenario outputs, not risk estimates."))
    if tally.failed:
        reasons.append(ValidityReason(code="FAILED_SAMPLES", affected_components=["sampling"],
                                      message=f"{tally.failed} of {tally.n} samples failed to converge; see p_any_bounds."))
    if horizon is not None and horizon.n_failed:
        reasons.append(ValidityReason(code="FAILED_TRAJECTORIES", affected_components=["horizon"],
                                      message=f"{horizon.n_failed} of {horizon.n_trajectories} trajectories are unresolved; p_event is a lower bound, not a complete probability. See p_event_bounds."))
    no_valid_samples = n_valid == 0 or (horizon is not None and horizon.n_failed == horizon.n_trajectories)
    if no_valid_samples:
        reasons.append(ValidityReason(code="NO_VALID_RISK_SAMPLES", affected_components=["sampling"],
                                      message="No successful samples in at least one requested risk calculation; zero known exceedances does not establish safety."))
    warnings = []
    if horizon is None:
        warnings.append(Finding(rule_id="RISK-HORIZON-UNSUPPORTED", severity="INFO", element_ids=[], reference="S11",
                                message=f"Pointwise probability only: no probability over the {req.horizon_hours:g} h horizon was computed (set include_horizon)."))
    base_validity = solver_validity(req, base_req, system, sol0, specs)
    state = "invalid" if base_validity.state == "invalid" or no_valid_samples else "limited" if reasons or base_validity.state == "limited" else "valid"
    validity = Validity(state=state, reasons=base_validity.reasons + reasons, diagnostics=base_validity.diagnostics)
    status = "RED" if p_any > 0.10 else "AMBER" if p_any > 0.01 else "GREEN"
    return envelope(ExceedanceResponse, model="mooring.risk.monte_carlo", request=req, result=result, backend="real", model_version="1.0.0",
                    status=status_with_validity(status, validity), validity=validity, warnings=warnings,
                    manifest=solver.manifest_for(base_req, system, specs, sol0, {"risk": {"seed": req.seed, "n": req.n_samples, "model": model.model_dump(mode="json"),
                                                                                         "dynamic_factor": req.gust_dynamic_factor}}).model_copy(
                        update={"rng_seed": req.seed, "rng_model_revision": f"{model.model_id}@{model.revision}"}),
                    assumptions=[f"{tally.n} instantaneous samples of gust factor, direction and current from model '{model.model_id}' r{model.revision}; each solved to equilibrium.",
                                 "Failed samples are counted, reported and used to bound the probability.", "No dynamic or snatch amplification is modeled; the dynamic factor, if any, scales wind force once.",
                                 *solver.ASSUMPTIONS])


def solver_validity(req, base_req, system, sol0, specs) -> Validity:
    from mooring.loads.validity import wind_basis
    result, status, load_findings = solver.build_result(base_req, system, sol0, specs, run_rules=False)
    return solver._validity(base_req, system, sol0, specs, load_findings, wind_basis(base_req.environment, True))


def _horizon(req: ExceedanceRequest, system, specs, sol0, model, df, ctx=None) -> HorizonRisk:
    intervals = max(1, math.ceil(req.horizon_hours * 60 / req.horizon_step_min))
    effective_step = req.horizon_hours * 60 / intervals
    sampler = unc.Sampler(model, None if req.seed is None else req.seed + 1)
    hits = failed = 0
    for i in range(req.n_trajectories):
        if ctx is not None:
            ctx.check_cancelled()
            ctx.progress(0.9 + 0.09 * i / req.n_trajectories, f"trajectory {i} of {req.n_trajectories}")
        hit = False
        for env in sampler.trajectory(req.environment, intervals + 1, effective_step):
            if ctx is not None:
                ctx.check_cancelled()
            out = _eval_env(dataclasses.replace(system, env=_with_dynamic(env, req.gust_dynamic_factor)), sol0.pose, df)
            if out is None:
                failed += 1
                hit = None if not hit else hit
                break
            if any(load > wll for load, wll, _ in out.values()):
                hit = True
                break
        hits += bool(hit)
    n = req.n_trajectories
    lo, _ = wilson(hits, n)
    _, hi = wilson(hits + failed, n)
    return HorizonRisk(event="any line (WLL), ship/pier fitting (rated capacity) or fender (rated energy) exceeded at a sampled step; unresolved trajectories are unknown",
                       n_trajectories=req.n_trajectories, step_min=req.horizon_step_min, horizon_hours=req.horizon_hours,
                       p_event=hits / n, p_event_ci95=[round(lo, 6), round(hi, 6)], n_failed=failed,
                       correlation_time_min=model.correlation_time_min,
                       p_event_bounds=[hits / n, (hits + failed) / n], effective_step_min=effective_step)


def timeline(req: TimelineRequest, ctx=None) -> TimelineResponse:
    from mooring.data_simulation.timeline import sample as training_sample

    berth = refdata.berth(req.berth_id)
    stations = (berth.env_station_ids.wind, berth.env_station_ids.current, berth.env_station_ids.water_level)
    base_req = AnalyzeRequest(**req.model_dump(exclude={"forecast_hours", "step_min", "start_utc", "n_samples_per_step", "forecast"}))
    system, sol0, specs = solver.solve_request(base_req)
    df = design_factor(req.mst)
    start = req.start_utc or utcnow().replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=req.forecast_hours)
    synthetic = req.forecast is None
    if synthetic:
        times = [start + timedelta(minutes=i) for i in range(0, req.forecast_hours * 60, req.step_min)] + [end]
        forcing = [training_sample(t, stations) for t in times]
    else:
        forcing = [s for s in req.forecast if start <= s.valid_at_utc <= end]
    sampler = unc.Sampler(unc.SYNTHETIC_DEMO, 1)
    steps, actions, warm = [], [], sol0.pose
    base_validity = solver_validity(req, base_req, system, sol0, specs)
    reasons = list(base_validity.reasons)
    if synthetic:
        reasons.append(ValidityReason(code="SYNTHETIC_TIMELINE", affected_components=["timeline"],
            message="No forecast supplied: this is a synthetic training timeline, independent of the configured provider."))
    if req.n_samples_per_step > 0:
        reasons.append(ValidityReason(code="UNQUALIFIED_UNCERTAINTY_MODEL", affected_components=["synthetic-demo"],
            message="Per-step probabilities use the synthetic model: scenario outputs only."))
    common_reasons = list(reasons)
    for i, env in enumerate(forcing):
        if ctx is not None:
            ctx.check_cancelled()
            ctx.progress(i / len(forcing), f"step {i} of {len(forcing)}")
        sysm = dataclasses.replace(system, env=env)
        sol = eq.solve(sysm, warm)
        condition_req = base_req.model_copy(update={"environment": env})
        condition_validity = solver_validity(req, condition_req, sysm, sol, specs)
        condition_reasons = [*common_reasons, *condition_validity.reasons]
        n_valid = n_failed = p = bounds = None
        worst_el, pct = "undetermined", None
        status = "RED"
        if sol.converged and condition_validity.state != "invalid":
            warm = sol.pose
            worst_el, pct, _ = max(utilization(sysm, sol.pose, df), key=lambda e: e[1])
            status = "RED" if pct > 100 else "AMBER" if pct > 80 else "GREEN"
            if pct > 100:
                actions.append(f"{worst_el} reaches {pct:.0f}% of its limit at {env.valid_at_utc:%H:%MZ}; review additional lines, tending or tugs.")
            if req.n_samples_per_step > 0:
                def check_sampling(_):
                    if ctx is not None:
                        ctx.check_cancelled()
                tally, _ = monte_carlo(lambda env=env: sampler.instant(env),
                    lambda e: _eval_env(dataclasses.replace(system, env=e), warm, df), req.n_samples_per_step, check_sampling)
                n_valid, n_failed = tally.n - tally.failed, tally.failed
                p = round(tally.any_wll / n_valid, 4) if n_valid else None
                bounds = [tally.any_wll / tally.n, (tally.any_wll + tally.failed) / tally.n]
                if n_failed:
                    condition_reasons.append(ValidityReason(code="FAILED_SAMPLES", affected_components=["timeline"],
                        message=f"{n_failed} of {tally.n} samples failed at {env.valid_at_utc.isoformat()}; see p_any_bounds."))
        else:
            actions.append(f"Condition at {env.valid_at_utc:%H:%MZ} is invalid or undetermined; recheck inputs and the plan.")
        if not sol.converged:
            condition_reasons.append(ValidityReason(code="STEP_SOLVE_FAILED", affected_components=["timeline"],
                message=f"Equilibrium failed at {env.valid_at_utc.isoformat()}; the condition is undetermined."))
        invalid = base_validity.state == "invalid" or not sol.converged or condition_validity.state == "invalid" or n_valid == 0
        if n_valid == 0:
            condition_reasons.append(ValidityReason(code="NO_VALID_RISK_SAMPLES", affected_components=["timeline"],
                message=f"No successful risk samples at {env.valid_at_utc.isoformat()}; no probability established."))
        state = "invalid" if invalid else "limited" if synthetic or reasons or condition_reasons else "valid"
        step_validity = condition_validity.model_copy(update={"state": state, "reasons": condition_reasons})
        steps.append(TimelineStep(valid_at_utc=env.valid_at_utc, status=status_with_validity(status, step_validity),
            wind_speed_kt=env.wind_speed_kt, wind_gust_kt=env.wind_gust_kt, p_any_exceeds_wll=p,
            governing_element=worst_el, max_pct_wll=round(pct, 1) if pct is not None else None,
            valid=not invalid, environment=env, validity=step_validity, n_valid=n_valid, n_failed=n_failed, p_any_bounds=bounds))
        reasons.extend(condition_reasons)
    # Repeated seed/geometry reasons need one entry, while timestamped failures remain distinct.
    reasons = list({(r.code, r.message, tuple(r.affected_components)): r for r in reasons}.values())
    state = "invalid" if base_validity.state == "invalid" or any(not s.valid for s in steps) else "limited" if reasons else "valid"
    validity = Validity(state=state, reasons=reasons, diagnostics=base_validity.diagnostics)
    first_amber = next((s.valid_at_utc for s in steps if s.status != "GREEN"), None)
    first_red = next((s.valid_at_utc for s in steps if s.status == "RED"), None)
    overall = "RED" if first_red else "AMBER" if first_amber else "GREEN"
    return envelope(TimelineResponse, model="mooring.risk.timeline", request=req, backend="real", model_version="1.0.0",
        result=TimelineResult(steps=steps, first_amber_utc=first_amber, first_red_utc=first_red, recommended_actions=actions,
                              forcing_source="synthetic_training" if synthetic else "supplied"),
        status=status_with_validity(overall, validity), validity=validity,
        manifest=solver.manifest_for(base_req, system, specs, sol0, {"timeline": {"start": start.isoformat(),
            "step_min": req.step_min, "forcing": [s.model_dump(mode="json") for s in forcing]}}),
        assumptions=["Synthetic training conditions; not a forecast and not replaced when providers are enabled." if synthetic else
                     "Every supplied snapshot in the horizon is evaluated without interpolation or extrapolation; peaks between snapshots remain unresolved.",
                     "Line installation lengths stay fixed at the request environment's installation water level unless explicitly provided in config.",
                     "p_any_exceeds_wll is pointwise per step among valid samples, not a horizon probability; failed samples have explicit bounds.",
                     *solver.ASSUMPTIONS])


def alert_for(env: EnvironmentSnapshot, analyze_req: AnalyzeRequest | None) -> Alert:
    """Current-condition diagnostics; invalid inputs never produce usable utilization."""
    from mooring.loads.validity import environment_findings

    meta = env.metadata
    stale = bool(meta and meta.age_s is not None and meta.age_s > STALE_AFTER_S) or any(q.age_s > STALE_AFTER_S for q in env.quality)
    findings = environment_findings(env)
    if stale:
        findings.append(("limited", ValidityReason(code="ALERT_ENVIRONMENT_STALE",
            message="Environment data is stale for the live alert freshness policy.", affected_components=["environment"])))
    reasons = [reason for _, reason in findings]
    invalid = any(state == "invalid" for state, _ in findings)

    def emit(severity, message, validity, element=None, provenance="deterministic equilibrium at the current environment; no probability"):
        return Alert(alert_id=new_id("alr"), at_utc=env.valid_at_utc, severity=severity, element_id=element,
                     env=env, stale=stale, validity=validity, provenance=provenance,
                     message=message + (" Environment data is stale." if stale else ""))

    if invalid:
        return emit("RED", "Environmental inputs are invalid; mooring condition is undetermined.",
                    Validity(state="invalid", reasons=reasons), provenance="input validation; no usable mooring assessment")
    if analyze_req is None:
        reasons.append(ValidityReason(code="ALERT_NO_PLAN", message="No mooring plan was supplied; observations do not establish mooring adequacy."))
        return emit("AMBER" if findings else "INFO",
                    f"Observation only: wind {env.wind_speed_kt:.0f} kt gusting {env.wind_gust_kt:.0f} kt from {env.wind_from_true_deg:03.0f}; no plan assessed.",
                    Validity(state="limited", reasons=reasons), provenance="observation only; no mooring plan to evaluate")
    installation_tide = analyze_req.installed_at_water_level_mllw_ft
    if installation_tide is None:
        installation_tide = analyze_req.environment.water_level_mllw_ft
    current_req = analyze_req.model_copy(update={"environment": env,
                                                "installed_at_water_level_mllw_ft": installation_tide})
    try:
        system, sol, specs = solver.solve_request(current_req)
    except (refdata.InvalidReference, refdata.NotFound) as exc:
        return emit("RED", "Plan inputs cannot be evaluated; mooring condition is undetermined.",
                    Validity(state="invalid", reasons=[*reasons, ValidityReason(code="ALERT_PLAN_INVALID", message=str(exc))]))
    validity = solver_validity(current_req, current_req, system, sol, specs)
    if stale:
        validity = validity.model_copy(update={"state": "invalid" if validity.state == "invalid" else "limited",
                                               "reasons": [*validity.reasons, reasons[-1]]})
    if validity.state == "invalid":
        return emit("RED", "Mooring assessment is invalid; condition undetermined. No usable utilization is reported.", validity)
    df = design_factor(analyze_req.mst)
    el, pct, mode = max(utilization(system, sol.pose, df), key=lambda e: e[1])
    sev = "RED" if pct > 100 else "AMBER" if pct > 80 or validity.state == "limited" else "INFO"
    note = " Limited assessment; review validity reasons." if validity.state == "limited" else ""
    return emit(sev, f"Gust {env.wind_gust_kt:.0f} kt: {el} at {pct:.0f}% of its {mode} limit." + note, validity, el)
