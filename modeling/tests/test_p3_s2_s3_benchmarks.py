"""Independent P3 benchmarks for S2 (simulation-time forcing) and S3 (tug geometry, vertical).

Expected values are derived from vector algebra, the documented frame conventions
(docs/MOTION_FRAME_DESIGN.md: berth +x along pier, +y off-pier, ship surge forward / sway PORT,
yaw CCW from berth +x; docs/BERTHING_SIMULATION.md S2) and closed-form ODE solutions, never by
re-using implementation formulas. Synthetic fixtures; numerical consistency only, not vessel qualification.
"""

import math
from datetime import UTC, datetime

import pytest

from mooring import refdata, scenarios
from mooring.berthing import simulator as sim
from mooring.berthing.forcing import ForcingSeries, apparent_wind
from mooring.berthing.s3_tug_geometry import (
    PushPointGeom, TugCommand, TugGeometryError, TugLimits, bind_push_point, clamp_force,
    slew_force, target_signed, total_wrench, tug_contact)
from mooring.berthing.s3_vertical import vertical_state
from mooring.berthing.simulator import initial_model
from mooring.core.schemas import (
    Berth, BerthingSimRequest, EnvironmentSnapshot, ForcingSpec, LineSpec, MooringConfig,
    MooringLine, Scenario, ShipClass, ShipState, SimLineEventMessage, SimTugCommandMessage, TugSpec)
from mooring.fixtures import calm_env
from mooring.loads import compute_loads
from modeling_api.sim_sessions import Session

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SYNTHETIC = {"source": "P3 analytical benchmark fixture", "confidence": "synthetic"}
KT = 1.6878098571  # ft/s per knot


def _model(monkeypatch, *, side="starboard", push_x=25.0, wind_kt=0.0,
           with_line=False, dt=0.05, duration=30, forcing=None):
    """Inject references and a fixed environment; never touch stores or live feeds."""
    water_side = "port" if side == "starboard" else "starboard"
    ship = ShipClass(
        class_id="P3-SYNTHETIC", name="Analytical fixture", hull_type="DDG",
        loa_ft=100, lwl_ft=100, beam_ft=20, block_coefficient=0.5,
        loading_conditions=[dict(name="full_load", displacement_lt=1000,
                                 draft_fwd_ft=10, draft_aft_ft=10, freeboard_ft=10)],
        wind_area_lateral_ft2=1000, hull_wind_area_lateral_ft2=500,
        wind_area_frontal_ft2=200, superstructure_height_ft=20,
        wind_drag_class="typical", mst_class="II", provenance=SYNTHETIC,
        fittings=[dict(fitting_id="LEAD", kind="bitt", x_ft=0, y_ft=0,
                       z_ft=1.5, side="centerline", swl_lbf=1_000_000)],
        push_points=[dict(push_point_id="PUSH", x_ft=push_x, side=water_side,
                          max_force_lbf=20_000)],
    )
    berth = Berth(
        berth_id="P3-BERTH", name="Analytical berth", face_bearing_true_deg=90,
        origin_lat=0, origin_lon=0, face_length_ft=500, deck_height_mllw_ft=0,
        depth_profile=[dict(x_ft=0, depth_mllw_ft=100)], fenders=[],
        fittings=[dict(fitting_id="ANCHOR", kind="bollard_horn", x_ft=200,
                       y_ft=0, capacity_nominal_lbf=1_000_000)],
        env_station_ids=dict(wind="unused", current="unused", water_level="unused"),
        provenance=SYNTHETIC,
    )
    line = LineSpec(
        spec_id="P3-SPRING", material="polyester", construction="double_braid",
        size_circ_in=1, mbs_lbf=1_000_000, load_elongation=[(0, 0), (1, 5)],
        wet_strength_factor=1, provenance=SYNTHETIC,
    )
    lines = [MooringLine(line_number=1, spec_id=line.spec_id, ship_fitting_id="LEAD",
                         pier_fitting_id="ANCHOR", paid_out_unstretched_length_ft=10)] if with_line else []
    cfg = MooringConfig(side_to=side, ship_x_ft=200, standoff_ft=10, lines=lines)
    scenario = Scenario(
        scenario_id="P3-SCENARIO", created_at_utc=NOW, name="Analytical scenario",
        ship_class_id=ship.class_id, berth_id=berth.berth_id, side_to=side,
        env_source=dict(mode="scenario", env_scenario_id="P3-ENV"), config=cfg,
    )
    heading = 90 if side == "starboard" else 270
    environment = EnvironmentSnapshot(
        valid_at_utc=NOW, source="scenario", wind_speed_kt=wind_kt,
        wind_gust_kt=wind_kt, wind_from_true_deg=heading,
        current_speed_kt=0, current_set_true_deg=0, water_level_mllw_ft=0,
    )
    tug = TugSpec(tug_id="P3-TUG", name="Synthetic tug", propulsion="asd",
                  power_hp=100, bollard_pull_ahead_lbf=20_000,
                  bollard_pull_astern_lbf=20_000, provenance=SYNTHETIC)
    monkeypatch.setattr(refdata, "ship", lambda _: ship)
    monkeypatch.setattr(refdata, "berth", lambda _: berth)
    monkeypatch.setattr(refdata, "line", lambda _: line)
    monkeypatch.setattr(refdata, "tugs", lambda: [tug])
    monkeypatch.setattr(scenarios, "get", lambda _: scenario)
    monkeypatch.setattr(scenarios, "environment_for", lambda _: environment)
    return initial_model(scenario.scenario_id,
                         ShipState(x_ft=200, y_ft=20, heading_true_deg=heading),
                         dt=dt, duration=duration, forcing=forcing)


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def _unit(heading_deg):
    """Compass unit vector (east, north) as a complex number."""
    h = math.radians(heading_deg)
    return complex(math.sin(h), math.cos(h))


