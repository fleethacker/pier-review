"""Static berthing tug plan and berthing windows (S08/S09): tugs carry the whole wrench before any line is fast.

Real: M3 loads at the berthing heading, wrench allocation over the requested fleet (surge, sway, yaw, ratings, one tug per
push point), load-model validity propagated, and windows evaluated over the forecast with full-wrench feasibility,
current/gust limits, coverage and threshold refinement. Not modeled: tug approach, transient maneuvering, line handling,
hull contact (those are M11), certified bollard pull (catalog ratings are estimates).
"""

from datetime import datetime, timedelta

from mooring import environment, refdata
from mooring.core.envelopes import envelope, status_with_validity, worst
from mooring.core.geometry import depth_at, ship_heading_true
from mooring.core.schemas import (
    BerthingTugRequest, BerthingWindow, BerthingWindowRequest, BerthingWindowsResponse, BerthingWindowsResult,
    EnvironmentSnapshot, TugPlanResponse, Validity, ValidityReason,
)
from mooring.loads import compute_loads
from mooring.loads.service import load_metadata
from mooring.loads.validity import merge_reasons
from mooring.tugs.allocation import allocate

FORECAST_HORIZON_H = 48.0   # the environment service's forecast reaches this far past the window start
CODE = "mooring.tugs.allocation@1.0.0"


def _fleet(ids: list[str] | None):
    try:
        return [refdata.tug(t) for t in ids] if ids else refdata.tugs()
    except refdata.NotFound as e:
        raise refdata.InvalidReference(str(e)) from None


def _tug_reasons(fleet) -> list[ValidityReason]:
    est = [t.tug_id for t in fleet if t.provenance.confidence != "published"]
    return [ValidityReason(code="TUG_RATINGS_NOT_CERTIFIED", affected_components=est,
                           message="Bollard pull comes from the catalog (seed/estimated), not a certified rating.")] if est else []


def _plan(ship, berth, side_to, loading, env, margin, fleet):
    heading = ship_heading_true(berth, side_to)
    depth = depth_at(berth, berth.face_length_ft / 2) + env.water_level_mllw_ft
    loads = compute_loads(ship, loading, heading, env, depth, use_gust=True)
    required = (-loads.total.fx_lbf, -loads.total.fy_lbf, -loads.total.mz_ftlbf)  # tugs must cancel the environmental wrench
    plan, _ = allocate(ship, required, fleet, heading_true_deg=heading, margin=margin)
    return plan, loads, depth


def berthing_plan(req: BerthingTugRequest) -> TugPlanResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    refdata.loading(ship, req.loading)
    fleet = _fleet(req.available_tug_ids)
    plan, loads, depth = _plan(ship, berth, req.side_to, req.loading, req.environment, req.margin, fleet)
    assumptions, findings, validity = load_metadata(ship, req.loading, depth, req.environment.water_density_kgm3, True,
                                                    req.environment.current_speed_kt, [loads], req.environment)
    reasons = merge_reasons(validity.reasons + _tug_reasons(fleet))
    state = "invalid" if validity.state == "invalid" else "limited" if reasons else "valid"
    if not plan.feasible and state != "invalid":
        reasons.append(ValidityReason(code="ALLOCATION_INFEASIBLE", affected_components=[b.split("@")[0] for b in plan.binding_constraints][:5] or ["fleet"],
                                      message="The requested fleet cannot supply the full wrench; this is a completed RED result, not an error."))
    validity = Validity(state=state, reasons=reasons)
    base = worst(["GREEN" if plan.feasible else "RED", *(w.severity for w in findings)])
    return envelope(TugPlanResponse, model="mooring.tugs.berthing", request=req, result=plan,
                    status=status_with_validity(base, validity), warnings=findings, validity=validity, backend="real",
                    model_version="1.0.0",
                    assumptions=["No lines fast: tugs must cancel the whole static wind-and-current wrench (surge, sway, yaw) at the berthing heading.",
                                 plan.ratings_basis or "", f"Margin {req.margin:.0%} applied to the wrench.", *assumptions])


