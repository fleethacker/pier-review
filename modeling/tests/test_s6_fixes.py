"""Regression tests for the independent physics review of the S6 transit simulator (each fails on the pre-fix code)."""

import math

import pytest
from fastapi.testclient import TestClient
from s6_helpers import env, request, run, states, vessel

from modeling_api.main import app
from mooring import refdata
from mooring.core.schemas import PropulsionAssumptions
from mooring.transit import coefficients as C
from mooring.transit import simulator as S
from mooring.transit.autopilot import Autopilot
from mooring.transit.geo import LocalPlane
from mooring.transit.hull import build_hull
from mooring.transit.nomoto import linearise
from mooring.transit.propulsion import build_propulsion

KT = C.KT_MPS
FT = 0.3048
client = TestClient(app)
CLASSES = [("DDG-51-FIIA", 30.0), ("CG-47", 30.0), ("LHD-1", 22.0), ("CVN-68", 30.0)]


def final_leg(cls, cur_kt=0.0, cur_toward=0.0, radius_ft=300.0, varr=0.0, dur=3000.0, dlon=0.06, spd=12.0, **kw):
    route = [{"lat": 37.0, "lon": -76.0 + dlon, "speed_kt": spd, **({"acceptance_radius_ft": radius_ft} if radius_ft else {})}]
    v = vessel(cls=cls, speed=spd, heading=90.0, route=route, autopilot={"arrival_slowdown_nm": 0.5, "arrival_speed_kt": varr}, **kw)
    return run([v], dur=dur, dt=0.2, sample=5.0, env=env(cur_kt=cur_kt, cur_toward=cur_toward) if cur_kt else None)


# ---------------- fix 1: arrival over ground, in current ----------------

@pytest.mark.parametrize("cls,cur,toward,label", [
    ("DDG-51-FIIA", 2.0, 270.0, "foul 2 kt"), ("DDG-51-FIIA", 3.0, 90.0, "fair 3 kt"),
    ("CVN-68", 3.0, 90.0, "CVN fair 3 kt"), ("CVN-68", 0.0, 0.0, "CVN calm")])
def test_arrival_in_current_is_judged_over_ground(cls, cur, toward, label):
    """Foul: the engine must deliver STW above the ground target. Fair: it must go astern. Arrival is SOG <= 0.5 kt inside the radius.
    (Pre-fix: DDG foul stalled 477 ft short at SOG 0 without any event; DDG fair 'arrived' at SOG 3.5 kt; CVN fair drifted away at 3 kt.)"""
    r = final_leg(cls, cur, toward)
    v = r.vessels[0]
    s = states(r)[-1]
    assert v.status == "arrived", (label, s.status, s.sog_kt, s.distance_to_go_nm * 6076)
    assert s.sog_kt <= 0.5 + 0.02 and s.distance_to_go_nm * 1852 < 300 * FT + 1
    if cur and toward == 90.0:
        assert s.stw_kt < 0                       # held against a following current by going astern
    if cur and toward == 270.0:
        assert s.stw_kt > 1.5                     # stemming the current: STW above the ground target
    print(f"S6 arrival {label}: arrived {v.arrival_t:.0f} s, SOG {s.sog_kt:.2f} kt, STW {s.stw_kt:.2f} kt, "
          f"{sum(e.kind == 'missed_approach' for e in r.events)} missed approaches")


def test_arrival_is_not_declared_on_through_water_speed():
    """Fair current: STW ~0.5 kt but SOG 3.5 kt inside the radius is NOT an arrival (pre-fix it was)."""
    a = _ap([(0.0, 0.0), (1000.0, 0.0)], radius=100.0)
    a.update(0.0, 0.2, (950.0, 0.0), 90.0, 0.5 * KT, 0.0, 3.5 * KT, 90.0, 0.0)
    assert a.status == "underway"
    ev = a.update(0.2, 0.2, (950.0, 0.0), 90.0, 0.5 * KT, 0.0, 0.4 * KT, 90.0, 0.0).events
    assert a.status == "arrived" and [k for k, _ in ev] == ["arrived"]


