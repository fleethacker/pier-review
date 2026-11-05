"""Independent P3 mechanics benchmarks derived from Newton's law and energy balance.

All geometry, springs and damping below are synthetic analytical fixtures, not
vessel coefficients. No seed catalog or existing dynamics tests supply expected
answers. These checks establish numerical consistency, not vessel qualification.
"""

import math
from datetime import UTC, datetime

import pytest

from mooring import refdata, scenarios
from mooring.berthing.simulator import initial_model
from mooring.core.schemas import (
    Berth, EnvironmentSnapshot, LineSpec, MooringConfig, MooringLine, Scenario,
    ShipClass, ShipState, SimLineEventMessage, SimTugCommandMessage, TugAssignment,
    TugSpec,
)
from mooring.loads import compute_loads
from mooring.mechanics.dynamics import BodyParams, simulate
from mooring.mechanics.equilibrium import build_system
from mooring.mechanics.pose import Pose
from mooring.mechanics.streaming import Integrator


NOW = datetime(2026, 1, 1, tzinfo=UTC)
SYNTHETIC = {"source": "P3 analytical benchmark fixture", "confidence": "synthetic"}


def _model(monkeypatch, *, side="starboard", push_x=25.0, wind_kt=0.0,
           with_line=False, dt=0.05):
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
        # Deck is at MLLW; the pier attachment is 1.5 ft above it. The
        # centerline lead is at the same height, making this a horizontal spring.
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
    # With L0=10 ft and T=1e6 * strain/5, k=20,000 lbf/ft exactly.
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
                         dt=dt, duration=30)


@pytest.mark.parametrize("side", ["starboard", "port"])
@pytest.mark.parametrize("push_x", [-25.0, 25.0], ids=["aft", "forward"])
def test_single_tug_force_and_moment_from_cross_product(monkeypatch, side, push_x):
    """A water-side push is -berth-y; N=rx*Fy, invariant under frame rotation."""
    model = _model(monkeypatch, side=side, push_x=push_x)
    force = 8000.0
    direction = 90 if side == "starboard" else 270
    model.schedule(SimTugCommandMessage(type="tug_command", t_s=0,
                                        tug_id="P3-TUG", force_lbf=force,
                                        direction_rel_deg=direction))
    model.apply_pending()
    # At five simulated seconds the documented demonstration slew is complete.
    # Evaluate the force at the unchanged pose to isolate wrench bookkeeping.
    state = model.integrator.state
    fx, fy, yaw = model.forces(5, state)
    c, s = math.cos(state[2]), math.sin(state[2])
    berth_force = (c * fx - s * fy, s * fx + c * fy)
    berth_arm_x = push_x if side == "starboard" else -push_x
    expected = (0.0, -force, -force * berth_arm_x)
    assert (*berth_force, yaw) == pytest.approx(expected, abs=1e-8)

    # Independent static path must implement the same physical cross product.
    system = build_system(model.ship, model.berth, model.cfg, {}, model.env,
                          loading="full_load", lines_wet=False,
                          tugs=[TugAssignment(tug_id="P3-TUG", push_point_id="PUSH",
                                              mode="push", force_lbf=force)])
    assert system.total_wrench(Pose()).vec() == pytest.approx(expected, abs=1e-8)
    assert not model.system.lines and not model.system.fenders


@pytest.mark.parametrize("v0", [-2.0, 2.0])
def test_free_sway_decay_matches_exponential(v0):
    """M dv/dt=-D v gives v=v0 exp(-Dt/M), y-y0=M(v0-v)/D."""
    mass, added_mass, damping = 12.0, 8.0, 5.0
    params = BodyParams(mass, 100, added_sway=added_mass,
                        damping_lin=(0, damping, 0))
    integrator = Integrator(params, lambda t, state: (0, 0, 0),
                            (7, 3, 0, 0, v0, 0), 0.025)
    rate = damping / (mass + added_mass)
    for t in (1.0, 3.0, 12.0):
        integrator.advance(t)
        velocity = v0 * math.exp(-rate * t)
        expected = (7, 3 + (v0 - velocity) / rate, 0, 0, velocity, 0)
        assert integrator.state == pytest.approx(expected, rel=1e-9, abs=1e-10)


