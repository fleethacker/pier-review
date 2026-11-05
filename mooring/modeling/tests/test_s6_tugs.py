"""S6 tug benchmarks: pure sway push, yaw sign, bollard-pull limit, slew, and automatic assist."""

import math

import pytest
from s6_helpers import run, states, vessel

from mooring.transit import coefficients as C

LBF = C.LBF_N


def still(tug_commands, **kw):
    return vessel(speed=0.0, mode="tug_assisted", helm=[{"t_s": 0, "rudder_deg": 0, "engine_order": 0.0}],
                  tug_commands=tug_commands, **kw)


def cmd(tid, point, force, direction, t=0.0):
    return {"t_s": t, "tug_id": tid, "point": point, "force_lbf": force, "direction_rel_deg": direction}


def test_balanced_sway_push_gives_sway_without_yaw_moment():
    """Two tugs pushing the same way at +/-0.3 LOA: net force sideways, zero moment about midships."""
    r = run([still([cmd("T1", "port_shoulder", 50000, 90.0), cmd("T2", "port_quarter", 50000, 90.0)])], dur=60, dt=0.1, sample=1.0)
    st = states(r)
    f = st[-1].forces.tugs
    assert f.sway_lbf < -99000 and abs(f.yaw_ftlbf) < 1e-6 * abs(f.sway_lbf)    # toward starboard, no moment
    assert st[0].r_degps == 0.0
    assert st[-1].v_kt < 0                                                      # sways to starboard
    # Yaw develops only through hydrodynamic cross-coupling (Clarke N_v, Y_rdot, N_vdot) once the hull moves sideways.
    # Compare with the same total force applied as a bow push: the yaw rate after 10 s must be a small fraction (<15 %) of it.
    t10 = next(s_ for f, s_ in zip(r.frames, st) if f.t_s >= 10.0)
    bow = states(run([still([cmd("T1", "bow", 100000, 90.0)])], dur=60, dt=0.1, sample=1.0))
    bow10 = next(s_ for f, s_ in zip(r.frames, bow) if f.t_s >= 10.0)
    print(f"S6 balanced sway push: after 10 s r={t10.r_degps:.5f} deg/s vs {abs(bow10.r_degps):.5f} for the same force at the bow; "
          f"after 60 s v={st[-1].v_kt:.2f} kt, r={st[-1].r_degps:.4f} deg/s")
    assert abs(t10.r_degps) < 0.15 * abs(bow10.r_degps)      # measured ~0.10: the hydrodynamic coupling, not a tug moment


def test_bow_push_to_port_yaws_ccw_and_stern_push_yaws_cw():
    bow = states(run([still([cmd("T1", "bow", 40000, 270.0)])], dur=60, dt=0.1))
    stern = states(run([still([cmd("T1", "stern", 40000, 270.0)])], dur=60, dt=0.1))
    assert bow[-1].forces.tugs.yaw_ftlbf > 0 and bow[-1].r_degps > 0 and bow[-1].v_kt > 0        # bow to port: CCW, + port
    assert stern[-1].forces.tugs.yaw_ftlbf < 0 and stern[-1].r_degps < 0 and stern[-1].v_kt > 0
    # moment = x * Fy with x = 0.45 LOA
    loa_ft = 509.5
    assert bow[-1].forces.tugs.yaw_ftlbf == pytest.approx(0.45 * loa_ft * bow[-1].forces.tugs.sway_lbf, rel=1e-9)


def test_bow_tug_ahead_pulls_surge_and_moment_sign_for_shoulder_push():
    st = states(run([still([cmd("T1", "bow", 30000, 0.0)])], dur=40, dt=0.1))
    assert st[-1].forces.tugs.surge_lbf > 29000 and abs(st[-1].forces.tugs.yaw_ftlbf) < 1e-6
    # starboard shoulder pushing toward port (270): Fy > 0 at x > 0 -> CCW
    sh = states(run([still([cmd("T2", "starboard_shoulder", 30000, 270.0)])], dur=40, dt=0.1))
    assert sh[-1].forces.tugs.yaw_ftlbf > 0


