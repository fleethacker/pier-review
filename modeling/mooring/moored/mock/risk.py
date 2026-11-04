"""Mock risk engine (M5): small Monte Carlo over gust, direction and current using the mock solver."""

import random
import statistics
from datetime import timedelta

from mooring import refdata
from mooring.core.schemas import (
    Alert,
    AnalyzeRequest,
    ElementRisk,
    EnvironmentSnapshot,
    ExceedanceRequest,
    ExceedanceResponse,
    ExceedanceResult,
    TimelineRequest,
    TimelineResponse,
    TimelineResult,
    TimelineStep,
)

from mooring import environment
from mooring.core.envelopes import envelope, new_id, utcnow
from .solver import solve

MAX_MOCK_SAMPLES = 300


def _sample_env(env: EnvironmentSnapshot, rng: random.Random, dyn: float) -> EnvironmentSnapshot:
    gf = rng.lognormvariate(0.27, 0.08)  # gust factor around 1.3
    return env.model_copy(update={
        "wind_gust_kt": env.wind_speed_kt * gf * dyn,
        "wind_from_true_deg": (env.wind_from_true_deg + rng.gauss(0, 15)) % 360,
        "current_speed_kt": max(0.0, env.current_speed_kt + rng.gauss(0, 0.15)),
    })


def exceedance(req: ExceedanceRequest) -> ExceedanceResponse:
    rng = random.Random(req.seed)
    base = AnalyzeRequest(**req.model_dump(exclude={"horizon_hours", "n_samples", "seed", "gust_dynamic_factor"}))
    n = min(req.n_samples, MAX_MOCK_SAMPLES)
    tensions: dict[str, list[float]] = {}
    over_wll: dict[str, int] = {}
    over_mbs: dict[str, int] = {}
    any_wll = any_mbs = 0
    for _ in range(n):
        s = solve(base.model_copy(update={"environment": _sample_env(req.environment, rng, req.gust_dynamic_factor)}),
                  run_rules=False)
        hit_wll = hit_mbs = False
        for r in s.result.lines:
            eid = f"line-{r.line_number}"
            tensions.setdefault(eid, []).append(r.tension_lbf)
            if r.pct_wll > 100:
                over_wll[eid] = over_wll.get(eid, 0) + 1
                hit_wll = True
            if r.pct_mbs >= 100:
                over_mbs[eid] = over_mbs.get(eid, 0) + 1
                hit_mbs = True
        any_wll += hit_wll
        any_mbs += hit_mbs
    elements = []
    for eid, ts in tensions.items():
        ts_sorted = sorted(ts)
        elements.append(ElementRisk(
            element_id=eid, p_exceed_wll=over_wll.get(eid, 0) / n, p_exceed_mbs=over_mbs.get(eid, 0) / n,
            tension_p50_lbf=round(statistics.median(ts_sorted)), tension_p95_lbf=round(ts_sorted[int(0.95 * (n - 1))])))
    governing = max(elements, key=lambda e: (e.p_exceed_wll, e.tension_p95_lbf)).element_id if elements else "none"
    p_any = any_wll / n
    status = "RED" if p_any > 0.10 else "AMBER" if p_any > 0.01 else "GREEN"
    result = ExceedanceResult(n_samples=n, p_any_exceeds_wll=p_any, p_any_exceeds_mbs=any_mbs / n,
                              elements=elements, governing_element=governing)
    return envelope(ExceedanceResponse, model="mooring.risk.monte_carlo", request=req, result=result, status=status,
                    assumptions=[f"Mock: {n} samples (capped at {MAX_MOCK_SAMPLES}); lognormal gust factor ~1.3, "
                                 "direction scatter 15 deg, current scatter 0.15 kt."])


def timeline(req: TimelineRequest) -> TimelineResponse:
    berth = refdata.berth(req.berth_id)
    stations = (berth.env_station_ids.wind, berth.env_station_ids.current, berth.env_station_ids.water_level)
    base = AnalyzeRequest(**req.model_dump(exclude={"forecast_hours", "step_min"}))
    start = utcnow().replace(minute=0, second=0, microsecond=0)
    steps, first_amber, first_red, actions = [], None, None, []
    n = int(req.forecast_hours * 60 / req.step_min) + 1
    for i in range(n):
        t = start + timedelta(minutes=i * req.step_min)
        env = environment.synthetic(t, "forecast", stations)
        s = solve(base.model_copy(update={"environment": env}), run_rules=False)
        top = max(s.result.lines, key=lambda r: r.pct_wll) if s.result.lines else None
        p = min(1.0, max(0.0, (top.pct_wll - 70) / 60)) if top else 0.0  # mock mapping from utilization to risk
        status = "RED" if top and top.pct_wll > 100 else "AMBER" if top and top.pct_wll > 80 else "GREEN"
        if status in ("AMBER", "RED") and first_amber is None:
            first_amber = t
        if status == "RED" and first_red is None:
            first_red = t
            actions.append(f"Double up line {top.line_number} before {t:%H:%MZ}.")
        steps.append(TimelineStep(valid_at_utc=t, status=status, wind_speed_kt=env.wind_speed_kt,
                                  wind_gust_kt=env.wind_gust_kt, p_any_exceeds_wll=round(p, 3),
                                  governing_element=f"line-{top.line_number}" if top else "none"))
    overall = "RED" if first_red else "AMBER" if first_amber else "GREEN"
    return envelope(TimelineResponse, model="mooring.risk.timeline", request=req,
                    result=TimelineResult(steps=steps, first_amber_utc=first_amber, first_red_utc=first_red,
                                          recommended_actions=actions),
                    status=overall, assumptions=["Mock forecast (synthetic tide and wind)."])


def alert_for(env: EnvironmentSnapshot, analyze_req: AnalyzeRequest | None) -> Alert:
    """Build an alert for the live stream from the current environment."""
    if analyze_req is not None:
        s = solve(analyze_req.model_copy(update={"environment": env}), run_rules=False)
        top = max(s.result.lines, key=lambda r: r.pct_wll)
        sev = "RED" if top.pct_wll > 100 else "AMBER" if top.pct_wll > 80 else "INFO"
        return Alert(alert_id=new_id("alr"), at_utc=env.valid_at_utc, severity=sev,
                     element_id=f"line-{top.line_number}",
                     message=f"Gust {env.wind_gust_kt:.0f} kt: line {top.line_number} at {top.pct_wll:.0f}% of WLL.",
                     env=env)
    return Alert(alert_id=new_id("alr"), at_utc=env.valid_at_utc, severity="INFO", element_id=None,
                 message=f"Wind {env.wind_speed_kt:.0f} kt gusting {env.wind_gust_kt:.0f} kt from "
                         f"{env.wind_from_true_deg:03.0f}.", env=env)
