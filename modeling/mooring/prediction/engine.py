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
from mooring.core.forcing import ForcingSeries
from mooring.core.envelopes import envelope, resolved_inputs_hash
from mooring.core.schemas import (
    ForcingBasis,
    ForcingCoverage,
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
from mooring.prediction import forced
from mooring.transit import simulator as sim
from mooring.transit.geo import LocalPlane

FT = 0.3048
NM = 1852.0
CODE_VERSION = "prediction-v1+" + sim.CODE_VERSION
STALE_S = 300.0
SAMPLE_DT_S = 1.0            # Monte Carlo runs use at least this step to bound runtime
FAR_NM = 20.0
# Illustrative environment spreads (one sigma). Not the S10 model.
CHECK_S = 2.0                # central-path hazard checks are made at most this far apart and swept in between
SAMPLE_CHECK_S = 5.0         # same for the Monte Carlo samples (bounds runtime)
MAX_STATE_KT = 60.0
WIND_SPEED_FRAC, WIND_DIR_DEG, CURRENT_SPEED_FRAC, CURRENT_DIR_DEG = 0.15, 10.0, 0.20, 15.0


ForcingValueError = ValueError


class RequestInvalid(ValueError):
    pass


class Unsupported(RequestInvalid):
    """A requested capability is not implemented (HTTP 501). Never answered by silently using another engine."""


def _resolve_forcing(req: PredictionRequest):
    """(series, ForcingBasis, req). req is the private copy; its horizon is truncated when the series ends early and its
    policy is 'invalidate'. Uncovered horizon with policy 'stop' is rejected. No extrapolation either way."""
    if req.forcing is None:
        return None, ForcingBasis(), req
    spec = req.forcing
    base = req.environment if req.environment is not None else sim.CALM_ENV
    horizon = requested = req.horizon_s
    series = ForcingSeries(spec, base, horizon)
    if series.start > 1e-9:
        raise RequestInvalid(f"FORCING_UNCOVERED: forcing series {series.revision} starts at t={series.start:g} s but the prediction "
                             "starts at t=0 (as_of_utc); the series must cover the snapshot time")
    if series.end + 1e-9 < horizon:
        if spec.on_uncovered == "stop":
            raise RequestInvalid(f"FORCING_UNCOVERED: forcing series {series.revision} covers t={series.start:g}..{series.end:g} s but the "
                                 f"horizon is {horizon:g} s (on_uncovered='stop'); shorten the horizon or set on_uncovered='invalidate' to truncate")
        horizon = math.floor(series.end / req.tick_s + 1e-9) * req.tick_s
        if horizon < req.tick_s:
            raise RequestInvalid(f"FORCING_UNCOVERED: forcing series {series.revision} covers less than one output tick ({series.end:g} s)")
        req = req.model_copy(update={"horizon_s": horizon})
        series = ForcingSeries(spec, base, horizon)
    basis = ForcingBasis(kind="time_varying", revision=series.revision, synthetic=series.synthetic, series_kind=spec.kind,
                         coverage=ForcingCoverage(start_s=series.start, end_s=series.end), requested_horizon_s=requested,
                         horizon_s=req.horizon_s, truncated=req.horizon_s < requested - 1e-9)
    return series, basis, req


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


def _transit_request(req: PredictionRequest, helm, tugs, *, dt: float, start_ll, heading, speed_kt, env, plane,
                     sample_s: float | None = None) -> TransitRequest:
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
                          duration_s=req.horizon_s, dt_s=dt, sample_interval_s=sample_s or req.tick_s)


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


def _perturb_fn(rng):
    a, b, c, d = (float(x) for x in rng.standard_normal(4))      # same draw order as _perturbed_env

    def apply(env):
        ws = max(0.0, env.wind_speed_kt * (1 + WIND_SPEED_FRAC * a))
        return env.model_copy(update={"wind_speed_kt": ws, "wind_from_true_deg": (env.wind_from_true_deg + WIND_DIR_DEG * b) % 360,
                                      "current_speed_kt": max(0.0, env.current_speed_kt * (1 + CURRENT_SPEED_FRAC * c)),
                                      "current_set_true_deg": (env.current_set_true_deg + CURRENT_DIR_DEG * d) % 360,
                                      "wind_gust_kt": max(env.wind_gust_kt, ws), "wind_rel_ship_deg": None, "current_rel_ship_deg": None})
    return apply


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
        rows.sort(key=lambda r: r[0])
        others.append((o.vessel_id, rows, o.length_ft * FT, o.beam_ft * FT))
    return Hazards(face, bid, fenders, others)