def _ap(pts, radius=100.0, varr=0.0, **kw):
    n = len(pts) - 1
    return Autopilot(pts, [8 * KT] * n, [radius] * n, L=142.0, v_max=15.0, lookahead_ls=2.0, slow_dist_m=926.0, v_arrival=varr,
                     max_rudder=0.6, m33=1e10, m11=1e7, **kw)


def test_passing_the_final_waypoint_outside_the_radius_is_reported_and_reapproached():
    a = _ap([(0.0, 0.0), (1000.0, 0.0)], radius=100.0)
    ev = a.update(0.0, 0.2, (1300.0, 40.0), 90.0, 3.0, 0.0, 3.0, 90.0, 0.0).events        # 300 m past the end, outside 100 m
    assert [k for k, _ in ev] == ["missed_approach"]
    cmd = a.update(0.2, 0.2, (1300.0, 40.0), 90.0, 3.0, 0.0, 3.0, 90.0, 0.0)
    assert abs(((cmd.psi_cmd_deg - 270.0 + 180) % 360) - 180) < 15      # steering back toward the waypoint (westward)
    assert cmd.v_target <= 6.0 * KT + 1e-9


def test_stopped_short_uses_sog_not_through_water_speed():
    """Stemming a current with STW 2 kt but SOG 0: pre-fix this was never reported (STW > 0.3 kt)."""
    a = _ap([(0.0, 0.0), (0.0, 5000.0)])
    ev = []
    for k in range(700):
        ev += a.update(k * 0.2, 0.2, (0.0, 3000.0), 0.0, 2.0 * KT, 0.0, 0.0, 0.0, 0.0).events
    assert a.status == "stopped_short" and [k for k, _ in ev] == ["stopped_short"]


def test_missed_approach_is_a_valid_schema_event():
    from mooring.core.schemas import TransitEvent
    TransitEvent(t_s=1.0, vessel_id="A", kind="missed_approach", detail="x")


# ---------------- fix 2: crab compensation ----------------

def test_crab_only_when_fast_enough_clamped_and_never_astern():
    """Ship heading east on an eastward track; current toward north c. Water velocity (u, 0), ground (u, c)."""
    def drive(u_kt, c_kt, steps=2000, astern=False, t0=0.0, a=None):
        a = a or _ap([(0.0, 0.0), (500000.0, 0.0)])
        u, c = u_kt * KT, c_kt * KT
        gx, gy = (-u if astern else u), c
        cog = math.degrees(math.atan2(gx, gy)) % 360
        for k in range(steps):
            a.update(t0 + k * 0.2, 0.2, (100.0 + k, 0.0), 90.0, -u if astern else u, 0.0, math.hypot(gx, gy), cog, 0.0)
        return a
    assert abs(drive(3.5, 2.0).beta) < 1e-9                                  # STW < max(3 kt, 2 x 2 kt): no crab despite 30 deg drift
    a = drive(12.0, 2.0)                                                       # fast enough: crab = drift, atan(2/12) = 9.5 deg
    assert math.degrees(a.beta) == pytest.approx(-math.degrees(math.atan2(2.0, 12.0)), abs=0.3) or \
           abs(math.degrees(a.beta)) == pytest.approx(math.degrees(math.atan2(2.0, 12.0)), abs=0.3)
    a = drive(12.0, 5.0)                                                       # drift 22.6 deg: clamped to 20
    assert abs(math.degrees(a.beta)) == pytest.approx(20.0, abs=0.3)
    drive(2.0, 1.0, steps=3000, t0=500.0, a=a)                                # slow down: decays to zero
    assert abs(a.beta) < 1e-4
    assert abs(drive(6.0, 1.0, astern=True).beta) < 1e-9                       # astern: COG - heading never used


def test_cross_current_in_the_arrival_zone_arrives_without_a_rudder_saturation_spiral():
    """2 kt cross current while slowing to arrive (default 2 L radius). Pre-fix the crab low-pass of COG-heading at low speed fed
    a spiral: rudder pinned, the ship set away and never arriving. A single turn-around (missed approach) is allowed; sustained
    saturation is not. Stopping in a cross current needs the ship to face the current: documented in docs/PORT_TRANSIT.md."""
    r = final_leg("DDG-51-FIIA", 2.0, 0.0, radius_ft=None, dur=2400)
    st = states(r)
    assert r.vessels[0].status == "arrived"
    sat = sum(1 for s in st if abs(s.rudder_deg) >= 34.5) * 5.0
    assert sat < 150.0, sat                                           # seconds with the rudder at its limit
    assert all(abs(s.rudder_deg) < 34.5 for s in st[-int(120 / 5):])    # not saturated while arriving
    assert sum(e.kind == "missed_approach" for e in r.events) <= 1


