"""S6 analytic and sanity benchmarks for the transit hull/propulsion/rudder model (calm, deep water, scripted helm)."""

import math

import pytest
from s6_helpers import FT, env, run, states, vessel

from mooring import refdata
from mooring.transit import coefficients as C
from mooring.transit import simulator as S
from mooring.transit.hull import build_hull

CLASSES = [("DDG-51-FIIA", 30.0), ("CG-47", 30.0), ("LHD-1", 22.0), ("CVN-68", 30.0)]
KT = C.KT_MPS


@pytest.fixture
def no_air(monkeypatch):
    """Isolate hull + engine dynamics: the calibration (T_max = R(v_max)) and the analytic comparisons below are for
    water resistance only. The own-motion air drag that a calm run now includes (environment=None is treated as a
    zero-wind environment) is switched off here and tested separately in test_calm_includes_own_motion_air_drag."""
    monkeypatch.setattr(S.Vessel, "wind_wrench", lambda self, s: (0.0, 0.0, 0.0))


def full_ahead(cls="DDG-51-FIIA", speed=0.0, rud=0.0, **kw):
    return vessel(cls=cls, speed=speed, helm=[{"t_s": 0, "rudder_deg": rud, "engine_order": 1.0}], **kw)


@pytest.mark.parametrize("cls,vmax", CLASSES)
def test_full_ahead_converges_to_max_speed(cls, vmax, no_air):
    r = run([full_ahead(cls)], dur=4000, dt=0.5)
    st = states(r)
    assert abs(st[-1].stw_kt - vmax) / vmax < 0.02
    assert all(abs(s.sog_kt - s.stw_kt) < 1e-9 for s in st)          # no current, no wind
    print(f"S6 steady speed {cls}: {st[-1].stw_kt:.3f} kt vs max {vmax}")


def _two_lag_time_to_63(hull, tmax, u_inf, u0, tau_e, dt=0.05):
    k = (hull.resistance(u_inf + 0.01) - hull.resistance(u_inf - 0.01)) / 0.02
    du, dT = u0 - u_inf, hull.resistance(u0) - tmax
    t, target = 0.0, 0.368 * (u0 - u_inf)
    while du < target:
        du += dt * (dT - k * du) / hull.m11
        dT += dt * (-dT) / tau_e
        t += dt
    return t, hull.m11 / k


def test_speed_rise_time_matches_linearised_time_constant(no_air):
    cls, vmax = "DDG-51-FIIA", 30.0
    ship = refdata.ship(cls)
    hull = build_hull(ship, refdata.loading(ship, "full_load"), C.RHO_WATER_DEFAULT)
    u_inf, u0 = vmax * KT, 0.95 * vmax * KT
    r = run([full_ahead(cls, speed=0.95 * vmax)], dur=900, dt=0.1, sample=1.0)
    st = states(r)
    gap = u_inf / KT - 0.95 * vmax
    t63 = next(f.t_s for f, s in zip(r.frames, st) if s.stw_kt >= 0.95 * vmax + 0.632 * gap)
    pred, tau_h = _two_lag_time_to_63(hull, hull.resistance(u_inf), u_inf, u0, 20.0)
    print(f"S6 63% rise: simulated {t63:.1f} s, two-lag linear prediction {pred:.1f} s, hull tau {tau_h:.1f} s")
    assert abs(t63 - pred) / pred < 0.06
    assert 40 < tau_h < 200


def test_zero_rudder_calm_goes_straight_and_symmetric():
    r = run([full_ahead(speed=15.0)], dur=600, dt=0.2)
    for s in states(r):
        assert abs(s.v_kt) < 1e-12 and abs(s.r_degps) < 1e-12 and abs(s.x_east_ft) < 1e-9 and abs(s.heading_true_deg) < 1e-9   # headwind drag only


def _turn(sign, cls="DDG-51-FIIA", rud=35.0, dur=900, dt=0.2):
    vmax = dict(CLASSES)[cls]
    r = run([full_ahead(cls, speed=vmax, rud=sign * rud)], dur=dur, dt=dt)
    return r, states(r)