def _wrap(deg):
    return (deg + 180) % 360 - 180


# ------------------------------------------------------------ S3a tug geometry

@pytest.mark.parametrize("yaw_deg", [0, 30, -50, 135])
@pytest.mark.parametrize("x_pp", [-40.0, 25.0])
def test_tug_contact_rotation_and_moment(yaw_deg, x_pp):
    """Ship-axes F=(0,fy); berth vector = plain CCW rotation by yaw; Mz = x*fy (right-hand rule)."""
    pp = PushPointGeom("P", x_pp, "port", 50_000)
    limits = TugLimits(-50_000, 50_000, 1000)
    f = -7000.0  # toward starboard
    psi = math.radians(yaw_deg)
    out = tug_contact("T", pp, f, psi, limits)
    rotated = complex(0, f) * complex(math.cos(psi), math.sin(psi))
    assert out.wrench_ship == pytest.approx((0, f, x_pp * f), abs=1e-9)
    assert out.force_berth_lbf == pytest.approx((rotated.real, rotated.imag), abs=1e-9)
    assert math.hypot(*out.force_berth_lbf) == pytest.approx(abs(f))
    assert out.tug_position_ft is None and out.position_status == "not_modeled"
    # A starboard-ward push ahead of midships turns the bow to starboard (clockwise, Mz<0).
    assert (out.wrench_ship[2] < 0) == (x_pp > 0)


def test_total_wrench_is_vector_sum_of_two_tugs():
    fwd = PushPointGeom("F", 30.0, "port", 1e5)
    aft = PushPointGeom("A", -30.0, "port", 1e5)
    lim = TugLimits(-1e5, 1e5, 1e3)
    a, b = tug_contact("T1", fwd, -4000, 0.2, lim), tug_contact("T2", aft, -4000, 0.2, lim)
    assert total_wrench([a, b]) == pytest.approx((0, -8000, 0), abs=1e-9)  # pure sway, no couple
    c = tug_contact("T2", aft, -1000, 0.2, lim)
    assert total_wrench([a, c])[2] == pytest.approx(30 * -4000 + -30 * -1000)