def test_tug_force_never_exceeds_bollard_pull_and_saturation_event():
    r = run([still([cmd("T4", "bow", 1_000_000, 270.0)])], dur=120, dt=0.1)
    st = states(r)
    assert max(t.force_lbf for s in st for t in s.tugs) <= 66000 * (1 + 1e-9)       # T4 bollard pull ahead
    assert max(t.force_lbf for s in st for t in s.tugs) > 65000
    assert any(e.kind == "tug_saturated" for e in r.events)
    assert max(abs(s.forces.tugs.sway_lbf) for s in st) <= 66000 * (1 + 1e-9)


def test_tug_slew_is_linear_over_ten_seconds():
    r = run([still([cmd("T1", "bow", 100000, 270.0, t=5.0)])], dur=30, dt=0.1, sample=1.0)
    st = {f.t_s: s for f, s in zip(r.frames, states(r))}
    assert st[5.0].tugs == [] or st[5.0].tugs[0].force_lbf == 0.0
    assert st[10.0].tugs[0].force_lbf == pytest.approx(130000 / 10.0 * 5.0, rel=1e-6)   # T1 bollard 130 klbf: rate = bollard / 10 s
    assert st[15.0].tugs[0].force_lbf == pytest.approx(100000, rel=1e-6)
    assert st[15.0].tugs[0].lat != 0 and st[15.0].tugs[0].point == "bow"


def test_tug_reports_hull_contact_point_position():
    r = run([still([cmd("T1", "bow", 20000, 0.0)], heading=0.0)], dur=10, dt=0.1)
    s = states(r)[-1]
    # a north-heading ship: the bow contact point is 0.45 LOA north of the ship's midships position
    from mooring.transit.geo import LocalPlane
    p = LocalPlane(37.0, -76.0)
    e1, n1 = p.to_local(s.lat, s.lon)
    e2, n2 = p.to_local(s.tugs[0].lat, s.tugs[0].lon)
    assert math.hypot(e2 - e1, n2 - n1 - 0.45 * 509.5 * 0.3048) < 0.5


def test_tug_wrench_independent_of_ship_heading_in_body_axes():
    a = states(run([still([cmd("T1", "bow", 30000, 270.0)], heading=0.0)], dur=20, dt=0.1))[-1].forces.tugs
    b = states(run([still([cmd("T1", "bow", 30000, 270.0)], heading=137.0)], dur=20, dt=0.1))[-1].forces.tugs
    assert (a.surge_lbf, a.sway_lbf, a.yaw_ftlbf) == pytest.approx((b.surge_lbf, b.sway_lbf, b.yaw_ftlbf))


def test_auto_assist_turns_a_slow_ship_and_respects_bollard_pull():
    """A ship at rest told to head for a waypoint 90 deg to port: with auto assist tugs supply the turning moment."""
    route = [{"lat": 37.0, "lon": -76.02, "speed_kt": 3.0}]       # due west of the start; ship heads north
    v = vessel(speed=0.0, heading=0.0, route=route, mode="tug_assisted",
               tug_assist={"policy": "auto", "tug_ids": ["T1", "T2"], "assist_below_kt": 5.0},
               helm=[{"t_s": 0, "engine_order": 0.0}])             # engine held stopped: heading change must come from tugs
    r = run([v], dur=400, dt=0.2, sample=2.0)
    st = states(r)
    assert any(s.tugs for s in st)
    assert max(t.force_lbf for s in st for t in s.tugs) <= 130000
    assert {t.source for s in st for t in s.tugs} == {"auto_assist"}
    print(f"S6 auto assist: heading after 400 s = {st[-1].heading_true_deg:.1f} deg (target ~270), max tug force "
          f"{max(t.force_lbf for s in st for t in s.tugs):.0f} lbf")
    assert 250 < st[-1].heading_true_deg < 290


def test_own_thrust_rejects_tug_commands_and_assist():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        from s6_helpers import request
        request([vessel(mode="own_thrust", tug_commands=[cmd("T1", "bow", 1000, 0.0)])])
    with pytest.raises(ValidationError):
        from s6_helpers import request
        request([vessel(mode="own_thrust", tug_assist={"policy": "auto"})])