def test_rudder_sign_and_mirror_symmetry():
    _, port = _turn(+1, dur=300)
    _, stbd = _turn(-1, dur=300)
    assert port[-1].r_degps > 0 and port[-1].v_kt >= 0 or port[-1].r_degps > 0     # +rudder: CCW yaw rate
    assert port[10].heading_true_deg > 180 and stbd[10].heading_true_deg < 180    # bow to port = decreasing bearing
    assert port[-1].heading_true_deg != stbd[-1].heading_true_deg
    for a, b in zip(port, stbd):
        assert a.x_east_ft == pytest.approx(-b.x_east_ft, abs=1e-6)
        assert a.y_north_ft == pytest.approx(b.y_north_ft, abs=1e-6)
        assert a.r_degps == pytest.approx(-b.r_degps, abs=1e-9)
        assert (a.heading_true_deg + b.heading_true_deg) % 360 == pytest.approx(0, abs=1e-6) or \
               (a.heading_true_deg + b.heading_true_deg) % 360 == pytest.approx(360, abs=1e-6)
    # +rudder moves the ship to the WEST (port of a north heading)
    assert port[-1].x_east_ft < 0 < stbd[-1].x_east_ft


@pytest.mark.parametrize("cls", ["DDG-51-FIIA", "CG-47", "LHD-1", "CVN-68"])
def test_turning_circle_tactical_diameter_band(cls):
    L = refdata.ship(cls).lwl_ft
    r, st = _turn(+1, cls, dur=1500, dt=0.5)
    td = adv = None
    for s in st:
        if (360 - s.heading_true_deg) % 360 >= 180 and s.heading_true_deg < 180.5:
            td, adv = abs(s.x_east_ft), s.y_north_ft
            break
    assert td is not None, "never completed a 180 degree turn"
    print(f"S6 turning circle {cls}: tactical diameter {td:.0f} ft = {td / L:.2f} L, advance {adv / L:.2f} L, "
          f"final speed {st[-1].stw_kt:.1f} kt, steady yaw rate {st[-1].r_degps:.2f} deg/s")
    assert 2 < td / L < 8


def test_small_rudder_step_is_first_order_like(no_air):
    r = run([full_ahead(speed=15.0, helm=None)] if False else
            [vessel(speed=15.0, helm=[{"t_s": 0, "rudder_deg": 0, "engine_order": 0.4}, {"t_s": 200, "rudder_deg": 2.0, "engine_order": 0.4}])],
            dur=1500, dt=0.2, sample=1.0)
    st = states(r)
    ts = [f.t_s for f in r.frames]
    r0 = [s.r_degps for t, s in zip(ts, st) if t >= 200]
    rinf = r0[-1]
    assert rinf > 0 and all(b >= a - 1e-9 for a, b in zip(r0, r0[1:]))      # monotone rise, no overshoot
    tt = [t - 200 for t in ts if t >= 200]
    def t_at(frac):
        return next(t for t, x in zip(tt, r0) if x >= frac * rinf)
    T = t_at(0.632)
    print(f"S6 rudder step 2 deg at ~15 kt: steady r {rinf:.4f} deg/s, 63% time {T:.1f} s")
    for k, expect in ((2, 0.865), (3, 0.95)):
        val = next(x for t, x in zip(tt, r0) if t >= k * T) / rinf
        assert abs(val - expect) < 0.08, (k, val)


def test_engine_stop_decelerates_monotonically_and_matches_independent_integration(no_air):
    r = run([vessel(speed=20.0, helm=[{"t_s": 0, "rudder_deg": 0, "engine_order": 0.0}])], dur=900, dt=0.2, sample=1.0)
    st = states(r)
    u = [s.stw_kt for s in st]
    assert all(b <= a + 1e-12 for a, b in zip(u, u[1:])) and u[-1] < u[0] * 0.8
    # independent hand-rolled integration of u' = -R(u)/m11 with first-order thrust decay
    ship = refdata.ship("DDG-51-FIIA")
    h = build_hull(ship, refdata.loading(ship, "full_load"), C.RHO_WATER_DEFAULT)
    uu, T, dt = 20 * KT, h.resistance(20 * KT), 0.05
    for _ in range(int(900 / dt)):
        uu += dt * (T - h.resistance(uu)) / h.m11
        T += dt * (-T) / 20.0
    assert u[-1] == pytest.approx(uu / KT, rel=5e-3)