def test_tug_clamp_limits_push_and_pull_and_pier_side_rejected():
    pp = PushPointGeom("P", 10.0, "port", 8000)
    tug = TugSpec(tug_id="T", name="t", propulsion="asd", power_hp=1, bollard_pull_ahead_lbf=12_000,
                  bollard_pull_astern_lbf=5_000, provenance=SYNTHETIC)
    lim = TugLimits.from_specs(tug, pp, slew_s=5)
    # Port-side tug pushes toward starboard (negative sway): min(ahead 12000, hull 8000) = 8000.
    # Pulling toward port is limited by astern bollard pull 5000.
    assert (lim.lo_lbf, lim.hi_lbf) == (-8000, 5000)
    assert lim.slew_lbf_per_s == pytest.approx(8000 / 5)
    assert clamp_force(-9000, lim) == (-8000, True)
    assert clamp_force(6000, lim) == (5000, True)
    assert clamp_force(-3000, lim) == (-3000, False)
    out = tug_contact("T", pp, -9000, 0.0, lim, requested=-9000)
    assert out.clamped and out.signed_force_lbf == -8000 and out.mode == "push"
    assert out.wrench_ship[2] == pytest.approx(10 * -8000)
    mirror = TugLimits.from_specs(tug, PushPointGeom("S", 10.0, "starboard", 8000), slew_s=5)
    assert (mirror.lo_lbf, mirror.hi_lbf) == (-5000, 8000)
    cmd = TugCommand("T", "P", 100.0, 90)
    assert target_signed(cmd) == -100.0 and target_signed(TugCommand("T", "P", 100.0, 270)) == 100.0
    with pytest.raises(TugGeometryError):
        bind_push_point(cmd, [PushPointGeom("P", 0, "starboard", 1)], side_to="starboard")


def test_tug_slew_is_rate_limited_linear():
    lim = TugLimits(-10_000, 10_000, 2_000)
    f = 0.0
    for _ in range(10):
        f = slew_force(f, -10_000, lim, 0.1)  # 1 s at 2000 lbf/s
    assert f == pytest.approx(-2000)
    assert slew_force(f, -10_000, lim, 100) == -10_000  # cannot pass the target
    assert slew_force(-10_000, 20_000, lim, 0.5) == pytest.approx(-9000)  # target clamped to +10000


@pytest.mark.parametrize("side", ["starboard", "port"])
@pytest.mark.parametrize("yaw", [0.35, -0.8])
def test_simulator_tug_wrench_at_nonzero_yaw(monkeypatch, side, yaw):
    """Hull force stays body-fixed (0, fy) and the moment is x*fy, whatever the yaw."""
    model = _model(monkeypatch, side=side, push_x=25.0)
    force = 8000.0
    direction = 90 if side == "starboard" else 270
    model.schedule(SimTugCommandMessage(type="tug_command", t_s=0, tug_id="P3-TUG",
                                        force_lbf=force, direction_rel_deg=direction))
    model.apply_pending()
    base = model.integrator.state
    fx, fy, mz = model.forces(5.0, (base[0], base[1], yaw, 0.0, 0.0, 0.0))
    fy_expected = -force if direction == 90 else force
    assert (fx, fy) == pytest.approx((0.0, fy_expected), abs=1e-8)
    assert mz == pytest.approx(25.0 * fy_expected, abs=1e-8)


def test_simulator_tug_slew_is_rated_linear_ramp_then_hold(monkeypatch):
    """Rating 20000 lbf over 5 s => 4000 lbf/s; an 8000 lbf command reaches target at 2 s and holds."""
    model = _model(monkeypatch)
    model.schedule(SimTugCommandMessage(type="tug_command", t_s=0, tug_id="P3-TUG",
                                        force_lbf=8000, direction_rel_deg=90))
    model.apply_pending()
    assert model.tug_force("P3-TUG", 0.5) == pytest.approx(-2000)
    assert model.tug_force("P3-TUG", 1.0) == pytest.approx(-4000)
    assert model.tug_force("P3-TUG", 2.0) == pytest.approx(-8000)
    assert model.tug_force("P3-TUG", 9.0) == pytest.approx(-8000)


@pytest.mark.parametrize("force,ok", [(20_000, True), (20_001, False)])
def test_simulator_tug_clamp_rejects_over_rating(monkeypatch, force, ok):
    model = _model(monkeypatch)
    msg = SimTugCommandMessage(type="tug_command", t_s=0, tug_id="P3-TUG", force_lbf=force,
                               direction_rel_deg=90)
    if ok:
        model.schedule(msg)
    else:
        with pytest.raises(ValueError):
            model.schedule(msg)


# ------------------------------------------------------------ S3b vertical / tide