# ---------------- fix 3: model-based heading controller ----------------

def _hull_prop(cls, vmax):
    ship = refdata.ship(cls)
    h = build_hull(ship, refdata.loading(ship, "full_load"), C.RHO_WATER_DEFAULT)
    return h, build_propulsion(h, PropulsionAssumptions(), vmax * KT, cls)


@pytest.mark.parametrize("cls,vmax", CLASSES)
def test_nomoto_gain_matches_simulated_small_rudder_step(cls, vmax, monkeypatch):
    """K from the linearised model equals the simulated steady yaw rate per radian of rudder (small step, hull-only forces)."""
    monkeypatch.setattr(S.Vessel, "wind_wrench", lambda self, s: (0.0, 0.0, 0.0))
    h, p = _hull_prop(cls, vmax)
    kt = 8.0
    lin = linearise(h, p, kt * KT)
    # engine order that holds 8 kt: T = R(8 kt) => order = R/Tmax
    order = h.resistance(kt * KT) / p.t_max
    r = run([vessel(cls=cls, speed=kt, helm=[{"t_s": 0, "rudder_deg": 0.0, "engine_order": order}, {"t_s": 100, "rudder_deg": 1.0, "engine_order": order}])],
            dur=1800, dt=0.5, sample=5.0)
    st = states(r)
    r_ss = math.radians(st[-1].r_degps)
    pred = lin.K * math.radians(1.0)
    print(f"S6 Nomoto {cls} 8 kt: K = {lin.K:.4f} 1/s, T = {lin.T:.1f} s, steady r simulated {r_ss:.3e} vs K delta {pred:.3e} rad/s")
    assert r_ss == pytest.approx(pred, rel=0.12)


def test_clarke_stability_index_is_reported_negative_for_lhd_and_cvn_hulls():
    """The linear Clarke stability index of the HULL ALONE is negative for LHD-1 and CVN-68 (course-unstable) and positive for
    DDG-51 and CG-47; with the rudder fixed amidships (its lateral damping) all four are stable in the linear model."""
    for cls, vmax in CLASSES:
        h, p = _hull_prop(cls, vmax)
        lin = linearise(h, p, 8.0 * KT)
        assert lin.stable_hull == (cls in ("DDG-51-FIIA", "CG-47")), (cls, lin.c_hull)
        assert lin.stable_total
        print(f"S6 stability {cls}: c_hull {lin.c_hull:.3g} ({'stable' if lin.stable_hull else 'UNSTABLE'}), with rudder {lin.c_total:.3g}")


class _Unstable:
    """A course-unstable linear model (T < 0, K < 0)."""
    def at(self, u):
        return -0.02, -80.0


def test_heading_controller_valid_for_course_unstable_hull():
    a = _ap([(0.0, 0.0), (50000.0, 0.0)], nomoto=_Unstable())
    cmd = a.update(0.0, 0.2, (0.0, 0.0), 89.5, 8 * KT, 0.0, 8 * KT, 89.5, 0.0)          # heading 0.5 deg left of track (needs +CW)
    assert cmd.rudder_rad < 0                         # clockwise (starboard) correction = negative rudder (+ is bow to port)
    cmd2 = a.update(0.2, 0.2, (0.0, 0.0), 89.5, 8 * KT, 0.01, 8 * KT, 89.5, 0.0)
    assert cmd2.rudder_rad < cmd.rudder_rad           # a CCW swing (r > 0) that worsens the error demands more CW rudder (Kd > 0)