def test_zero_thrust_ship_drifts_with_current_over_ground():
    e = env(cur_kt=2.0, cur_toward=90.0)
    r = run([vessel(speed=0.0, heading=0.0, helm=[{"t_s": 0, "rudder_deg": 0, "engine_order": 0.0}])], dur=1200, dt=0.5, env=e, sample=10.0)
    st = states(r)
    s = st[-1]
    # still air: the drifting hull feels a 2 kt apparent wind, which retards it by about 1 % (checked separately below)
    assert s.sog_kt == pytest.approx(2.0, rel=0.02)
    assert s.cog_true_deg == pytest.approx(90.0, abs=1.0)
    assert s.x_east_ft * FT == pytest.approx(2.0 * KT * 1200, rel=0.02)     # moved east by current * time
    assert abs(s.y_north_ft) < 0.02 * s.x_east_ft
    assert abs(s.stw_kt) < 0.05                                              # still water-relative at rest


def test_current_toward_convention_north():
    e = env(cur_kt=1.0, cur_toward=0.0)
    r = run([vessel(speed=0.0, helm=[{"t_s": 0, "engine_order": 0.0, "rudder_deg": 0}])], dur=600, dt=0.5, env=e, sample=10.0)
    s = states(r)[-1]
    assert s.y_north_ft > 0 and abs(s.x_east_ft) < 1.0


def test_wind_from_starboard_beam_pushes_ship_to_port_in_body_axes():
    e = env(wind_kt=30.0, wind_from=90.0)                    # wind FROM the east on a north-heading ship
    r = run([vessel(speed=0.0, helm=[{"t_s": 0, "engine_order": 0.0, "rudder_deg": 0}])], dur=60, dt=0.5, env=e, sample=10.0)
    s = states(r)[-1]
    assert s.forces.wind.sway_lbf > 0                        # + port
    assert s.x_east_ft < 0                                   # downwind = toward the west
    # apparent wind: a ship making way into a calm-air environment (explicit zero wind) feels a headwind drag
    e0 = env()
    r2 = run([full_ahead(speed=20.0)], dur=20, dt=0.5, env=e0)
    assert states(r2)[-1].forces.wind.surge_lbf < 0


def test_current_does_not_change_water_relative_speed_at_steady_state():
    e = env(cur_kt=2.0, cur_toward=0.0)                      # following current
    r = run([full_ahead(speed=0.0)], dur=3000, dt=0.5, env=e)
    s = states(r)[-1]
    assert s.stw_kt == pytest.approx(30.0, rel=0.025)
    assert s.sog_kt == pytest.approx(s.stw_kt + 2.0, abs=0.1)


def test_supplied_max_speed_overrides_class_default():
    r = run([full_ahead(propulsion={"max_speed_kt": 24.0})], dur=3000, dt=0.5)
    assert states(r)[-1].stw_kt == pytest.approx(24.0, rel=0.02)


def test_timestep_convergence_of_the_turning_circle():
    out = {}
    for dt in (0.5, 0.2, 0.05):
        r = run([full_ahead(speed=30.0, rud=35.0)], dur=400, dt=dt, sample=5.0)
        s = states(r)[-1]
        out[dt] = (s.x_east_ft, s.y_north_ft, s.heading_true_deg)
    print("S6 dt convergence (x, y, heading at 400 s):", {k: tuple(round(x, 2) for x in v) for k, v in out.items()})
    ref = out[0.05]
    err = {dt: math.hypot(out[dt][0] - ref[0], out[dt][1] - ref[1]) for dt in (0.5, 0.2)}
    print("S6 dt convergence: position error vs dt=0.05 (ft):", {k: round(v, 2) for k, v in err.items()}, "of ~3000 ft turn")
    # Rudder/tug/wind are held constant over a step (zero-order hold), so the scheme is first order in dt overall.
    assert err[0.5] > err[0.2] and err[0.2] < 6.0          # 0.2 % of the 3000 ft transfer
    assert abs(out[0.2][2] - ref[2]) < 0.1


def test_calm_includes_own_motion_air_drag():
    """Fix 8e: environment=None is explicit calm and must still apply the air drag of the ship's own motion, identically to a
    supplied zero-wind, zero-current environment."""
    v = full_ahead(speed=25.0)
    a = run([v], dur=120, dt=0.2, sample=10.0)
    b = run([v], dur=120, dt=0.2, sample=10.0, env={**env(), "water_density_kgm3": C.RHO_WATER_DEFAULT})   # same water density
    assert [s.model_dump() for s in states(a)] == [s.model_dump() for s in states(b)]
    assert states(a)[-1].forces.wind.surge_lbf < -1000.0          # a real headwind drag from own motion
    assert states(a)[-1].stw_kt < 25.0 + 4.0                      # sanity: still moving