@pytest.mark.parametrize("phase", [0.0, math.pi / 2, 2.2])
def test_tide_heave_tracks_sinusoid_amplitude_and_phase(phase):
    amp, period, base_level = 3.0, 400.0, 1.25
    env = calm_env().model_copy(update={"water_level_mllw_ft": base_level})
    spec = ForcingSpec(kind="steady", tide_amplitude_ft=amp, tide_period_s=period, tide_phase_rad=phase)
    series = ForcingSeries(spec, env, 1000)
    omega = 2 * math.pi / period
    for t in (0, 33, 100, 150, 200, 301.5, 400, 777):
        level = base_level + amp * (math.sin(omega * t + phase) - math.sin(phase))
        got = series.at(t)[0].water_level_mllw_ft
        assert got == pytest.approx(level, abs=1e-9)
        v = vertical_state(got)
        assert v.heave_mllw_ft == pytest.approx(level, abs=1e-9) and v.heave_dof == "prescribed"
        assert v.roll_dof == v.pitch_dof == "not_simulated" and v.roll_deg is None
    levels = [series.at(t * period / 400)[0].water_level_mllw_ft for t in range(401)]
    assert max(levels) - min(levels) == pytest.approx(2 * amp, rel=2e-3) or phase not in (0.0,)
    assert levels[400] == pytest.approx(levels[0], abs=1e-9)  # periodic
    assert series.at(0)[0].water_level_mllw_ft == base_level  # zero tide at t=0


def test_vertical_state_missing_and_offset():
    assert vertical_state(None).heave_dof == "not_simulated"
    assert vertical_state(float("nan")).heave_mllw_ft is None
    assert vertical_state(2.0, waterline_offset_ft=-0.5).heave_mllw_ft == 1.5


# ------------------------------------------------------------ S2 wind

@pytest.mark.parametrize("heading", [0, 37, 90, 181, 299])
@pytest.mark.parametrize("wind_from", [0, 45, 270])
def test_still_ship_relative_wind_equals_true_wind(heading, wind_from):
    env = calm_env().model_copy(update={"wind_speed_kt": 17, "wind_gust_kt": 23, "wind_from_true_deg": wind_from})
    app = apparent_wind(env, heading, 0.0, 0.0)
    assert app.wind_speed_kt == pytest.approx(17, abs=1e-9)
    assert app.wind_gust_kt == pytest.approx(23, abs=1e-9)
    assert _wrap(app.wind_from_true_deg - wind_from) == pytest.approx(0, abs=1e-7)


@pytest.mark.parametrize("heading", [0, 40, 200])
def test_still_air_apparent_wind_is_ship_velocity_reversed(heading):
    """No true wind: the air appears to blow from where the ship is heading."""
    env = calm_env().model_copy(update={"wind_speed_kt": 0, "wind_gust_kt": 0, "wind_from_true_deg": 123})
    app = apparent_wind(env, heading, 6 * KT, 0.0)
    assert app.wind_speed_kt == pytest.approx(6, abs=1e-9)
    assert _wrap(app.wind_from_true_deg - heading) == pytest.approx(0, abs=1e-6)


def test_moving_ship_apparent_wind_is_vector_difference():
    heading, u_kt, v_kt = 40.0, 6.0, -2.0  # v<0 is to starboard (sway is +port)
    env = calm_env().model_copy(update={"wind_speed_kt": 12, "wind_gust_kt": 12, "wind_from_true_deg": 250})
    fwd = _unit(heading)
    port = fwd * 1j  # CCW quarter turn on (east, north) is to port
    ship = u_kt * fwd + v_kt * port
    air = -12 * _unit(250)  # air moves toward the opposite of its "from" bearing
    rel = air - ship
    app = apparent_wind(env, heading, u_kt * KT, v_kt * KT)
    assert app.wind_speed_kt == pytest.approx(abs(rel), abs=1e-9)
    from_dir = math.degrees(math.atan2(-rel.real, -rel.imag)) % 360
    assert _wrap(app.wind_from_true_deg - from_dir) == pytest.approx(0, abs=1e-7)
    # Running into a head wind adds the speeds.
    head = apparent_wind(env.model_copy(update={"wind_from_true_deg": 40}), 40, 6 * KT, 0)
    assert head.wind_speed_kt == pytest.approx(18, abs=1e-9)
    # Air moving 12 kt toward 40, ship 6 kt toward 40: relative 6 kt from 220.
    tail = apparent_wind(env.model_copy(update={"wind_from_true_deg": 220}), 40, 6 * KT, 0)
    assert tail.wind_speed_kt == pytest.approx(6, abs=1e-9)
    assert _wrap(tail.wind_from_true_deg - 220) == pytest.approx(0, abs=1e-6)


