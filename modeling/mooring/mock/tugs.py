"""Mock tug planner (M6): force balance with a margin, greedy tug assignment, berthing windows."""

from datetime import timedelta

from mooring import refdata
from mooring.core.geometry import depth_at, ship_heading_true
from mooring.core.schemas import (
    AnalyzeRequest,
    BerthingTugRequest,
    BerthingWindow,
    BerthingWindowRequest,
    BerthingWindowsResponse,
    BerthingWindowsResult,
    EnvironmentSnapshot,
    HoldTugRequest,
    PushPointForce,
    ShipClass,
    TugAssignment,
    TugPlanResponse,
    TugPlanResult,
)

from . import environment
from ._common import envelope
from .forces import crude_loads, off_pier
from .mooring import solve


def _plan(ship: ShipClass, required: float, onto_pier: bool, side_to: str, heading: float,
          tug_ids: list[str] | None, rationale: list[str]) -> TugPlanResult:
    """Split the required force between forward and aft push points on the side away from the pier."""
    water_side = "port" if side_to == "starboard" else "starboard"
    pps = sorted([p for p in ship.push_points if p.side == water_side], key=lambda p: -p.x_ft)
    mode = "pull" if onto_pier else "push"
    per_point = required / max(len(pps), 1)
    fleet = sorted((refdata.tug(t) for t in tug_ids) if tug_ids else refdata.tugs(),
                   key=lambda t: -t.bollard_pull_ahead_lbf)
    # Push toward the pier = toward the pier-side beam; pull = away from it.
    toward_pier = (heading + (90 if side_to == "starboard" else 270)) % 360
    direction = toward_pier if mode == "push" else (toward_pier + 180) % 360
    assignments, total_bp, total_hp = [], 0.0, 0.0
    by_point = []
    for pp in pps:
        by_point.append(PushPointForce(push_point_id=pp.push_point_id, force_lbf=round(per_point), mode=mode))
        if required <= 0 or not fleet:
            continue

        def pull(t):
            return t.bollard_pull_ahead_lbf if mode == "push" else t.bollard_pull_astern_lbf

        # Smallest tug that covers this push point; otherwise the strongest one left.
        enough = [t for t in fleet if pull(t) >= per_point]
        tug = min(enough, key=pull) if enough else fleet[0]
        fleet.remove(tug)
        bp = pull(tug)
        assignments.append(TugAssignment(tug_id=tug.tug_id, push_point_id=pp.push_point_id, mode=mode,
                                         force_lbf=round(min(bp, per_point)), direction_true_deg=round(direction, 1)))
        total_bp += bp
        total_hp += tug.power_hp
    feasible = total_bp >= required
    if required > 0 and not feasible:
        rationale.append(f"Available tugs give {total_bp:,.0f} lbf; {required:,.0f} lbf needed.")
    return TugPlanResult(required_lateral_lbf=round(required), required_by_point=by_point, assignments=assignments,
                         total_bollard_pull_lbf=round(total_bp), total_power_hp=round(total_hp),
                         recommended_tug_count=len(assignments), feasible=feasible, rationale=rationale)


def berthing_plan(req: BerthingTugRequest) -> TugPlanResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    heading = ship_heading_true(berth, req.side_to)
    depth = depth_at(berth, berth.face_length_ft / 2) + req.environment.water_level_mllw_ft
    loads = crude_loads(ship, req.loading, heading, req.environment, depth, use_gust=True)
    f_off = off_pier(loads.total.fy_lbf, req.side_to)
    required = abs(f_off) * (1 + req.margin)
    rationale = [f"Gust {req.environment.wind_gust_kt:.0f} kt and current {req.environment.current_speed_kt:.1f} kt "
                 f"give {abs(f_off):,.0f} lbf {'off' if f_off > 0 else 'onto'} the pier; "
                 f"{req.margin:.0%} margin added."]
    result = _plan(ship, required, f_off < 0, req.side_to, heading, req.available_tug_ids, rationale)
    return envelope(TugPlanResponse, model="mooring.tugs.berthing", request=req, result=result,
                    status="GREEN" if result.feasible else "RED",
                    assumptions=["No lines fast: tugs carry the whole lateral load.",
                                 "Bollard pull from the fleet catalog; equal split fore and aft (yaw ignored)."])


def hold_plan(req: HoldTugRequest) -> TugPlanResponse:
    s = solve(AnalyzeRequest(**req.model_dump(exclude={"margin", "available_tug_ids"})), run_rules=False)
    over = [r for r in s.result.lines if r.pct_wll > 100]
    deficit = sum(r.tension_lbf * (1 - 100 / r.pct_wll) * r.breast_efficiency for r in over)
    required = deficit * (1 + req.margin)
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    heading = ship_heading_true(berth, req.config.side_to)
    rationale = ([f"Lines {', '.join(str(r.line_number) for r in over)} exceed WLL; tugs relieve about "
                  f"{deficit:,.0f} lbf."] if over else ["All lines within WLL; no holding tugs needed."])
    result = _plan(ship, required, False, req.config.side_to, heading, req.available_tug_ids, rationale)
    return envelope(TugPlanResponse, model="mooring.tugs.hold", request=req, result=result,
                    status="GREEN" if result.feasible else "RED", assumptions=["Deficit from the mock solver."])


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
            f = abs(off_pier(crude_loads(ship, req.loading, heading, env, depth).total.fy_lbf, req.side_to)) * 1.25
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
