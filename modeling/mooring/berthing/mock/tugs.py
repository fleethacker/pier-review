"""Mock berthing tug plan and berthing windows (Phase 1c): tugs carry the whole load before lines are fast."""

from datetime import timedelta

from mooring import refdata
from mooring.core.envelopes import envelope
from mooring.core.geometry import depth_at, ship_heading_true
from mooring.core.schemas import (
    BerthingTugRequest,
    BerthingWindow,
    BerthingWindowRequest,
    BerthingWindowsResponse,
    BerthingWindowsResult,
    EnvironmentSnapshot,
    TugPlanResponse,
)
from mooring.environment import mock as environment
from mooring.loads import compute_loads, off_pier
from mooring.tugs import size_tugs


def berthing_plan(req: BerthingTugRequest) -> TugPlanResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    heading = ship_heading_true(berth, req.side_to)
    depth = depth_at(berth, berth.face_length_ft / 2) + req.environment.water_level_mllw_ft
    loads = compute_loads(ship, req.loading, heading, req.environment, depth, use_gust=True)
    f_off = off_pier(loads.total.fy_lbf, req.side_to)
    required = abs(f_off) * (1 + req.margin)
    rationale = [f"Gust {req.environment.wind_gust_kt:.0f} kt and current {req.environment.current_speed_kt:.1f} kt "
                 f"give {abs(f_off):,.0f} lbf {'off' if f_off > 0 else 'onto'} the pier; "
                 f"{req.margin:.0%} margin added."]
    result = size_tugs(ship, required, f_off < 0, req.side_to, heading, req.available_tug_ids, rationale)
    return envelope(TugPlanResponse, model="mooring.tugs.berthing", request=req, result=result,
                    status="GREEN" if result.feasible else "RED",
                    assumptions=["No lines fast: tugs carry the whole lateral load.",
                                 "Bollard pull from the fleet catalog; equal split fore and aft (yaw ignored)."])


def windows(req: BerthingWindowRequest) -> BerthingWindowsResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    heading = ship_heading_true(berth, req.side_to)
    stations = (berth.env_station_ids.wind, berth.env_station_ids.current, berth.env_station_ids.water_level)
    out, cur = [], None
    t = req.from_utc
    while t <= req.to_utc:
        env: EnvironmentSnapshot = environment.synthetic(t, "forecast", stations)
        ok = env.current_speed_kt <= req.max_current_kt and (req.max_gust_kt is None or env.wind_gust_kt <= req.max_gust_kt)
        if ok:
            depth = depth_at(berth, berth.face_length_ft / 2) + env.water_level_mllw_ft
            f = abs(off_pier(compute_loads(ship, req.loading, heading, env, depth).total.fy_lbf, req.side_to)) * 1.25
            hp = f / 2000 / 1.25 * 100  # ~1.25 short tons bollard pull per 100 hp (ASD)
            if cur is None:
                cur = dict(start_utc=t, end_utc=t, max_current_kt=env.current_speed_kt, max_gust_kt=env.wind_gust_kt,
                           required_power_hp=hp)
            else:
                cur.update(end_utc=t, max_current_kt=max(cur["max_current_kt"], env.current_speed_kt),
                           max_gust_kt=max(cur["max_gust_kt"], env.wind_gust_kt),
                           required_power_hp=max(cur["required_power_hp"], hp))
        elif cur is not None:
            out.append(BerthingWindow(**{**cur, "required_power_hp": round(cur["required_power_hp"])}))
            cur = None
        t += timedelta(minutes=6)
    if cur is not None:
        out.append(BerthingWindow(**{**cur, "required_power_hp": round(cur["required_power_hp"])}))
    return envelope(BerthingWindowsResponse, model="mooring.tugs.windows", request=req,
                    result=BerthingWindowsResult(windows=out), status="GREEN" if out else "AMBER",
                    assumptions=["Mock tide and wind forecast; 1.25 short tons per 100 hp."])