def test_model_applies_apparent_wind_from_yaw_and_velocity(monkeypatch):
    """Yaw is CCW from berth +x (bearing 90): heading = 90 - yaw. Calm air, ship surging 5 kt."""
    model = _model(monkeypatch, forcing=ForcingSpec(kind="steady", vessel_relative_wind=True), duration=10)
    yaw = 0.3
    model.set_env(0.0, (200, 20, yaw, 5 * KT, 0, 0))
    assert model.system.env.wind_speed_kt == pytest.approx(5, abs=1e-9)
    assert _wrap(model.system.env.wind_from_true_deg - (90 - math.degrees(yaw))) == pytest.approx(0, abs=1e-6)


# ------------------------------------------------------------ S2 ramp convergence

def test_ramp_forcing_timestep_convergence_to_closed_form(monkeypatch):
    """Surge: M u' = c V(t)^2 - D u with V=a t; exact u = q(t^2/r - 2t/r^2 + 2/r^3) - 2q e^{-rt}/r^3."""
    T, V_end = 4.0, 40.0
    forcing = ForcingSpec(kind="ramp", ramp_start_s=0,
                          target=dict(t_s=T, wind_speed_kt=V_end, wind_gust_kt=V_end))
    probe = _model(monkeypatch, wind_kt=10)
    f10 = compute_loads(probe.ship, "full_load", 90, probe.env, 100).total.fx_lbf
    e20 = probe.env.model_copy(update={"wind_speed_kt": 20, "wind_gust_kt": 20})
    f20 = compute_loads(probe.ship, "full_load", 90, e20, 100).total.fx_lbf
    assert f20 / f10 == pytest.approx(4.0, rel=1e-9)  # quadratic in speed
    c = f10 / 10**2
    errors = {}
    for dt in (1.0, 0.5, 0.25):
        model = _model(monkeypatch, wind_kt=0, dt=dt, duration=T, forcing=forcing)
        mass = model.params.mass_slug + model.params.added_surge
        r, a = model.params.damping_lin[0] / mass, V_end / T
        q = c * a**2 / mass
        exact = q * (T**2 / r - 2 * T / r**2 + 2 / r**3) - 2 * q * math.exp(-r * T) / r**3
        model.advance(T)
        errors[dt] = abs(model.integrator.state[3] - exact) / abs(exact)
    # Forcing is smooth and evaluated at RK4 stage times, so the global error is 4th order (ratio 16).
    assert errors[1.0] > errors[0.5] > errors[0.25] > 1e-14
    assert errors[1.0] / errors[0.5] == pytest.approx(16, rel=0.1)
    assert errors[0.5] / errors[0.25] == pytest.approx(16, rel=0.1)


def test_ramp_forcing_stage_time_resolution_is_not_stale(monkeypatch):
    forcing = ForcingSpec(kind="ramp", ramp_start_s=0, target=dict(t_s=4, wind_speed_kt=40, wind_gust_kt=40))
    model = _model(monkeypatch, wind_kt=0, duration=4, forcing=forcing)
    for t in (0.0, 0.7, 2.0, 3.3, 4.0):
        model.set_env(t, model.integrator.state)
        assert model.system.env.wind_speed_kt == pytest.approx(40 * t / 4, abs=1e-12)


# ------------------------------------------------------------ S2 batch / interactive / replay

TUGS = [dict(t_s=1.0, tug_id="P3-TUG", force_lbf=6000, direction_rel_deg=90)]
LINES = [dict(t_s=0.0, line_number=1, event="secured")]


def _frames_batch(job, forcing, duration):
    req = BerthingSimRequest(scenario_id="P3-SCENARIO",
                             initial_state=ShipState(x_ft=200, y_ft=20, heading_true_deg=90),
                             duration_s=duration, dt_s=0.05, sample_interval_s=0.25, forcing=forcing,
                             tug_commands=TUGS, line_events=LINES)
    sim.simulate_berthing(req, job, "/api/v1")
    return sim.SERIES[job].frames