def _turn_case(cls, kt, dur=2400.0, dt=0.2, turn=60.0, radius_L=2.0):
    L = refdata.ship(cls).lwl_ft * FT
    U = kt * KT
    plane = LocalPlane(37.0, -76.0)
    d1 = max(U * 100, 2 * L)
    b2 = 90.0 - turn
    far = 60000.0
    p1, p2 = (d1, 0.0), (d1 + far * math.sin(math.radians(b2)), far * math.cos(math.radians(b2)))
    geo = lambda p: dict(zip(("lat", "lon"), plane.to_geo(*p)))
    route = [dict(**geo(p1), speed_kt=kt, acceptance_radius_ft=radius_L * L / FT), dict(**geo(p2), speed_kt=kt)]
    req = request([vessel(cls=cls, speed=kt, heading=90.0, route=route)], dur=dur, dt=dt)
    _, _, _, vs = S.prepare(req)
    v = vs[0]
    rec = []
    for k in range(int(dur / dt)):
        v.step(dt)
        if k % 10 == 0:
            rec.append((math.degrees(v.s[2]) % 360, v.cmd.psi_cmd_deg, v.ap.cross_track((v.s[0], v.s[1])) / FT, v.ap.i))
    wrap = lambda x: (x + 180) % 360 - 180
    ov_cmd = max(max(0.0, wrap(pc - h)) for h, pc, xt, i in rec if i >= 2)        # port turn: overshoot = heading below the command
    ov_leg = max(max(0.0, wrap(b2 - h)) for h, pc, xt, i in rec if i >= 2)
    third = len(rec) // 3
    a1 = max(abs(x[2]) for x in rec[:third])
    a3 = max(abs(x[2]) for x in rec[-third:])
    return ov_cmd, ov_leg, a1, a3


@pytest.mark.parametrize("cls,vmax", CLASSES)
@pytest.mark.parametrize("kt", [4.0, 8.0, 15.0])
def test_sixty_degree_course_change_benchmark(cls, vmax, kt):
    ov_cmd, ov_leg, a1, a3 = _turn_case(cls, kt)
    print(f"S6 course change 60 deg {cls} {kt:g} kt: overshoot vs guidance command {ov_cmd:.1f} deg, vs new leg bearing {ov_leg:.1f} deg, "
          f"cross-track first third {a1:.0f} ft, last third {a3:.1f} ft")
    assert ov_cmd < 10.0
    assert a3 < 0.2 * a1 and a3 < 100.0


# ---------------- fix 4 and 5: tug auto assist ----------------

def _assisted(helm=None, **kw):
    return vessel(speed=kw.pop("speed", 4.0), heading=0.0, mode="tug_assisted",
                  route=[{"lat": 37.0, "lon": -75.97, "speed_kt": 8.0}],
                  tug_assist={"policy": "auto", "tug_ids": ["T1", "T2"], "assist_below_kt": 5.0}, helm=helm or [], **kw)


def test_auto_assist_forces_return_to_zero_above_the_assist_speed():
    """Pre-fix the auto-assist command was never cleared once |u| >= assist_below, so the last force persisted for the rest of the run."""
    v = _assisted(helm=[{"t_s": 0, "engine_order": 1.0}], speed=3.0)
    r = run([v], dur=240, dt=0.2, sample=2.0)
    st = states(r)
    first = next(s for s in st if s.tugs)
    assert max(t.force_lbf for s in st[:30] for t in s.tugs) > 1000.0          # assisting while slow
    above = [(f.t_s, s) for f, s in zip(r.frames, st) if s.stw_kt > 5.0 + 0.2]
    assert above, "ship never exceeded the assist speed"
    t0 = above[0][0]
    late = [s for t, s in above if t > t0 + 15.0]                            # 10 s slew + margin
    assert late and all(t.force_lbf < 1.0 for s in late for t in s.tugs)
    assert first.tugs[0].source == "auto_assist"


