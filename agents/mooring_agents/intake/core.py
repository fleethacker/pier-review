"""Deterministic intake assessment. Detection and planning behavior retained from the mock."""

import math
from datetime import timedelta

from mooring.core.envelopes import new_id, utcnow
from mooring.core.schemas import EnvironmentSnapshot

from ..physics.toolkit import PhysicsToolkit, calls_for
from .schemas import ConcernWindow, DataQualityIssue, IntakeReport, IntakeRequest, MstAssessment, PlanningCondition

from .thresholds import (
    MST_LIMITS, GUST_AMBER_KT, GUST_RED_KT, WIND_AMBER_KT, WIND_RED_KT,
    CURRENT_AMBER_KT, CURRENT_RED_KT, SHIFT_DEG_PER_HOUR, STALE_S,
    FORECAST_STEP_MIN, MIN_SHIFT_INTERVAL_HOURS, BERTHING_MAX_CURRENT_KT,
)


REPORTS: dict[str, IntakeReport] = {}


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
    tk.plan_id = tk.plan_id or report_id  # ties this report's tool calls together in the ledger
    berth_id, ship_id, side = req.berth_id, req.ship_class_id, req.side_to
    if req.scenario_id:
        sc = await tk.scenario(req.scenario_id)
        berth_id, ship_id, side = berth_id or sc.berth_id, ship_id or sc.ship_class_id, side or sc.side_to
    if not berth_id:
        from ..physics.client import ModelingError

        raise ModelingError(422, "Give scenario_id or berth_id")
    berth = await tk.berth(berth_id)
    current = await tk.env_now(berth_id, req.env_scenario_id)
    if req.env_scenario_id:
        series = [current.model_copy(update={"valid_at_utc": current.valid_at_utc + timedelta(minutes=FORECAST_STEP_MIN * i)})
                  for i in range(req.horizon_hours * (60 // FORECAST_STEP_MIN) + 1)]
    else:
        series = (await tk.forecast(berth_id, req.horizon_hours, FORECAST_STEP_MIN)).series

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
                               f"current {max_cur:.1f} kt over {req.horizon_hours} h fit MST {mst_req}.")

    worst_gust = max(series, key=lambda s: s.wind_gust_kt)
    worst_cur = max(series, key=broadside)
    conditions = [PlanningCondition(label="Worst gust in horizon", environment=worst_gust,
                                    why=f"Gusts peak at {worst_gust.wind_gust_kt:.0f} kt at {worst_gust.valid_at_utc:%H:%MZ}.")]
    if worst_cur.valid_at_utc != worst_gust.valid_at_utc:
        conditions.append(PlanningCondition(label="Strongest current in horizon", environment=worst_cur,
                                            why=f"Current peaks at {worst_cur.current_speed_kt:.1f} kt at "
                                                f"{worst_cur.valid_at_utc:%H:%MZ}."))
    conditions.append(PlanningCondition(label="Now", environment=current, why="Conditions at the time of planning."))

    berthing = []
    if ship_id and side:
        start = utcnow().replace(second=0, microsecond=0)
        bw = await tk.windows({"berth_id": berth_id, "ship_class_id": ship_id, "side_to": side,
                               "from_utc": start.isoformat(), "to_utc": (start + timedelta(hours=req.horizon_hours)).isoformat(),
                               "max_current_kt": BERTHING_MAX_CURRENT_KT, "max_gust_kt": GUST_AMBER_KT})
        berthing = bw.result.windows

    quality = []
    for q in current.quality:
        if q.age_s > STALE_S:
            quality.append(DataQualityIssue(station_id=q.station_id, issue="stale", severity="AMBER",
                                            detail=f"Observation is {q.age_s / 60:.0f} min old."))
        if "mock" in q.flags:
            quality.append(DataQualityIssue(station_id=q.station_id, issue="mock", severity="INFO",
                                            detail="Synthetic data from the mock environment service."))

    reds = [w for w in windows if w.severity == "RED"]
    summary = (f"Next {req.horizon_hours} h at {berth.name}: {len(windows)} window(s) of concern"
               f"{f', {len(reds)} severe' if reds else ''}. Gusts peak {worst_gust.wind_gust_kt:.0f} kt; "
               f"MST {mst_req} conditions{'; exceeds ship MST' if exceeds else ''}."
               f"{f' {len(berthing)} berthing window(s) found.' if berthing else ''}")
    report = IntakeReport(report_id=report_id, created_at_utc=utcnow(), berth_id=berth_id, ship_class_id=ship_id,
                          side_to=side, horizon_hours=req.horizon_hours, current=current, mst=mst, windows=windows,
                          planning_conditions=conditions, berthing_windows=berthing, data_quality=quality,
                          summary=summary, backend="mock",
                          tool_call_ids=[c.call_id for c in calls_for(tk.plan_id) if c.caller == tk.caller])
    REPORTS[report_id] = report
    return report, series


async def assess(req: IntakeRequest, tk: PhysicsToolkit) -> IntakeReport:
    """Compatibility entry point for the unchanged deterministic assessment."""
    report, _ = await assess_with_forecast(req, tk)
    return report