def _split(tick_s: float, target_s: float) -> tuple[int, float]:
    """(k, check_s): k check intervals per output tick, check_s = tick_s / k <= target_s."""
    k = max(1, math.ceil(tick_s / target_s - 1e-9))
    return k, tick_s / k


def _sub(tr: Track, k: int) -> Track:
    return Track(tr.t[::k], tr.x[::k], tr.y[::k], tr.heading[::k], tr.sog[::k], tr.cog[::k], tr.rudder[::k], tr.order[::k])


def _other_hull(rows, t, ol, ob) -> Polygon:
    """Hull of another vessel at time t: linear interpolation along its supplied path, held at the first/last fix outside it."""
    if t <= rows[0][0]:
        r = rows[0]
        return hull_polygon(r[1], r[2], r[3], ol, ob)
    if t >= rows[-1][0]:
        r = rows[-1]
        return hull_polygon(r[1], r[2], r[3], ol, ob)
    for r0, r1 in zip(rows, rows[1:]):
        if r0[0] <= t <= r1[0]:
            f = 0.0 if r1[0] == r0[0] else (t - r0[0]) / (r1[0] - r0[0])
            dh = ((r1[3] - r0[3] + 180.0) % 360.0) - 180.0
            return hull_polygon(r0[1] + f * (r1[1] - r0[1]), r0[2] + f * (r1[2] - r0[2]), (r0[3] + f * dh) % 360.0, ol, ob)
    r = rows[-1]
    return hull_polygon(r[1], r[2], r[3], ol, ob)


def _iter_clearances(track: Track, hz: Hazards, loa: float, beam: float):
    """Per check time: list of (clearance_m, kind, element_id, closest hull point). Each entry after the first uses the
    SWEPT hull (convex hull of the footprints at the previous and this check time), so a hazard falling between two
    samples is still seen; entry 0 is the initial footprint, so an overlap that exists at the start is reported at t=0.
    Other vessels are swept over the same interval (conservative: both swept hulls are compared over the whole interval)."""
    prev = None
    for i in range(len(track.t)):
        hull = hull_polygon(track.x[i], track.y[i], track.heading[i], loa, beam)
        swept = hull if prev is None else unary_union([prev, hull]).convex_hull
        prev = hull
        cands = []
        if hz.face is not None:
            cands.append((swept.distance(hz.face), "pier", f"{hz.berth_id}:face", nearest_points(swept, hz.face)[0]))
            for fid, seg in hz.fenders:
                cands.append((swept.distance(seg), "fender", fid, nearest_points(swept, seg)[0]))
        for oid, rows, ol, ob in hz.others:
            t1 = track.t[i]
            t0 = track.t[i - 1] if i else t1
            hs = [_other_hull(rows, t0, ol, ob), *(hull_polygon(r[1], r[2], r[3], ol, ob) for r in rows if t0 < r[0] < t1),
                  _other_hull(rows, t1, ol, ob)]
            oh = unary_union(hs).convex_hull if len(hs) > 1 else hs[0]
            cands.append((swept.distance(oh), "vessel", oid, nearest_points(swept, oh)[0]))
        yield cands


def _clearances(track: Track, hz: Hazards, loa: float, beam: float):
    return list(_iter_clearances(track, hz, loa, beam))


def _worst(cands):
    return min(cands, key=lambda c: c[0]) if cands else None


def _approach(plane, t, c, prob):
    lat, lon = plane.to_geo(c[3].x, c[3].y)
    return HazardApproach(t_s=t, kind=c[1], element_id=c[2], clearance_ft=round(c[0] / FT, 1),
                          position=GeoPoint(lat=lat, lon=lon), probability=prob)


