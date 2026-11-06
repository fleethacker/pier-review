"""Deterministic intake assessment. Detection and planning behavior retained from the mock."""

import math
from datetime import UTC, timedelta

from mooring.core import access
from mooring.core.envelopes import new_id, utcnow
from mooring.core.schemas import EnvironmentSnapshot
from mooring.core.forecast_provenance import availability_problem

from ..physics.toolkit import PhysicsToolkit, calls_for
from ..physics.client import ModelingError
from ..shared.environment_quality import component_issues
from ..shared.forecast import bound_samples, resolve_forecast
from .schemas import ConcernWindow, DataQualityIssue, IntakeReport, IntakeRequest, MstAssessment, PlanningCondition

from .thresholds import (
    MST_LIMITS, GUST_AMBER_KT, GUST_RED_KT, WIND_AMBER_KT, WIND_RED_KT,
    CURRENT_AMBER_KT, CURRENT_RED_KT, SHIFT_DEG_PER_HOUR, STALE_S,
    FORECAST_STEP_MIN, MIN_SHIFT_INTERVAL_HOURS, BERTHING_MAX_CURRENT_KT,
)


from ..shared.storage import AgentStore

REPORTS = AgentStore("agent_report", IntakeReport)


def _windows(series: list[EnvironmentSnapshot], kind: str, value, amber: float, red: float, reason: str):
    out, run = [], []
    for s in series + [None]:
        v = value(s) if s is not None else None
        if v is not None and v >= amber:
            run.append((s, v))
            continue
        if run:
            peak = max(v_ for _, v_ in run)
            out.append(ConcernWindow(start_utc=run[0][0].valid_at_utc, end_utc=run[-1][0].valid_at_utc, kind=kind,
                                     severity="RED" if peak >= red else "AMBER", peak_value=round(peak, 1), unit="kt",
                                     reason=reason.format(peak=peak)))
            run = []
    return out


def _mst(max_wind: float, max_cur: float) -> str:
    for mst in ("I", "II", "III"):
        if any(max_wind <= w and max_cur <= c for w, c in MST_LIMITS[mst]):
            return mst
    return "exceeds_III"