def test_rk4_smooth_oscillator_converges_at_fourth_order():
    """For M=K=2, y''=-y: y(2)=cos(2), v(2)=-sin(2); E(h)/E(h/2)≈16."""
    params = BodyParams(2, 10)
    errors = []
    for dt in (0.2, 0.1, 0.05):
        trace = simulate(params, lambda t, state: (0, -2 * state[1], 0),
                         (0, 1, 0, 0, 0, 0), 2, dt, sample_dt=2)
        state = trace.states[-1]
        errors.append(math.hypot(state[1] - math.cos(2), state[4] + math.sin(2)))
    assert errors[0] > errors[1] > errors[2] > 1e-10
    for coarse, fine in zip(errors, errors[1:]):
        assert coarse / fine == pytest.approx(16, rel=0.03)


def test_constant_environment_initial_acceleration_and_damped_drift(monkeypatch):
    """At rest a=F/M; then M du/dt=F-Du gives u=(F/D)(1-exp(-Dt/M))."""
    model = _model(monkeypatch, wind_kt=20, dt=0.01)
    # This benchmark tests load-to-motion coupling, not UFC coefficients: take
    # the prescribed headwind force from the public load calculator separately.
    force = compute_loads(model.ship, "full_load", 90, model.env, 100).total.fx_lbf
    mass = model.params.mass_slug + model.params.added_surge
    damping = model.params.damping_lin[0]
    assert force < 0 and mass > 0 and damping > 0
    assert not model.system.lines and not model.system.fenders
    assert not model.ramps
    dt = 0.0001
    model.advance(dt)
    assert model.integrator.state[3] / dt == pytest.approx(force / mass, rel=1e-5)
    model.advance(5)
    velocity = force / damping * (1 - math.exp(-damping * 5 / mass))
    displacement = force / damping * (5 - mass / damping * (1 - math.exp(-damping * 5 / mass)))
    assert model.integrator.state == pytest.approx(
        (200 + displacement, 20, 0, velocity, 0, 0), rel=1e-9, abs=1e-9)
    assert model.validity().state == "limited"


def test_taut_line_energy_balance_against_damped_spring(monkeypatch):
    """U=K e²/2, T=K e and M e''+D e'+K e=0 until the line goes slack."""
    dt, end, spring, rest_length, extension0 = 0.05, 8.0, 20_000.0, 10.0, 10.0
    model = _model(monkeypatch, with_line=True, dt=dt)
    mass = model.params.mass_slug + model.params.added_sway
    damping = model.params.damping_lin[1]
    initial_energy = spring * extension0**2 / 2
    model.schedule(SimLineEventMessage(type="line_event", t_s=0,
                                       line_number=1, event="secured"))
    model.apply_pending()
    alpha = damping / (2 * mass)
    omega = math.sqrt(spring / mass - alpha**2)
    observed = []

    def check_energy(t0, s0, t, state):
        extension = extension0 * math.exp(-alpha*t) * (
            math.cos(omega*t) + alpha/omega * math.sin(omega*t))
        velocity = -extension0 * spring / (mass*omega) * math.exp(-alpha*t) * math.sin(omega*t)
        analytic_energy = mass * velocity**2 / 2 + spring * extension**2 / 2
        assert state[1] - rest_length == pytest.approx(extension, rel=1e-8)
        assert state[4] == pytest.approx(velocity, rel=1e-8, abs=1e-10)
        tension = model.system.line_tensions(model.body.pose(state))[0][2]
        assert tension == pytest.approx(spring * extension, rel=1e-8)
        assert tension > 0  # Exercise a genuinely taut line throughout the run.
        diag = model.diagnostics(state)
        assert diag.final_energy_ftlbf == pytest.approx(analytic_energy, rel=1e-8)
        # Trapezoidal integration of damping power is second-order. Bound the
        # residual relative to energy using the shorter damping/spring timescale.
        tau = min(mass/damping, math.sqrt(mass/spring))
        residual_bound = 2 * (dt/tau)**2 * initial_energy
        residual = analytic_energy - initial_energy + diag.dissipated_energy_ftlbf
        assert abs(residual) < residual_bound
        assert abs(diag.energy_residual_ftlbf) < residual_bound
        observed.append(diag)

    model.advance(end, observe=check_energy)
    assert len(observed) >= int(end/dt)
    final = observed[-1]
    assert final.initial_energy_ftlbf == 0
    assert final.line_event_energy_ftlbf == pytest.approx(initial_energy, rel=1e-12)
    assert final.applied_work_ftlbf == 0
    assert final.dissipated_energy_ftlbf > 0
    assert final.final_energy_ftlbf < initial_energy