def _check_finite(req: PredictionRequest) -> None:
    v = req.vessel
    for name, x in (("surge_kt", v.surge_kt), ("sway_kt", v.sway_kt), ("yaw_rate_degps", v.yaw_rate_degps),
                    ("delivered_thrust_lbf", v.delivered_thrust_lbf if v.delivered_thrust_lbf is not None else 0.0)):
        if not math.isfinite(x):
            raise RequestInvalid(f"vessel.{name} must be a finite number")
    if abs(v.surge_kt) > MAX_STATE_KT or abs(v.sway_kt) > MAX_STATE_KT:
        raise RequestInvalid(f"vessel speeds beyond {MAX_STATE_KT:g} kt are not plausible for these ships")


def predict(req: PredictionRequest) -> PredictionResponse:
    # The prediction works on a private deep copy: nothing in the caller's request (which may be built from a live
    # session or replay state) is ever mutated, and nothing here writes to any store.
    req = req.model_copy(deep=True)
    if req.engine not in (None, "transit"):
        raise Unsupported("ENGINE_UNSUPPORTED: only the 'transit' (S6) engine is supported for prediction. The berthing engine (S1-S3) "
                          "has no validated handoff (frame, unit, state and parameter mapping, operating domain); the engine is never "
                          "switched automatically, including near a pier.")
    _check_finite(req)
    try:
        series, basis, req = _resolve_forcing(req)
    except ForcingValueError as exc:
        raise RequestInvalid(str(exc)) from None
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

        k_c, check_c = _split(req.tick_s, CHECK_S)
        k_s, check_s = _split(req.tick_s, SAMPLE_CHECK_S)

        def go(helm, tugs, dt, start, heading, speed, env, sample, xform=None):
            treq = _transit_request(req, helm, tugs, dt=dt, start_ll=start, heading=heading, speed_kt=speed, env=env, plane=plane,
                                    sample_s=sample)
            if series is not None:       # S7b: same integrator, environment re-sampled from the S2 series each step
                return treq, forced.run(treq, series, xform)
            return treq, sim.run(treq, "predict")
        central = {}
        for aid, _, helm, tugs in sets:
            central[aid] = go(helm, tugs, req.dt_s, start_ll, v.heading_true_deg, speed0, req.environment, check_c)
    except (sim.RequestInvalid, refdata.NotFound) as exc:
        raise RequestInvalid(str(exc)) from None

    n_req = req.uncertainty.samples
    u = v.uncertainty
    env0 = req.environment
    spread = bool((u and (u.position_sd_ft or u.heading_sd_deg or u.speed_sd_kt))
                  or (env0 and (env0.wind_speed_kt > 0 or env0.current_speed_kt > 0)) or series is not None)
    # With no spread source (or a single sample) every sample would equal the central path: report the uncertainty as
    # unavailable (null corridor, spread and probability) instead of a corridor of zero width.
    n_s = n_req if (n_req >= 2 and spread) else 0
    samples: dict[str, list[Track]] = {aid: [] for aid, *_ in sets}
    if n_s:
        rng = np.random.default_rng(req.uncertainty.seed)
        u = v.uncertainty
        draws = []
        for _ in range(n_s):
            dx, dy = (rng.standard_normal(2) * (u.position_sd_ft * FT)) if u else (0.0, 0.0)
            dh = rng.standard_normal() * u.heading_sd_deg if u else 0.0
            ds = rng.standard_normal() * u.speed_sd_kt if u else 0.0
            if series is not None:
                env = _perturb_fn(rng)        # same four draws, applied to the series value at every step
            else:
                env = _perturbed_env(req.environment, rng)
            draws.append((dx, dy, dh, ds, env))
        dt_s = max(req.dt_s, SAMPLE_DT_S)
        for aid, _, helm, tugs in sets:       # same draws for every alternative (common random numbers)
            for dx, dy, dh, ds, env in draws:
                ll = plane.to_geo(dx, dy)
                _, r = go(helm, tugs, dt_s, ll, (v.heading_true_deg + dh) % 360, max(0.0, speed0 + ds),
                          req.environment if series is not None else env, check_s, env if series is not None else None)
                samples[aid].append(_track(r, plane))

    alts = []
    for aid, label, _, _ in sets:
        treq, r = central[aid]
        tr_fine = _track(r, plane)
        tr = _sub(tr_fine, k_c)
        n = len(tr.t)
        cl = _clearances(tr_fine, hz, loa, beam)
        worst = [(_worst(c), i) for i, c in enumerate(cl) if c]
        closest = first = None
        breach_p = None
        thr = req.hazards.min_clearance_ft * FT
        if worst:
            if n_s:
                breach_p = sum(any(c and min(x[0] for x in c) < thr for c in _iter_clearances(s, hz, loa, beam))
                               for s in samples[aid]) / n_s
            wi = min(worst, key=lambda w: w[0][0])
            closest = _approach(plane, tr_fine.t[wi[1]], wi[0], breach_p)
            fb = next((w for w in worst if w[0][0] < thr), None)
            if fb:
                first = _approach(plane, tr_fine.t[fb[1]], fb[0], breach_p)
        # corridor and spread
        corridor, sd = None, [None] * n
        if n_s:
            ss = [_sub(s, k_s) for s in samples[aid]]
            m = min(n, *(len(s.t) for s in ss))
            mx = [float(np.median([s.x[i] for s in ss])) for i in range(m)]
            my = [float(np.median([s.y[i] for s in ss])) for i in range(m)]
            for i in range(m):
                sd[i] = round(math.sqrt(np.var([s.x[i] for s in ss]) + np.var([s.y[i] for s in ss])) / FT, 1)
            dist = [max(math.hypot(s.x[i] - mx[i], s.y[i] - my[i]) for i in range(m)) for s in ss]
            keep = [s for _, s in sorted(zip(dist, ss), key=lambda z: z[0])[:max(1, math.ceil(req.uncertainty.percentile / 100 * n_s))]]
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
    validity = _validity(req, central["hold"], input_age, env_age, n_s, dt_s_used=max(req.dt_s, SAMPLE_DT_S) if n_s else None,
                         checked=checked, n_req=n_req, hz=hz, horizon_s=req.horizon_s, basis=basis)
    breach_hold = alts[0].first_breach is not None
    status = "RED" if (validity.state == "invalid" or breach_hold) else "AMBER"
    result = PredictionResult(vessel_id=v.vessel_id, engine="transit", as_of_utc=as_of, input_age_s=round(input_age, 1),
                              hazards_checked=checked, alternatives=alts, forcing_basis=basis)
    snapshot = {"request": req.model_dump(mode="json"), "as_of": as_of.isoformat(), "code_version": CODE_VERSION,
                "ship": ship.model_dump(mode="json"), "transit_requests": {k: t.model_dump(mode="json") for k, (t, _) in central.items()}}
    assumptions = ["Path from the S6 transit simulator run forward from the observed state with the current rudder and engine order held.",
                   "Hull footprint is a parametric planform from catalog LOA and beam centred on the reported position, rotated by heading.",
                   _env_assumption(req, basis) if (req.environment or series is not None) else "No environment supplied: calm assumed (labeled, not unknown).",
                   f"Corridor spread (when sampled): start position/heading/speed per the supplied one-sigma values; wind speed {WIND_SPEED_FRAC:.0%}, "
                   f"wind direction {WIND_DIR_DEG:g} deg, current speed {CURRENT_SPEED_FRAC:.0%}, current direction {CURRENT_DIR_DEG:g} deg (illustrative sd)."]
    return envelope(PredictionResponse, model="mooring.prediction.trajectory", model_version="1.0.0", backend="real", request=req,
                    result=result, status=status, validity=validity, assumptions=assumptions,
                    manifest=ResultManifest(resolved_inputs_hash=resolved_inputs_hash(snapshot), code_version=CODE_VERSION,
                                            numerical_settings={"dt_s": req.dt_s, "tick_s": req.tick_s, "sample_dt_s": max(req.dt_s, SAMPLE_DT_S) if n_s else 0.0,
                                                                "samples": n_s, "seed": req.uncertainty.seed}))


