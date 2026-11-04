"""Mock environmental loads (M3). Simple drag estimates with the right shape and units, not UFC 4-159-03.

Workstream B replaces this with the UFC 4-159-03 Chapter 4 equations calibrated to NSTM Table 582-3-1.
"""

import math

from mooring import refdata
from mooring.core.schemas import (
    EnvironmentSnapshot,
    ForceComponent,
    ForceSet,
    LoadsRequest,
    LoadsResponse,
    LoadsResult,
    PolarPoint,
    PolarRequest,
    PolarResponse,
    PolarResult,
    ShipClass,
)
from mooring.core.units import KGM3_TO_SLUG_FT3, KT_TO_FPS

from mooring.core.envelopes import envelope

from .helpers import mean_draft_ft, off_pier

WIND_CY = {"hull_dominated": 0.82, "typical": 0.92, "extensive_superstructure": 1.02}  # UFC Table 4-2 classes


def crude_loads(
    ship: ShipClass,
    loading: str,
    heading_true_deg: float,
    env: EnvironmentSnapshot,
    water_depth_ft: float,
    use_gust: bool = True,
    shielding_factor: float = 1.0,
) -> LoadsResult:
    """Wind FROM rel 90 (starboard beam) pushes the ship to port (+y). Current TOWARD rel 90 pushes it to starboard."""
    rho_a = env.air_density_kgm3 * KGM3_TO_SLUG_FT3
    rho_w = env.water_density_kgm3 * KGM3_TO_SLUG_FT3
    vw = (env.wind_gust_kt if use_gust else env.wind_speed_kt) * KT_TO_FPS
    vc = env.current_speed_kt * KT_TO_FPS
    rel_w = (env.wind_from_true_deg - heading_true_deg) % 360
    rel_c = (env.current_set_true_deg - heading_true_deg) % 360
    qa = 0.5 * rho_a * vw**2 * shielding_factor
    qw = 0.5 * rho_w * vc**2
    cy = WIND_CY[ship.wind_drag_class]
    tw, tc = math.radians(rel_w), math.radians(rel_c)

    wind = ForceComponent(
        fx_lbf=-qa * ship.wind_area_frontal_ft2 * 0.8 * math.cos(tw),
        fy_lbf=qa * ship.wind_area_lateral_ft2 * cy * math.sin(tw),
        mz_ftlbf=qa * ship.wind_area_lateral_ft2 * cy * ship.loa_ft * 0.08 * math.sin(2 * tw),
        coefficients={"cy": cy, "cx": 0.8, "cxy": 0.08},
    )
    draft = mean_draft_ft(ship, loading)
    t_over_d = min(draft / water_depth_ft, 0.95)
    cyc = 0.6 + 2.0 * t_over_d**3  # rises sharply as under-keel clearance shrinks (Seelig trend, mock fit)
    area_c = ship.lwl_ft * draft
    current = ForceComponent(
        fx_lbf=qw * area_c * 0.05 * math.cos(tc),
        fy_lbf=-qw * area_c * cyc * math.sin(tc),
        mz_ftlbf=-qw * area_c * cyc * ship.lwl_ft * 0.05 * math.sin(2 * tc),
        coefficients={"cyc": round(cyc, 3), "depth_draft_ratio": round(water_depth_ft / draft, 3)},
    )
    total = ForceSet(
        fx_lbf=wind.fx_lbf + current.fx_lbf,
        fy_lbf=wind.fy_lbf + current.fy_lbf,
        mz_ftlbf=wind.mz_ftlbf + current.mz_ftlbf,
    )
    return LoadsResult(wind=wind, current=current, total=total, wind_rel_ship_deg=rel_w, current_rel_ship_deg=rel_c)




def environmental(req: LoadsRequest) -> LoadsResponse:
    ship = refdata.ship(req.ship_class_id)
    res = crude_loads(ship, req.loading, req.heading_true_deg, req.environment, req.water_depth_ft,
                      req.use_gust, req.shielding_factor)
    if req.side_to:
        res.off_pier_component_lbf = off_pier(res.total.fy_lbf, req.side_to)
    return envelope(LoadsResponse, model="mooring.loads.ufc", request=req, result=res, status="GREEN",
                    assumptions=["Wind uses the gust speed." if req.use_gust else "Wind uses the sustained speed."])


def polar(req: PolarRequest) -> PolarResponse:
    ship = refdata.ship(req.ship_class_id)
    pts = []
    for rel in range(0, 360, req.step_deg):
        env = EnvironmentSnapshot(
            wind_speed_kt=req.wind_speed_kt if req.apply_to != "current" else 0,
            wind_gust_kt=req.wind_speed_kt if req.apply_to != "current" else 0,
            wind_from_true_deg=float(rel),
            current_speed_kt=req.current_speed_kt if req.apply_to != "wind" else 0,
            current_set_true_deg=float((rel + 180) % 360),  # current flowing the same way the wind blows
            water_level_mllw_ft=0,
        )
        r = crude_loads(ship, req.loading, 0.0, env, req.water_depth_ft, use_gust=False)
        pts.append(PolarPoint(rel_deg=rel, fx_lbf=r.total.fx_lbf, fy_lbf=r.total.fy_lbf, mz_ftlbf=r.total.mz_ftlbf))
    return envelope(PolarResponse, model="mooring.loads.ufc", request=req, result=PolarResult(points=pts),
                    status="GREEN", assumptions=["rel_deg is the direction the wind comes from; current runs with it."])
