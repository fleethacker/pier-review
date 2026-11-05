"""S7 trajectory prediction engine.

Runs the EXISTING S6 transit simulator (mooring.transit.simulator.run) forward from an observed state with scripted
helm/tug commands held (or changed for a what-if). No new dynamics model. Geometry (hull footprints, pier face,
clearance, corridor) is computed in the same local tangent plane the simulator uses.

Corridor/probabilities: simple seeded perturbations (documented below), NOT the S10 uncertainty model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, unary_union

from mooring import refdata
from mooring.core.envelopes import envelope, resolved_inputs_hash
from mooring.core.schemas import (
    GeoPoint,
    HazardApproach,
    PredictedTick,
    PredictionAlternative,
    PredictionRequest,
    PredictionResponse,
    PredictionResult,
    ResultManifest,
    TransitHelmCommand,
    TransitRequest,
    TransitStart,
    TransitTugCommand,
    TransitWaypoint,
    Validity,
    ValidityReason,
    VesselTransit,
)
from mooring.transit import simulator as sim
from mooring.transit.geo import LocalPlane

FT = 0.3048
NM = 1852.0
CODE_VERSION = "prediction-v1+" + sim.CODE_VERSION
STALE_S = 300.0
SAMPLE_DT_S = 1.0            # Monte Carlo runs use at least this step to bound runtime
FAR_NM = 20.0
# Illustrative environment spreads (one sigma). Not the S10 model.
WIND_SPEED_FRAC, WIND_DIR_DEG, CURRENT_SPEED_FRAC, CURRENT_DIR_DEG = 0.15, 10.0, 0.20, 15.0


class RequestInvalid(ValueError):
    pass


@dataclass
class Track:
    """Central or sampled path in local metres, one row per tick."""
    t: list[float]
    x: list[float]
    y: list[float]
    heading: list[float]
    sog: list[float]
    cog: list[float | None]
    rudder: list[float]
    order: list[float]


def hull_polygon(x: float, y: float, heading_deg: float, loa_m: float, beam_m: float) -> Polygon:
    """Parametric planform (rectangle stern to 0.3 L, pointed bow) centred on the position, body +y to port."""
    hl, hb, h = loa_m / 2, beam_m / 2, math.radians(heading_deg)
    local = [(-hl, -hb), (0.3 * loa_m, -hb), (hl, 0.0), (0.3 * loa_m, hb), (-hl, hb)]
    s, c = math.sin(h), math.cos(h)
    return Polygon([(x + fx * s - fy * c, y + fx * c + fy * s) for fx, fy in local])


def _transit_request(req: PredictionRequest, helm, tugs, *, dt: float, start_ll, heading, speed_kt, env, plane) -> TransitRequest:
    v = req.vessel
    h = math.radians(heading)
    far = plane.to_geo(*(FAR_NM * NM * math.sin(h) + plane_xy(plane, start_ll)[0], FAR_NM * NM * math.cos(h) + plane_xy(plane, start_ll)[1]))
    commands = [TransitHelmCommand(t_s=0, rudder_deg=v.rudder_deg, engine_order=v.engine_order), *helm]
    tug_cmds = [TransitTugCommand(t_s=0, tug_id=t.tug_id, point=t.point, force_lbf=t.force_lbf,
                                  direction_rel_deg=t.direction_rel_deg) for t in v.tugs] + list(tugs)
    mode = "tug_assisted" if tug_cmds else "own_thrust"
    vt = VesselTransit(vessel_id=v.vessel_id, ship_class_id=v.ship_class_id, loading=v.loading,
                       start=TransitStart(lat=start_ll[0], lon=start_ll[1], heading_true_deg=heading, speed_kt=speed_kt),
                       route=[TransitWaypoint(lat=far[0], lon=far[1], speed_kt=max(speed_kt, 1.0))], mode=mode,
                       propulsion=req.propulsion, helm_commands=commands, tug_commands=tug_cmds)
    return TransitRequest(vessels=[vt], environment=env, start_utc=req.as_of_utc, origin=GeoPoint(lat=plane.lat0, lon=plane.lon0),
                          duration_s=req.horizon_s, dt_s=dt, sample_interval_s=req.tick_s)


def plane_xy(plane, ll):
    return plane.to_local(*ll)


def _track(run: sim.Run, plane: LocalPlane) -> Track:
    t = Track([], [], [], [], [], [], [], [])
    for f in run.frames:
        s = f.vessels[0]
        t.t.append(f.t_s)
        x, y = plane.to_local(s.lat, s.lon)
        t.x.append(x); t.y.append(y)
        t.heading.append(s.heading_true_deg); t.sog.append(s.sog_kt); t.cog.append(s.cog_true_deg)
        t.rudder.append(s.rudder_deg); t.order.append(s.engine_order)
    return t


def _perturbed_env(env, rng):
    if env is None:
        return None
    d = {"wind_speed_kt": max(0.0, env.wind_speed_kt * (1 + WIND_SPEED_FRAC * rng.standard_normal())),
         "wind_from_true_deg": (env.wind_from_true_deg + WIND_DIR_DEG * rng.standard_normal()) % 360,
         "current_speed_kt": max(0.0, env.current_speed_kt * (1 + CURRENT_SPEED_FRAC * rng.standard_normal())),
         "current_set_true_deg": (env.current_set_true_deg + CURRENT_DIR_DEG * rng.standard_normal()) % 360}
    d["wind_gust_kt"] = max(env.wind_gust_kt, d["wind_speed_kt"])
    return env.model_copy(update={**d, "wind_rel_ship_deg": None, "current_rel_ship_deg": None})


@dataclass
class Hazards:
    face: LineString | None
    berth_id: str | None
    fenders: list[tuple[str, LineString]]
    others: list[tuple[str, list[tuple[float, float, float, float]], float, float]]   # id, (t, x, y, hdg) rows, loa, beam


def _build_hazards(req: PredictionRequest, plane: LocalPlane, t0: datetime) -> Hazards:
    face, fenders, bid = None, [], req.hazards.berth_id
    if bid:
        try:
            b = refdata.berth(bid)
        except refdata.NotFound as exc:
            raise RequestInvalid(str(exc)) from None
        ox, oy = plane.to_local(b.origin_lat, b.origin_lon)
        bearing = math.radians(b.face_bearing_true_deg)
        ex, ey = math.sin(bearing), math.cos(bearing)
        nx, ny = math.sin(bearing - math.pi / 2), math.cos(bearing - math.pi / 2)    # off-pier (water) side

        def seg(a_ft, b_ft, off_ft=0.0):
            return LineString([(ox + a_ft * FT * ex + off_ft * FT * nx, oy + a_ft * FT * ey + off_ft * FT * ny),
                               (ox + b_ft * FT * ex + off_ft * FT * nx, oy + b_ft * FT * ey + off_ft * FT * ny)])
        face = seg(0.0, b.face_length_ft)
        fenders = [(f.fender_id, seg(f.x_ft - f.length_ft / 2, f.x_ft + f.length_ft / 2, f.standoff_ft)) for f in b.fenders]
    others = []
    for o in req.others:
        rows = []
        for fix in o.path:
            x, y = plane.to_local(fix.lat, fix.lon)
            rows.append(((fix.t_utc - t0).total_seconds(), x, y, fix.heading_true_deg or 0.0))
        others.append((o.vessel_id, rows, o.length_ft * FT, o.beam_ft * FT))
    return Hazards(face, bid, fenders, others)


def _clearances(track: Track, hz: Hazards, loa: float, beam: float):
    """Per tick: list of (clearance_m, kind, element_id, closest hull point (x, y))."""
    out = []
    for i in range(len(track.t)):
        hull = hull_polygon(track.x[i], track.y[i], track.heading[i], loa, beam)
        cands = []
        if hz.face is not None:
            d = hull.distance(hz.face)
            p = nearest_points(hull, hz.face)[0]
            cands.append((d, "pier", f"{hz.berth_id}:face", p))
            for fid, seg in hz.fenders:
                cands.append((hull.distance(seg), "fender", fid, nearest_points(hull, seg)[0]))
        for oid, rows, ol, ob in hz.others:
            row = min(rows, key=lambda r: abs(r[0] - track.t[i]))
            oh = hull_polygon(row[1], row[2], row[3], ol, ob)
            cands.append((hull.distance(oh), "vessel", oid, nearest_points(hull, oh)[0]))
        out.append(cands)
    return out


def _worst(cands):
    return min(cands, key=lambda c: c[0]) if cands else None


def _approach(plane, t, c, prob):
    lat, lon = plane.to_geo(c[3].x, c[3].y)
    return HazardApproach(t_s=t, kind=c[1], element_id=c[2], clearance_ft=round(c[0] / FT, 1),
                          position=GeoPoint(lat=lat, lon=lon), probability=prob)


def predict(req: PredictionRequest) -> PredictionResponse:
    v = req.vessel
    as_of = req.as_of_utc or datetime.now(UTC)
    plane = LocalPlane(v.position.lat, v.position.lon)
    start_ll = (v.position.lat, v.position.lon)
    try:
        ship = refdata.ship(v.ship_class_id)
    except refdata.NotFound as exc:
        raise RequestInvalid(str(exc)) from None
    loa, beam = ship.loa_ft * FT, ship.beam_ft * FT
    speed0 = max(v.surge_kt, 0.0)
    try:
        hz = _build_hazards(req, plane, as_of)
        sets = [("hold", "Hold current commands", [], [])] + [(a.alt_id, a.label, a.helm_commands, a.tug_commands) for a in req.alternatives]

        def go(helm, tugs, dt, start, heading, speed, env):
            treq = _transit_request(req, helm, tugs, dt=dt, start_ll=start, heading=heading, speed_kt=speed, env=env, plane=plane)
            return treq, sim.run(treq, "predict")
        central = {}
        for aid, _, helm, tugs in sets:
            central[aid] = go(helm, tugs, req.dt_s, start_ll, v.heading_true_deg, speed0, req.environment)
    except (sim.RequestInvalid, refdata.NotFound) as exc:
        raise RequestInvalid(str(exc)) from None

    n_s = req.uncertainty.samples
    samples: dict[str, list[Track]] = {aid: [] for aid, *_ in sets}
    if n_s:
        rng = np.random.default_rng(req.uncertainty.seed)
        u = v.uncertainty
        draws = []
        for _ in range(n_s):
            dx, dy = (rng.standard_normal(2) * (u.position_sd_ft * FT)) if u else (0.0, 0.0)
            dh = rng.standard_normal() * u.heading_sd_deg if u else 0.0
            ds = rng.standard_normal() * u.speed_sd_kt if u else 0.0
            env = _perturbed_env(req.environment, rng)
            draws.append((dx, dy, dh, ds, env))
        dt_s = max(req.dt_s, SAMPLE_DT_S)
        for aid, _, helm, tugs in sets:       # same draws for every alternative (common random numbers)
            for dx, dy, dh, ds, env in draws:
                ll = plane.to_geo(dx, dy)
                _, r = go(helm, tugs, dt_s, ll, (v.heading_true_deg + dh) % 360, max(0.0, speed0 + ds), env)
                samples[aid].append(_track(r, plane))

    alts = []
    for aid, label, _, _ in sets:
        treq, r = central[aid]
        tr = _track(r, plane)
        n = len(tr.t)
        cl = _clearances(tr, hz, loa, beam)
        worst = [(_worst(c), i) for i, c in enumerate(cl) if c]
        closest = first = None
        breach_p = None
        thr = req.hazards.min_clearance_ft * FT
        if worst:
            if n_s:
                scl = [_clearances(s, hz, loa, beam) for s in samples[aid]]
                breach_p = sum(any(c and min(x[0] for x in c) < thr for c in sc) for sc in scl) / n_s
            wi = min(worst, key=lambda w: w[0][0])
            closest = _approach(plane, tr.t[wi[1]], wi[0], breach_p)
            fb = next((w for w in worst if w[0][0] < thr), None)
            if fb:
                first = _approach(plane, tr.t[fb[1]], fb[0], breach_p)
        # corridor and spread
        corridor, sd = None, [None] * n
        if n_s:
            m = min(n, *(len(s.t) for s in samples[aid]))
            mx = [float(np.median([s.x[i] for s in samples[aid]])) for i in range(m)]
            my = [float(np.median([s.y[i] for s in samples[aid]])) for i in range(m)]
            for i in range(m):
                sd[i] = round(math.sqrt(np.var([s.x[i] for s in samples[aid]]) + np.var([s.y[i] for s in samples[aid]])) / FT, 1)
            dist = [max(math.hypot(s.x[i] - mx[i], s.y[i] - my[i]) for i in range(m)) for s in samples[aid]]
            keep = [s for _, s in sorted(zip(dist, samples[aid]), key=lambda z: z[0])[:max(1, math.ceil(req.uncertainty.percentile / 100 * n_s))]]
            polys = [hull_polygon(s.x[i], s.y[i], s.heading[i], loa, beam) for s in [*keep, tr] for i in range(min(m, len(s.t)))]
            u_ = unary_union(polys).buffer(0.5)
            if u_.geom_type != "Polygon":
                u_ = u_.convex_hull
            u_ = u_.simplify(0.6)
            corridor = [GeoPoint(lat=la, lon=lo) for la, lo in (plane.to_geo(px, py) for px, py in list(u_.exterior.coords)[:-1])]
        ticks = []
        for i in range(n):
            lat, lon = plane.to_geo(tr.x[i], tr.y[i])
            fp = hull_polygon(tr.x[i], tr.y[i], tr.heading[i], loa, beam)
            ticks.append(PredictedTick(
                t_s=tr.t[i], t_utc=as_of + timedelta(seconds=tr.t[i]), position=GeoPoint(lat=lat, lon=lon),
                heading_true_deg=tr.heading[i], sog_kt=tr.sog[i], cog_true_deg=tr.cog[i], rudder_deg=tr.rudder[i],
                engine_order=tr.order[i],
                footprint=[GeoPoint(lat=la, lon=lo) for la, lo in (plane.to_geo(px, py) for px, py in list(fp.exterior.coords)[:-1])],
                position_sd_ft=sd[i] if i < len(sd) else None))
        alts.append(PredictionAlternative(alt_id=aid, label=label, ticks=ticks, corridor=corridor,
                                          closest_approach=closest, first_breach=first))

    checked = []
    if hz.face is not None:
        checked.append("pier")
        if hz.fenders:
            checked.append("fender")
    if hz.others:
        checked.append("vessel")
    input_age = max(0.0, (as_of - v.observed_utc).total_seconds())
    env_age = req.environment.metadata.age_s if req.environment and req.environment.metadata else None
    validity = _validity(req, central["hold"], input_age, env_age, n_s, dt_s_used=max(req.dt_s, SAMPLE_DT_S) if n_s else None)
    breach_hold = alts[0].first_breach is not None
    status = "RED" if (validity.state == "invalid" or breach_hold) else "AMBER"
    result = PredictionResult(vessel_id=v.vessel_id, engine="transit", as_of_utc=as_of, input_age_s=round(input_age, 1),
                              hazards_checked=checked, alternatives=alts)
    snapshot = {"request": req.model_dump(mode="json"), "as_of": as_of.isoformat(), "code_version": CODE_VERSION,
                "ship": ship.model_dump(mode="json"), "transit_requests": {k: t.model_dump(mode="json") for k, (t, _) in central.items()}}
    assumptions = ["Path from the S6 transit simulator run forward from the observed state with the current rudder and engine order held.",
                   "Hull footprint is a parametric planform from catalog LOA and beam centred on the reported position, rotated by heading.",
                   "Environment held constant over the horizon." if req.environment else "No environment supplied: calm assumed (labeled, not unknown).",
                   f"Corridor spread (when sampled): start position/heading/speed per the supplied one-sigma values; wind speed {WIND_SPEED_FRAC:.0%}, "
                   f"wind direction {WIND_DIR_DEG:g} deg, current speed {CURRENT_SPEED_FRAC:.0%}, current direction {CURRENT_DIR_DEG:g} deg (illustrative sd)."]
    return envelope(PredictionResponse, model="mooring.prediction.trajectory", model_version="1.0.0", backend="real", request=req,
                    result=result, status=status, validity=validity, assumptions=assumptions,
                    manifest=ResultManifest(resolved_inputs_hash=resolved_inputs_hash(snapshot), code_version=CODE_VERSION,
                                            numerical_settings={"dt_s": req.dt_s, "tick_s": req.tick_s, "sample_dt_s": max(req.dt_s, SAMPLE_DT_S) if n_s else 0.0,
                                                                "samples": n_s, "seed": req.uncertainty.seed}))


def _validity(req, central_hold, input_age, env_age, n_s, dt_s_used) -> Validity:
    treq, r = central_hold
    inherited = sim.validity_for(treq, r)
    reasons = [x for x in inherited.reasons if x.code != "SYNTHETIC_EPOCH"]
    v = req.vessel
    msg = f"Input age {input_age:.0f} s (as_of - observed)" + (f"; environment age {env_age:.0f} s" if env_age is not None else "") + "."
    reasons.append(ValidityReason(code="INPUT_AGE", message=msg))
    if input_age > STALE_S or (env_age is not None and env_age > STALE_S):
        reasons.append(ValidityReason(code="STALE_INPUT", message=f"An input is older than {STALE_S:.0f} s; the ship and conditions may have changed."))
    notes = []
    if v.surge_kt < 0:
        notes.append("negative surge set to 0")
    if v.sway_kt:
        notes.append("sway ignored")
    if v.yaw_rate_degps:
        notes.append("yaw rate ignored")
    if v.rudder_deg:
        notes.append("rudder starts at 0 and slews to the observed angle at the steering-gear rate")
    if v.delivered_thrust_lbf is not None:
        notes.append("delivered thrust ignored (starts near resistance)")
    if notes:
        reasons.append(ValidityReason(code="PREDICTION_START_APPROXIMATED",
                       message="The transit start supports only forward surge from rest actuators: " + "; ".join(notes) + "."))
    if req.hazards.coastline:
        reasons.append(ValidityReason(code="COASTLINE_NOT_CHECKED", message="No coastline data are wired: coastline clearance is not checked, so not clear, just unknown."))
    if n_s:
        reasons.append(ValidityReason(code="UNCERTAINTY_ILLUSTRATIVE", message="Illustrative spread of simple seeded perturbations; the S10 uncertainty model is not yet wired. "
                       "Breach probability is a sample share, not calibrated." + (f" Samples use dt {dt_s_used:g} s." if dt_s_used else "")))
    return Validity(state=inherited.state, reasons=reasons)