async def assess_with_forecast(req: IntakeRequest, tk: PhysicsToolkit) -> tuple[IntakeReport, list[EnvironmentSnapshot]]:
    report_id = new_id("intake")
    access.claim("agent_report", report_id)
    tk.plan_id = tk.plan_id or report_id  # ties this report's tool calls together in the ledger
    berth_id, ship_id, side = req.berth_id, req.ship_class_id, req.side_to
    if berth_id is None and req.forecast_request is not None:
        berth_id = req.forecast_request.berth_id
    env_scenario_id = req.env_scenario_id
    quality = []
    forecast_complete = True
    saved_source = None
    if req.scenario_id:
        sc = await tk.scenario(req.scenario_id)
        berth_id, ship_id, side = berth_id or sc.berth_id, ship_id or sc.ship_class_id, side or sc.side_to
        source = getattr(sc, "env_source", None)
        if req.env_scenario_id is None and source is not None:
            if berth_id != sc.berth_id:
                raise ModelingError(422, "Scenario and requested berth do not match")
            saved_source = sc
        if env_scenario_id is None and source is not None and source.mode == "scenario":
            env_scenario_id = source.env_scenario_id
    if not berth_id:
        raise ModelingError(422, "Give scenario_id or berth_id")
    berth = await tk.berth(berth_id)
    resolution = None
    if req.forecast_request is not None:
        if req.forecast_request.berth_id != berth_id:
            raise ModelingError(422, "Forecast and scenario berth do not match")
        resolution = await resolve_forecast(tk, req.forecast_request)
    saved_mock = saved_source is not None and saved_source.env_source.mode == "mock"
    current = (bound_samples(resolution)[0] if resolution is not None else
               await tk.scenario_environment(req.scenario_id) if saved_source is not None
               else await tk.env_now(berth_id, env_scenario_id))
    assessed_cutoff = resolution.result.forecast_manifest.as_of_utc if resolution is not None else utcnow()
    if problem := availability_problem(current, assessed_cutoff):
        raise ModelingError(422, "Current environment is unavailable for assessment: " + problem)
    current = current.model_copy(update={"valid_at_utc": current.valid_at_utc.astimezone(UTC)})
    if resolution is not None:
        series = bound_samples(resolution)
    elif env_scenario_id:
        scenario = await tk.environment_scenario(env_scenario_id)
        if scenario.kind == "steady":
            # The declared source is constant by definition. Never freeze ramps or replay series.
            series = [current.model_copy(update={"valid_at_utc": current.valid_at_utc + timedelta(minutes=FORECAST_STEP_MIN * i)})
                      for i in range(int(req.horizon_hours) * (60 // FORECAST_STEP_MIN) + 1)]
        else:
            forecast_complete = False
            series = [current]
            quality.append(DataQualityIssue(station_id="forecast", issue="missing", severity="RED",
                detail=f"The {scenario.kind} scenario has no forecast-series interface; only the current snapshot was assessed. Future conditions were not held constant."))
    else:
        try:
            series = (await tk.forecast(berth_id, int(req.horizon_hours), FORECAST_STEP_MIN)).series
        except ModelingError as exc:
            if exc.status not in (429, 502, 503, 504):
                raise
            series = []
        if saved_mock and any(
                sample.source not in ("mock", "scenario")
                and not (sample.metadata and sample.metadata.basis == "scenario")
                and not any("mock" in item.flags for item in sample.quality) for sample in series):
            series = []
            quality.append(DataQualityIssue(station_id="forecast", issue="missing", severity="RED",
                detail="Configured forecast does not match the selected synthetic source; it was not substituted."))
        if not series:
            forecast_complete = False
            series = [current]
            quality.append(DataQualityIssue(station_id="forecast", issue="missing", severity="RED",
                detail="Forecast unavailable; assessment covers the current snapshot only, not the requested horizon."))

    # Compare elapsed UTC time, including repeated/skipped local hours; preserve caller objects.
    series = [sample.model_copy(update={"valid_at_utc": sample.valid_at_utc.astimezone(UTC)})
              if sample.valid_at_utc.tzinfo is not None and sample.valid_at_utc.utcoffset() is not None
              else sample for sample in series]
    # Assess only ordered, timezone-aware samples; do not silently sort a malformed feed.
    times = [sample.valid_at_utc for sample in series]
    if any(t.tzinfo is None or t.utcoffset() is None for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        forecast_complete = False
        series = [current]
        quality.append(DataQualityIssue(station_id="forecast", issue="missing", severity="RED",
            detail="Forecast timestamps are unordered, duplicated or lack a timezone; only the current snapshot was assessed."))
    elif forecast_complete and resolution is None:
        tolerance = timedelta(minutes=FORECAST_STEP_MIN * 2)
        start = current.valid_at_utc
        if (start.tzinfo is None or times[0] > start or
                times[-1] < start + timedelta(hours=req.horizon_hours) or
                any(b-a > tolerance for a, b in zip(times, times[1:]))):
            forecast_complete = False
            quality.append(DataQualityIssue(station_id="forecast", issue="missing", severity="RED",
                detail="Forecast samples do not cover the entire requested horizon without gaps; only available samples were assessed."))

    # Never let unavailable future guidance drive deterministic findings or optional LLM selection.
    assessed_at = assessed_cutoff if resolution is not None else utcnow()
    available = []
    unavailable = set()
    for sample in series:
        problem = availability_problem(sample, assessed_at)
        if problem:
            unavailable.add(problem)
        else:
            available.append(sample)
    if unavailable:
        forecast_complete = False
        quality.extend(DataQualityIssue(station_id="forecast", issue="missing", severity="RED",
            detail="Forecast samples excluded from assessment: " + problem) for problem in sorted(unavailable))
        series = available or [current]

    # Quality can be carried by forecast metadata, not just current station observations.
    flagged = set()
    for sample in [current, *series]:
        flagged.update(component_issues(sample))
        metadata = sample.metadata
        if metadata and ((metadata.valid_from_utc and sample.valid_at_utc < metadata.valid_from_utc)
                         or (metadata.valid_to_utc and sample.valid_at_utc > metadata.valid_to_utc)):
            flagged.add((metadata.source or "environment", "out_of_range", "RED",
                         "A supplied environment sample is outside its declared validity interval."))
        if metadata and metadata.quality in ("suspect", "poor"):
            flagged.add((metadata.source or "environment", "flagged", "RED" if metadata.quality == "poor" else "AMBER",
                         f"Provider marks environment quality {metadata.quality}; verify before use."))
        if metadata and metadata.age_s is not None and metadata.age_s > STALE_S:
            flagged.add((metadata.source or "environment", "stale", "AMBER", "Environment metadata reports stale observations."))
        for station in sample.quality:
            flags = " ".join(station.flags).lower()
            if any(word in flags for word in ("missing", "unavailable", "gap")):
                flagged.add((station.station_id, "missing", "RED", "A required source reports missing or unavailable data: " + ", ".join(station.flags)))
            elif any(word in flags for word in ("suspect", "poor", "invalid", "stale")):
                flagged.add((station.station_id, "flagged", "AMBER", "Provider quality flags require review: " + ", ".join(station.flags)))
    quality.extend(DataQualityIssue(station_id=station, issue=issue, severity=severity, detail=detail)
                   for station, issue, severity, detail in sorted(flagged))

    if any(q.issue == "missing" and q.severity == "RED" for q in quality):
        forecast_complete = False

    heading = None
    if side:
        heading = berth.face_bearing_true_deg if side == "starboard" else (berth.face_bearing_true_deg + 180) % 360

    def broadside(s: EnvironmentSnapshot) -> float:
        if heading is None:
            return s.current_speed_kt
        return s.current_speed_kt * abs(math.sin(math.radians(s.current_set_true_deg - heading)))

    windows = []
    windows += _windows(series, "gust", lambda s: s.wind_gust_kt, GUST_AMBER_KT, GUST_RED_KT,
                        "Gusts to {peak:.0f} kt")
    windows += _windows(series, "sustained_wind", lambda s: s.wind_speed_kt, WIND_AMBER_KT, WIND_RED_KT,
                        "Sustained wind {peak:.0f} kt, above MST I")
    windows += _windows(series, "current", broadside, CURRENT_AMBER_KT, CURRENT_RED_KT,
                        "Broadside current {peak:.1f} kt" if heading is not None else "Current {peak:.1f} kt")
    for a, b in zip(series, series[1:]):
        hours = max((b.valid_at_utc - a.valid_at_utc).total_seconds() / 3600, MIN_SHIFT_INTERVAL_HOURS)
        shift = abs((b.wind_from_true_deg - a.wind_from_true_deg + 180) % 360 - 180)
        if shift / hours >= SHIFT_DEG_PER_HOUR:
            windows.append(ConcernWindow(start_utc=a.valid_at_utc, end_utc=b.valid_at_utc, kind="wind_shift",
                                         severity="AMBER", peak_value=round(shift, 0), unit="deg",
                                         reason=f"Wind shifts {shift:.0f} deg; lines may load on the other side"))
    windows.sort(key=lambda w: w.start_utc)

    max_wind = max(s.wind_speed_kt for s in series)
    max_cur = max(broadside(s) for s in series)
    mst_req = _mst(max_wind, max_cur)
    ship = await tk.ship(ship_id) if ship_id else None
    # The ship's own design limits (MST II, or IIA for CVN 68 / LHA 1 / LHD 1/5) decide whether it can stay.
    exceeds = bool(ship) and not any(max_wind <= w and max_cur <= c for w, c in MST_LIMITS[ship.mst_class])
    mst = MstAssessment(mst_required=mst_req, ship_mst=ship.mst_class if ship else None, exceeds_ship_mst=exceeds,
                        max_wind_kt=round(max_wind, 1), max_broadside_current_kt=round(max_cur, 2) if heading is not None else None,
                        reason=f"Max sustained {max_wind:.0f} kt and {'broadside ' if heading is not None else ''}"
                               f"current {max_cur:.1f} kt over {req.horizon_hours:g} h fit MST {mst_req}.")

    worst_gust = max(series, key=lambda s: s.wind_gust_kt)
    worst_cur = max(series, key=broadside)
    conditions = [PlanningCondition(label="Worst gust in horizon" if forecast_complete else "Worst gust among available samples", environment=worst_gust,
                                    why=f"Gusts peak at {worst_gust.wind_gust_kt:.0f} kt at {worst_gust.valid_at_utc:%H:%MZ}.")]
    if worst_cur.valid_at_utc != worst_gust.valid_at_utc:
        conditions.append(PlanningCondition(label="Strongest current in horizon" if forecast_complete else "Strongest current among available samples", environment=worst_cur,
                                            why=f"Current peaks at {worst_cur.current_speed_kt:.1f} kt at "
                                                f"{worst_cur.valid_at_utc:%H:%MZ}."))
    conditions.append(PlanningCondition(label="Forecast interval start" if resolution is not None else "Now", environment=current,
        why="Actual supplied sample covering the bound interval start." if resolution is not None else "Conditions at the time of planning."))

    berthing = []
    if ship_id and side and not env_scenario_id and not saved_mock and resolution is None:
        start = utcnow().replace(second=0, microsecond=0)
        try:
            bw = await tk.windows({"berth_id": berth_id, "ship_class_id": ship_id, "side_to": side,
                                   "from_utc": start.isoformat(), "to_utc": (start + timedelta(hours=req.horizon_hours)).isoformat(),
                                   "max_current_kt": BERTHING_MAX_CURRENT_KT, "max_gust_kt": GUST_AMBER_KT})
            berthing = bw.result.windows
        except ModelingError as exc:
            if exc.status not in (429, 502, 503, 504):
                raise
            quality.append(DataQualityIssue(station_id="berthing_windows", issue="missing", severity="AMBER",
                detail="Berthing-window service unavailable; no arrival window has been verified."))

    for q in current.quality:
        if q.age_s > STALE_S:
            quality.append(DataQualityIssue(station_id=q.station_id, issue="stale", severity="AMBER",
                                            detail=f"Observation is {q.age_s / 60:.0f} min old."))
        if "mock" in q.flags:
            quality.append(DataQualityIssue(station_id=q.station_id, issue="mock", severity="INFO",
                                            detail="Synthetic data from the mock environment service."))

    if not forecast_complete:
        mst.reason = "Forecast coverage incomplete. " + mst.reason.replace(f"over {req.horizon_hours:g} h",
            "at the current snapshot only" if len(series) == 1 else "over available samples only")
    reds = [w for w in windows if w.severity == "RED"]
    summary = (f"Next {req.horizon_hours:g} h at {berth.name}: {len(windows)} window(s) of concern"
               f"{f', {len(reds)} severe' if reds else ''}. Gusts peak {worst_gust.wind_gust_kt:.0f} kt; "
               f"MST {mst_req} conditions{'; exceeds ship MST' if exceeds else ''}."
               f"{f' {len(berthing)} berthing window(s) found.' if berthing else ''}")
    if resolution is not None:
        manifest = resolution.result.forecast_manifest
        summary = summary.replace(f"Next {req.horizon_hours:g} h", f"Bound forecast {manifest.from_utc.isoformat()} to {manifest.to_utc.isoformat()}", 1)
    if not forecast_complete:
        summary = "Forecast coverage incomplete; available samples only. " + summary
    report = IntakeReport(report_id=report_id, created_at_utc=assessed_at, berth_id=berth_id, ship_class_id=ship_id,
                          forecast_manifest=resolution.result.forecast_manifest if resolution is not None else None,
                          forecast_result_id=resolution.result_id if resolution is not None else None,
                          forecast_request=req.forecast_request.model_copy(deep=True) if req.forecast_request is not None else None,
                          side_to=side, horizon_hours=req.horizon_hours, current=current, mst=mst, windows=windows,
                          planning_conditions=conditions, berthing_windows=berthing, data_quality=quality,
                          summary=summary, summary_source="deterministic", narration_note=None, backend="mock",
                          tool_call_ids=[c.call_id for c in calls_for(tk.plan_id) if c.caller == tk.caller])
    REPORTS[report_id] = report
    return report, series


async def assess(req: IntakeRequest, tk: PhysicsToolkit) -> IntakeReport:
    """Compatibility entry point for the unchanged deterministic assessment."""
    report, _ = await assess_with_forecast(req, tk)
    return report