def test_yaw_moment_allocation_thruster_first_then_tugs_without_double_counting():
    """Pre-fix the bow thruster and the tugs were each commanded the FULL deficit (delivered about twice the demand)."""
    v = vessel(speed=0.0, heading=0.0, mode="tug_assisted", route=[{"lat": 37.0, "lon": -75.97, "speed_kt": 3.0}],
               tug_assist={"policy": "auto", "tug_ids": ["T1", "T2"], "assist_below_kt": 5.0}, helm=[{"t_s": 0, "engine_order": 0.0}],
               propulsion={"bow_thruster_lbf": 20000})
    req = request([v], dur=40, dt=0.2, sample=1.0)
    _, _, _, vs = S.prepare(req)
    V = vs[0]
    cap = V.prop.thruster_max * V.prop.thruster_x                       # thruster moment capacity, N m
    # allocation arithmetic
    big = 3.0 * cap
    thr, rem = V.allocate_yaw(big, 0.0)
    assert thr == pytest.approx(V.prop.thruster_max) and rem == pytest.approx(big - cap)
    thr, rem = V.allocate_yaw(0.4 * cap, 0.0)
    assert thr * V.prop.thruster_x == pytest.approx(0.4 * cap) and rem == pytest.approx(0.0, abs=1e-6)
    # end to end: at t = 30 s (all slews done) the delivered moment of thruster + tugs equals the demanded deficit
    for _ in range(int(30 / 0.2)):
        V.step(0.2)
    st = V.state_model(30.0)
    delivered = (st.forces.bow_thruster.yaw_ftlbf + st.forces.tugs.yaw_ftlbf) * 1.3558179483314004      # N m
    assert abs(V.last_deficit) > 2 * cap                               # the tugs are needed on top of the thruster
    assert delivered == pytest.approx(V.last_deficit, rel=0.1)


# ---------------- fix 8 ----------------

def test_helm_command_with_null_field_releases_that_control_to_the_autopilot():
    far = [{"lat": 37.0, "lon": -75.9, "speed_kt": 10.0}]
    v = vessel(speed=10.0, heading=90.0, route=far, helm=[{"t_s": 0, "rudder_deg": 20.0, "engine_order": 0.0},
                                                         {"t_s": 60, "engine_order": 0.0}])       # null rudder: back to the autopilot
    r = run([v], dur=240, dt=0.2, sample=1.0)
    st = {f.t_s: s for f, s in zip(r.frames, states(r))}
    assert st[30.0].rudder_deg == pytest.approx(20.0, abs=0.1)
    assert abs(st[200.0].rudder_deg) < 8.0                                                        # autopilot steering back to the leg
    assert st[200.0].engine_order == 0.0                                                         # the engine order stays scripted
    v2 = vessel(speed=10.0, heading=90.0, route=far, helm=[{"t_s": 0, "rudder_deg": 5.0, "engine_order": 0.3}, {"t_s": 50, "rudder_deg": 5.0}])
    r2 = run([v2], dur=120, dt=0.2, sample=1.0)
    s2 = {f.t_s: s for f, s in zip(r2.frames, states(r2))}
    assert s2[40.0].engine_order == pytest.approx(0.3) and s2[100.0].engine_order != pytest.approx(0.3)      # engine released at t = 50


def test_arrived_vessel_is_frozen_while_others_continue():
    a = vessel("A", speed=8.0, heading=90.0, route=[{"lat": 37.0, "lon": -75.99, "speed_kt": 8.0, "acceptance_radius_ft": 400}],
               autopilot={"arrival_slowdown_nm": 0.2, "arrival_speed_kt": 0.0})
    b = vessel("B", speed=8.0, heading=90.0, route=[{"lat": 37.05, "lon": -75.95, "speed_kt": 8.0}])
    b["start"]["lat"] = 37.02
    r = run([a, b], dur=900, dt=0.2, sample=5.0)
    sa, sb = states(r, "A"), states(r, "B")
    ta = r.vessels[0].arrival_t
    assert ta is not None and ta < 600 and r.vessels[0].status == "arrived"
    after = [s for f, s in zip(r.frames, sa) if f.t_s > ta + 6]
    assert len(after) > 10
    assert all(s.status == "arrived" and (s.x_east_ft, s.y_north_ft, s.heading_true_deg, s.stw_kt) ==
               (after[0].x_east_ft, after[0].y_north_ft, after[0].heading_true_deg, after[0].stw_kt) for s in after)
    assert sb[-1].x_east_ft > sb[int(ta / 5)].x_east_ft + 500                       # B kept going
    assert r.frames[-1].t_s > ta + 100