def test_batch_equals_interactive_under_forcing(monkeypatch):
    _model(monkeypatch, with_line=True)
    forcing = ForcingSpec(kind="ramp", ramp_start_s=0, target=dict(t_s=4, wind_speed_kt=40, wind_gust_kt=40),
                          tide_amplitude_ft=1.5, tide_period_s=12)
    frames = _frames_batch("p3-b", forcing, 5)
    clock = Clock()
    model = initial_model("P3-SCENARIO", ShipState(x_ft=200, y_ft=20, heading_true_deg=90),
                          dt=0.05, duration=5, forcing=forcing)
    session = Session(model, clock=clock)
    session.attach("c")
    session.receive("c", SimTugCommandMessage(type="tug_command", t_s=1, tug_id="P3-TUG",
                                              force_lbf=6000, direction_rel_deg=90))
    session.receive("c", SimLineEventMessage(type="line_event", t_s=0, line_number=1, event="secured"))
    for i in range(1, 21):
        clock.now = i * 0.25
        session.tick()
        f = session.latest
        assert f.t_s == pytest.approx(frames[i].t_s)
        assert f.pose.model_dump() == pytest.approx(frames[i].pose.model_dump(), abs=1e-9)
        # Water level at the frame time equals the analytic tide 1.5 sin(2 pi t / 12).
        assert f.environment.water.level_mllw_ft == pytest.approx(1.5 * math.sin(2 * math.pi * f.t_s / 12), abs=1e-9)
        assert f.environment.water.level_mllw_ft == pytest.approx(frames[i].environment.water.level_mllw_ft, abs=1e-12)
        assert [x.tension_lbf for x in f.lines] == pytest.approx([x.tension_lbf for x in frames[i].lines], abs=1e-6)


def test_replay_series_matches_equivalent_ramp(monkeypatch):
    """Piecewise-linear replay of the ramp's own knots must reproduce the ramp trajectory."""
    _model(monkeypatch, with_line=True)
    ramp = ForcingSpec(kind="ramp", ramp_start_s=0, target=dict(t_s=4, wind_speed_kt=40, wind_gust_kt=40))
    replay = ForcingSpec(kind="replay", samples=[
        dict(t_s=0, wind_speed_kt=0, wind_gust_kt=0, wind_from_true_deg=90),
        dict(t_s=4, wind_speed_kt=40, wind_gust_kt=40, wind_from_true_deg=90),
        dict(t_s=5, wind_speed_kt=40, wind_gust_kt=40, wind_from_true_deg=90)])
    a = _frames_batch("p3-ramp", ramp, 5)
    b = _frames_batch("p3-replay", replay, 5)
    steady = _frames_batch("p3-steady", ForcingSpec(kind="steady"), 5)
    assert len(a) == len(b)
    for fa, fb in zip(a, b):
        assert fa.pose.model_dump() == pytest.approx(fb.pose.model_dump(), abs=1e-9)
        assert fa.environment.wind.speed_kt == pytest.approx(fb.environment.wind.speed_kt, abs=1e-9)
    # The forcing must actually matter, or this equivalence is vacuous.
    assert a[-1].pose.model_dump() != pytest.approx(steady[-1].pose.model_dump(), abs=1e-12)
    assert a[-1].forcing_revision != b[-1].forcing_revision


# ------------------------------------------------------------ S2 tide vs paid-out length

def test_water_level_change_keeps_paid_out_length_and_follows_vertical_geometry(monkeypatch):
    period, amp = 40.0, 3.0
    forcing = ForcingSpec(kind="steady", tide_amplitude_ft=amp, tide_period_s=period)
    model = _model(monkeypatch, with_line=True, duration=40, forcing=forcing)
    model.schedule(SimLineEventMessage(type="line_event", t_s=0, line_number=1, event="secured"))
    model.apply_pending()
    rec = model.all_lines[1]
    state = model.integrator.state
    pose = model.body.pose(state)

    def length(t):
        model.set_env(t, state)
        return model.system.line_state(rec, pose).length_ft

    l0, lu, ld = length(0), length(period / 4), length(3 * period / 4)  # level 0, +amp, -amp
    # L^2 = H^2 + (dz0 - d)^2  =>  L^2(+d) + L^2(-d) - 2 L^2(0) = 2 d^2, for any H and dz0.
    assert lu**2 + ld**2 - 2 * l0**2 == pytest.approx(2 * amp**2, rel=1e-9)
    assert lu >= l0
    for t in (0, period / 4, period / 2, period):
        length(t)
        assert rec.ln.paid_out_unstretched_length_ft == 10.0
    # Tension is a pure function of geometry: levels at t=0 and t=period/2 are both zero.
    model.set_env(0, state)
    t0 = model.system.line_tensions(pose)[0][2]
    model.set_env(period / 2, state)
    t1 = model.system.line_tensions(pose)[0][2]
    assert t0 == pytest.approx(t1, rel=1e-9)