def _feasible(ship, berth, req: BerthingWindowRequest, env: EnvironmentSnapshot, fleet):
    if env.current_speed_kt > req.max_current_kt or (req.max_gust_kt is not None and env.wind_gust_kt > req.max_gust_kt):
        return False, 0.0
    plan, loads, depth = _plan(ship, berth, req.side_to, req.loading, env, req.margin, fleet)
    from mooring.loads import range_findings, mean_draft_ft
    from mooring.loads.validity import classify_findings
    findings, _ = range_findings(depth, mean_draft_ft(ship, req.loading), env.current_speed_kt, [loads.current.coefficients["reynolds"]])
    if any(state == "invalid" for state, _ in classify_findings(findings)):
        return False, 0.0
    return plan.feasible, plan.total_power_hp


def windows(req: BerthingWindowRequest) -> BerthingWindowsResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    refdata.loading(ship, req.loading)
    fleet = _fleet(req.available_tug_ids)
    stations = (berth.env_station_ids.wind, berth.env_station_ids.current, berth.env_station_ids.water_level)
    coverage_end = req.from_utc + timedelta(hours=FORECAST_HORIZON_H)
    last = min(req.to_utc, coverage_end)
    gaps = [] if req.to_utc <= coverage_end else [f"{coverage_end.isoformat()} to {req.to_utc.isoformat()}: no forecast"]

    cache: dict[datetime, tuple[bool, float, EnvironmentSnapshot]] = {}

    def at(t: datetime):
        if t not in cache:
            env = environment.synthetic(t, "forecast", stations)
            ok, hp = _feasible(ship, berth, req, env, fleet)
            cache[t] = (ok, hp, env)
        return cache[t]

    def refine(lo: datetime, hi: datetime) -> datetime:
        """lo and hi differ in feasibility; return the last time at lo's state at 1-minute resolution."""
        state = at(lo)[0]
        while hi - lo > timedelta(minutes=1):
            mid = lo + (hi - lo) / 2
            mid = mid.replace(second=0, microsecond=0)
            if mid <= lo or mid >= hi:
                break
            if at(mid)[0] == state:
                lo = mid
            else:
                hi = mid
        return lo

    step = timedelta(minutes=req.step_min)
    ts = []
    t = req.from_utc
    while t <= last:
        ts.append(t)
        t += step
    windows_out: list[BerthingWindow] = []
    start = None
    for i, t in enumerate(ts):
        ok, hp, env = at(t)
        if ok and start is None:
            start = t if i == 0 else refine(ts[i - 1], t) + timedelta(minutes=1)
        if not ok and start is not None:
            end = refine(ts[i - 1], t)
            windows_out.append((start, end))
            start = None
    if start is not None:
        windows_out.append((start, ts[-1]))
    out = []
    for s, e in windows_out:
        if (e - s).total_seconds() / 60 < req.min_duration_min:
            continue
        samples = [at(x) for x in ts if s <= x <= e] or [at(s)]
        out.append(BerthingWindow(start_utc=s, end_utc=e, max_current_kt=max(x[2].current_speed_kt for x in samples),
                                  max_gust_kt=max(x[2].wind_gust_kt for x in samples), required_power_hp=round(max(x[1] for x in samples))))
    validity = Validity(state="limited", reasons=[
        ValidityReason(code="TUG_RATINGS_NOT_CERTIFIED", affected_components=[t.tug_id for t in fleet], message="Catalog bollard pull is not a certified rating."),
        ValidityReason(code="FORECAST_IS_SYNTHETIC", affected_components=["forecast"], message="The environment service is the deterministic mock until providers are enabled (S04).")])
    return envelope(BerthingWindowsResponse, model="mooring.tugs.windows", request=req, backend="real", model_version="1.0.0",
                    result=BerthingWindowsResult(windows=out, forecast_coverage_end_utc=coverage_end, gaps=gaps,
                                                 resolution_note=f"Sampled every {req.step_min} min; crossings refined to 1 min. A feasible or infeasible interval shorter than {req.step_min} min between samples can be missed."),
                    status=status_with_validity("GREEN" if out else "AMBER", validity), validity=validity,
                    assumptions=["Each sample requires full-wrench tug feasibility (surge, sway, yaw, ratings, one tug per point) with margin, "
                                 "current and gust limits, and valid load-model range.", "Windows are inclusive of start and end minute."])