def test_output_frames_fall_exactly_on_the_requested_sample_times():
    v = vessel(speed=8.0, heading=90.0, route=[{"lat": 37.0, "lon": -75.9, "speed_kt": 8.0}])
    r = run([v], dur=101.0, dt=0.3, sample=2.0)                               # 0.3 does not divide 2.0
    ts = [f.t_s for f in r.frames]
    assert ts == pytest.approx([*[2.0 * k for k in range(51)], 101.0], abs=1e-9)  # regular samples plus the full horizon
    assert r.sample_s == 2.0 and r.dt_s == pytest.approx(2.0 / 7) and r.dt_s <= 0.3
    assert r.vessels[0].track[-1].t_utc.timestamp() - r.vessels[0].track[0].t_utc.timestamp() == pytest.approx(101.0)
    assert S.effective_step(0.2, 2.0) == (pytest.approx(0.2), 10) and S.effective_step(1.0, 0.5)[0] == 0.5
    res = S.simulate_transit(request([v], dur=101.0, dt=0.3, sample=2.0), "samp-1", "/api/v1")
    assert res.manifest.numerical_settings["sample_interval_s"] == 2.0
    assert res.manifest.numerical_settings["dt_requested_s"] == 0.3


def test_early_stop_ends_on_a_sample_boundary():
    v = vessel(speed=8.0, heading=90.0, route=[{"lat": 37.0, "lon": -75.99, "speed_kt": 8.0, "acceptance_radius_ft": 400}],
               autopilot={"arrival_slowdown_nm": 0.2, "arrival_speed_kt": 0.0})
    r = run([v], dur=3000, dt=0.3, sample=5.0)
    ts = [f.t_s for f in r.frames]
    assert r.vessels[0].status == "arrived" and ts[-1] < 3000
    assert ts == pytest.approx([5.0 * k for k in range(len(ts))], abs=1e-9)


def test_frame_zero_shows_the_real_wind_force():
    v = vessel(speed=0.0, heading=0.0, helm=[{"t_s": 0, "engine_order": 0.0, "rudder_deg": 0.0}])
    r = run([v], dur=10, dt=0.5, env=env(wind_kt=30.0, wind_from=90.0))
    f0 = states(r)[0]
    assert f0.forces.wind.sway_lbf > 10000.0                       # pre-fix: exactly 0 in frame 0


def test_max_cross_track_excludes_the_leg_switch_corner():
    # unit: just after switching onto the second leg of a 90 degree corner the ship is still on the first leg's line
    pts = [(0.0, 0.0), (3000.0, 0.0), (3000.0, 6000.0)]
    a = _ap(pts, radius=300.0)
    a.update(0.0, 0.2, (2750.0, 0.0), 90.0, 5.0, 0.0, 5.0, 90.0, 0.0)                    # inside the radius: switches to leg 2
    assert a.i == 2
    pos = (2900.0, 0.0)                                                                     # 100 m before the corner, on leg 1's line
    assert abs(a.cross_track(pos)) == pytest.approx(100.0)                                  # raw distance to leg 2's line
    assert a.cross_track_metric(pos) == pytest.approx(0.0, abs=1e-9)                       # but it is on the previous leg
    far = (3000.0 + 800.0, 3000.0)                                                          # well off leg 2, outside the corner region
    assert a.cross_track_metric(far) == pytest.approx(abs(a.cross_track(far)))
    # integration: a corner passage with a generous radius does not report the corner swing as max cross-track
    route = [{"lat": 37.0, "lon": -75.97, "speed_kt": 12.0}, {"lat": 37.04, "lon": -75.97, "speed_kt": 12.0}]
    r = run([vessel(speed=12.0, heading=90.0, route=route)], dur=1500, dt=0.2, sample=5.0)
    raw = max(abs(s.cross_track_ft) for s in states(r))
    assert r.vessels[0].max_xt / FT < 0.7 * raw