def _env_assumption(req, basis) -> str:
    if basis.kind == "fixed_environment":
        return "Environment held constant over the horizon."
    return (f"Environment time-varying: forcing series {basis.revision} ({basis.series_kind}, "
            f"{'synthetic' if basis.synthetic else 'supplied, unverified'}) sampled at prediction-relative time (t = 0 at as_of_utc), "
            "once per integration step (zero-order hold, not RK4 stage times), around "
            + ("the supplied environment." if req.environment else "a calm base (none supplied)."))


def _validity(req, central_hold, input_age, env_age, n_s, dt_s_used, *, checked=(), n_req=0, hz=None, horizon_s=0.0, basis=None) -> Validity:
    treq, r = central_hold
    inherited = sim.validity_for(treq, r)
    drop = {"SYNTHETIC_EPOCH"} | ({"CALM_ASSUMED"} if basis is not None and basis.kind == "time_varying" else set())
    reasons = [x for x in inherited.reasons if x.code not in drop]
    if basis is not None and basis.kind == "time_varying":
        reasons.append(ValidityReason(code="FORCING_TIME_VARYING", message=(
            f"Forcing basis time_varying: series {basis.revision} ({basis.series_kind}), covering {basis.coverage.start_s:g}..{basis.coverage.end_s:g} s "
            "after as_of_utc; sampled once per integration step. The series is "
            + ("synthetic (generated, not an observation or forecast)." if basis.synthetic else "supplied samples whose origin and accuracy are not verified."))))
        reasons.append(ValidityReason(code="FORCING_SYNTHETIC" if basis.synthetic else "FORCING_SUPPLIED_UNVERIFIED", message=f"forcing revision {basis.revision}"))
        if basis.truncated:
            reasons.append(ValidityReason(code="FORCING_HORIZON_TRUNCATED", message=(
                f"Requested horizon {basis.requested_horizon_s:g} s exceeds the forcing coverage; the prediction stops at {basis.horizon_s:g} s "
                "(on_uncovered='invalidate'). Nothing beyond it is predicted or extrapolated.")))
        if req.forcing is not None and req.forcing.vessel_relative_wind:
            reasons.append(ValidityReason(code="FORCING_VESSEL_RELATIVE_WIND_IGNORED", message="The transit engine always applies apparent wind itself; the flag has no further effect."))
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
    kinds = ("pier", "fender", "coastline", "vessel")
    unchecked = [k for k in kinds if k not in checked]
    if not checked:
        reasons.append(ValidityReason(code="HAZARD_COVERAGE_UNKNOWN", message=(
            "No hazard layer was checked (no berth, no other vessels, no coastline data). The absence of a predicted breach or "
            "closest approach is NOT an all-clear: coverage is unknown.")))
    elif unchecked:
        reasons.append(ValidityReason(code="HAZARD_COVERAGE_INCOMPLETE", message=(
            f"Hazard kinds not checked: {', '.join(unchecked)}. Checked: {', '.join(checked)}. Unchecked kinds are unknown, not clear.")))
    if hz is not None:
        short = [oid for oid, rows, *_ in hz.others if rows[-1][0] < horizon_s or rows[0][0] > 0]
        if short:
            reasons.append(ValidityReason(code="OTHER_VESSEL_PATH_SHORT", message=(
                f"The supplied path of {', '.join(short)} does not cover the whole horizon; the vessel is held at its first/last "
                "supplied position outside it (not predicted).")))
    reasons.append(ValidityReason(code="SWEPT_HULL_CHECK", message=(
        f"Clearance is checked on the swept hull between samples (at most {CHECK_S:g} s apart centrally, {SAMPLE_CHECK_S:g} s for "
        "samples; the convex hull of consecutive footprints), including the initial footprint. Other vessels are swept over the "
        "same interval, which is conservative.")))
    if not n_s:
        why = ("not requested (samples = 0)" if not n_req else
               "not computable: it needs at least 2 samples and a spread source (initial-state uncertainty or non-zero wind/current)")
        reasons.append(ValidityReason(code="UNCERTAINTY_UNAVAILABLE", message=(
            f"No corridor, position spread or breach probability: {why}. This is unavailable, not zero width.")))
    if n_s:
        reasons.append(ValidityReason(code="UNCERTAINTY_ILLUSTRATIVE", message="Illustrative spread of simple seeded perturbations; the S10 uncertainty model is not yet wired. "
                       "Breach probability is a sample share, not calibrated." + (f" Samples use dt {dt_s_used:g} s." if dt_s_used else "")))
    return Validity(state=inherited.state, reasons=reasons)
