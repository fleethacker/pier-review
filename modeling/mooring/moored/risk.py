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

from mooring import environment, refdata
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
    berth = refdata.berth(req.berth_id)
    stations = (berth.env_station_ids.wind, berth.env_station_ids.current, berth.env_station_ids.water_level)
    base_req = AnalyzeRequest(**req.model_dump(exclude={"forecast_hours", "step_min", "start_utc", "n_samples_per_step"}))
    system, sol0, specs = solver.solve_request(base_req)
    df = design_factor(req.mst)
    start = req.start_utc or utcnow().replace(minute=0, second=0, microsecond=0)
    n = int(req.forecast_hours * 60 / req.step_min) + 1
    sampler = unc.Sampler(unc.SYNTHETIC_DEMO, 1)
    steps, first_amber, first_red, actions, warm, failed = [], None, None, [], sol0.pose, []
    peaks: dict[str, tuple[float, str]] = {}
    for i in range(n):
        if ctx is not None:
            ctx.check_cancelled()
            ctx.progress(i / n, f"step {i} of {n}")
        t = start + timedelta(minutes=i * req.step_min)
        env = environment.synthetic(t, "forecast", stations)
        sysm = dataclasses.replace(system, env=env)
        sol = eq.solve(sysm, warm)
        if not sol.converged:
            failed.append(t.isoformat())
            steps.append(TimelineStep(valid_at_utc=t, status="RED", wind_speed_kt=env.wind_speed_kt, wind_gust_kt=env.wind_gust_kt,
                                      p_any_exceeds_wll=None, governing_element="undetermined", valid=False))
            continue
        warm = sol.pose
        worst_el = max(utilization(sysm, sol.pose, df), key=lambda e: e[1])
        status = "RED" if worst_el[1] > 100 else "AMBER" if worst_el[1] > 80 else "GREEN"
        if status != "GREEN" and first_amber is None:
            first_amber = t
        if status == "RED" and first_red is None:
            first_red = t
        if status == "RED":
            actions.append(f"{worst_el[0]} reaches {worst_el[1]:.0f}% of its limit at {t:%H:%MZ}; review additional lines, tending or tugs.")
        p = None
        if req.n_samples_per_step > 0:
            tl, _ = monte_carlo(lambda env=env: sampler.instant(env),
                                lambda e: _eval_env(dataclasses.replace(system, env=e), warm, df), req.n_samples_per_step)
            nv = tl.n - tl.failed
            p = round(tl.any_wll / nv, 4) if nv else None
        steps.append(TimelineStep(valid_at_utc=t, status=status, wind_speed_kt=env.wind_speed_kt, wind_gust_kt=env.wind_gust_kt,
                                  p_any_exceeds_wll=p, governing_element=worst_el[0], max_pct_wll=round(worst_el[1], 1), valid=True))
    base_validity = solver_validity(req, base_req, system, sol0, specs)
    reasons = list(base_validity.reasons)
    if failed:
        reasons.append(ValidityReason(code="STEP_SOLVE_FAILED", affected_components=["timeline"],
                                      message=f"Equilibrium failed at {len(failed)} of {n} steps ({', '.join(failed[:3])}{'...' if len(failed) > 3 else ''}); those steps are undetermined."))
    if req.n_samples_per_step > 0:
        reasons.append(ValidityReason(code="UNQUALIFIED_UNCERTAINTY_MODEL", affected_components=["synthetic-demo"],
                                      message="Per-step probabilities use the synthetic model: scenario outputs only."))
    state = "invalid" if base_validity.state == "invalid" or failed else "limited" if reasons else "valid"
    validity = Validity(state=state, reasons=reasons, diagnostics=base_validity.diagnostics)
    overall = "RED" if first_red or failed else "AMBER" if first_amber else "GREEN"
    return envelope(TimelineResponse, model="mooring.risk.timeline", request=req, backend="real", model_version="1.0.0",
                    result=TimelineResult(steps=steps, first_amber_utc=first_amber, first_red_utc=first_red, recommended_actions=actions),
                    status=status_with_validity(overall, validity), validity=validity,
                    manifest=solver.manifest_for(base_req, system, specs, sol0, {"timeline": {"start": start.isoformat(), "step_min": req.step_min}}),
                    assumptions=["Each step is a deterministic equilibrium at the forecast environment (mock synthetic forecast until providers are enabled).",
                                 "p_any_exceeds_wll is pointwise per step and present only when n_samples_per_step > 0; it is not a horizon probability.",
                                 *solver.ASSUMPTIONS])


def alert_for(env: EnvironmentSnapshot, analyze_req: AnalyzeRequest | None) -> Alert:
    """Live alert from the current environment: deterministic equilibrium, with event time and freshness."""
    meta = env.metadata
    stale = bool(meta and meta.age_s is not None and meta.age_s > STALE_AFTER_S) or any(q.age_s > STALE_AFTER_S for q in env.quality)
    if analyze_req is None:
        return Alert(alert_id=new_id("alr"), at_utc=env.valid_at_utc, severity="INFO", element_id=None, env=env, stale=stale,
                     provenance="observation only; no mooring plan to evaluate",
                     message=f"Wind {env.wind_speed_kt:.0f} kt gusting {env.wind_gust_kt:.0f} kt from {env.wind_from_true_deg:03.0f}.")
    system, sol, specs = solver.solve_request(analyze_req.model_copy(update={"environment": env}))
    df = design_factor(analyze_req.mst)
    if not sol.converged:
        return Alert(alert_id=new_id("alr"), at_utc=env.valid_at_utc, severity="RED", element_id=None, env=env, stale=stale,
                     provenance="deterministic equilibrium (did not converge)", message="Equilibrium solve failed; condition undetermined.")
    el, pct, mode = max(utilization(system, sol.pose, df), key=lambda e: e[1])
    sev = "RED" if pct > 100 else "AMBER" if pct > 80 else "INFO"
    return Alert(alert_id=new_id("alr"), at_utc=env.valid_at_utc, severity=sev, element_id=el, env=env, stale=stale,
                 provenance="deterministic equilibrium at the current environment; no probability",
                 message=f"Gust {env.wind_gust_kt:.0f} kt: {el} at {pct:.0f}% of its {mode} limit." + (" Environment data is stale." if stale else ""))