def test_routes_with_zero_length_final_leg_or_duplicate_waypoints_are_422():
    base = request([vessel(speed=5.0, route=[{"lat": 37.0, "lon": -75.99, "speed_kt": 8.0}])], dur=10).model_dump(mode="json")
    ok = client.post("/api/v1/transit/simulate", json=base)
    assert ok.status_code == 202
    zero = request([vessel(speed=5.0, route=[{"lat": 37.0, "lon": -76.0, "speed_kt": 8.0}])], dur=10).model_dump(mode="json")
    r = client.post("/api/v1/transit/simulate", json=zero)
    assert r.status_code == 422 and "zero length" in r.text
    dup = request([vessel(speed=5.0, route=[{"lat": 37.0, "lon": -75.99, "speed_kt": 8.0}, {"lat": 37.0, "lon": -75.99, "speed_kt": 8.0},
                                           {"lat": 37.0, "lon": -75.98, "speed_kt": 8.0}])], dur=10).model_dump(mode="json")
    r = client.post("/api/v1/transit/simulate", json=dup)
    assert r.status_code == 422 and "coincide" in r.text
    with pytest.raises(S.RequestInvalid):
        S.prepare(request([vessel(route=[{"lat": 37.0, "lon": -76.0, "speed_kt": 8.0}])], dur=10))


# ---------------- fix 6: twin rudders and Cb ----------------

def test_rudder_count_and_equivalent_rudder_force():
    h, p2 = _hull_prop("DDG-51-FIIA", 30.0)
    assert p2.n_rudders == 2 and all(C.RUDDER_COUNT[c] == 2 for c, _ in CLASSES)
    p1 = build_propulsion(h, PropulsionAssumptions(), 30 * KT, "UNKNOWN-CLASS")
    assert p1.n_rudders == 1
    # at the same total thrust the twin arrangement (T/2 per race) must give about twice the single-rudder side force at speed
    f2 = p2.rudder_forces(math.radians(10), 3e5, 8 * KT, 0.0, 0.0)[1]
    f1 = p1.rudder_forces(math.radians(10), 3e5, 8 * KT, 0.0, 0.0)[1]
    assert 1.3 < f2 / f1 < 2.0          # less than 2x: each race carries T/2, so a slower race at each rudder


def test_block_coefficient_uses_displacement_when_catalog_is_inconsistent():
    from mooring.transit.hull import block_coefficient
    for cls, kept in (("DDG-51-FIIA", False), ("CG-47", False), ("LHD-1", True), ("CVN-68", True)):
        ship = refdata.ship(cls)
        lc = refdata.loading(ship, "full_load")
        h = build_hull(ship, lc, C.RHO_WATER_DEFAULT)
        assert (h.Cb == ship.block_coefficient) == kept, (cls, h.Cb)
        assert h.Cb == pytest.approx(h.m / (C.RHO_WATER_DEFAULT * h.L * h.B * h.T)) or kept
    assert block_coefficient(0.6, 6.0e6, 100.0, 10.0, 6.0 / 1.025 * 1.0 * 0.1) > 0


# ---------------- backup-camera property: route-free prediction from a state ----------------

def test_route_free_prediction_matches_scripted_run_and_is_fast():
    import time
    v = vessel(speed=15.0, heading=40.0, route=[{"lat": 37.3, "lon": -75.8, "speed_kt": 15.0}])
    vt = request([v], dur=10).vessels[0]
    t0 = time.perf_counter()
    pred = S.predict_constant_commands(vt, None, 600.0, rudder_deg=10.0, engine_order=0.5, dt=0.2, sample_s=10.0)
    wall = time.perf_counter() - t0
    scripted = run([{**v, "helm_commands": [{"t_s": 0, "rudder_deg": 10.0, "engine_order": 0.5}]}], dur=600, dt=0.2, sample=10.0)
    a, b = pred[-1][1], states(scripted)[-1]
    assert (a.x_east_ft, a.y_north_ft, a.heading_true_deg) == pytest.approx((b.x_east_ft, b.y_north_ft, b.heading_true_deg))
    assert pred[-1][0] == 600.0 and len(pred) == 61
    again = S.predict_constant_commands(vt, None, 600.0, rudder_deg=10.0, engine_order=0.5, dt=0.2, sample_s=10.0)
    assert [s.model_dump() for _, s in pred] == [s.model_dump() for _, s in again]       # deterministic
    print(f"S6 10-minute route-free prediction, one vessel, dt 0.2 s: wall {wall:.2f} s")
    assert wall < 3.0
