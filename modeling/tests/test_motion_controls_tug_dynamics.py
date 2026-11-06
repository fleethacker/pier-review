"""Coupled synthetic tug checks: connections, energy, controls and snapshot fidelity."""
import math
import pytest

from test_motion_controls_physics import model  # noqa: F401 - shared synthetic fixture
from mooring.berthing import rich
from mooring.berthing.simulator import BerthingModel
from mooring.berthing.tug_dynamics import spring, rotate, synthetic_tug_dynamics_config
from mooring.core.schemas import SimTugCommandMessage
from mooring.core.schemas.motion_controls import SimTugMotionCommandMessage


@pytest.fixture
def coupled(model):
    tug,point,_ = model.anchors["T1"]
    config = model.controls_config.model_copy(deep=True)
    config.tug_dynamics = [synthetic_tug_dynamics_config(tug,model.ship,point,model.initial,model.berth.face_bearing_true_deg)]
    return BerthingModel(model.sc,model.initial,model.env,controls=config,tug_ids=["T1"],duration=60,dt=.025)


def order(model,mode="push",vy=-.5):
    return SimTugMotionCommandMessage(type="tug_motion_command",t_s=model.t,tug_id="T1",
        mode=mode,target_velocity_x_fps=0,target_velocity_y_fps=vy,target_heading_true_deg=180,tow_length_ft=10)


def test_spring_energy_and_passivity_with_unilateral_capacity():
    assert spring(-1,10,100,20,150) == (0,0,0)
    assert spring(1,0,100,20,150) == (100,50,0)
    assert spring(2,0,100,20,150) == (150,187.5,0)
    for displacement in (.1,1,2):
        for speed in (-20,-1,0,1,20):
            force,energy,dissipation = spring(displacement,speed,100,20,150)
            assert 0 <= force <= 150 and energy >= 0 and dissipation >= 0
            assert force*speed-dissipation == pytest.approx(min(150,100*displacement)*speed)


def test_free_tug_propulsion_never_transfers_force_to_ship(coupled):
    original = coupled.integrator.state
    original_tug = coupled.integrator.auxiliary_state
    coupled.schedule(order(coupled,mode="free"));coupled.apply_pending()
    assert coupled.integrator.auxiliary_state == original_tug
    coupled.advance(3)
    assert coupled.integrator.state == pytest.approx(original,abs=1e-12)
    assert coupled.integrator.auxiliary_state[1] < original_tug[1]
    assert coupled.tug_wrench(coupled.t) == (0,0,0)
    assert coupled.frame().tug_dynamics[0].connection_state == "free"


def test_push_requires_contact_and_accelerates_tug_then_ship(coupled):
    coupled.schedule(order(coupled));coupled.apply_pending()
    coupled.advance(1)
    assert coupled.tug_wrench(coupled.t) == (0,0,0)
    assert coupled.integrator.state[3:] == pytest.approx((0,0,0))
    coupled.advance(12)
    tug = coupled.frame().tug_dynamics[0]
    assert tug.connection_state == "push_contact" and tug.contact_compression_ft > 0
    assert tug.transferred_y_lbf < 0 and coupled.integrator.state[1] < 100
    cfg = coupled.tug_dynamics.configs["T1"]
    assert math.hypot(tug.propulsion_surge_lbf,tug.propulsion_sway_lbf) <= cfg.max_propulsion_lbf
    assert math.hypot(tug.transferred_x_lbf,tug.transferred_y_lbf) <= cfg.contact_capacity_lbf
    diagnostics = coupled.diagnostics()
    scale = max(abs(diagnostics.applied_work_ftlbf),abs(diagnostics.final_energy_ftlbf),1)
    assert abs(diagnostics.energy_residual_ftlbf)/scale < .002


def test_tow_slack_then_taut_and_equal_opposite_connection_wrench(coupled):
    coupled.schedule(order(coupled,mode="tow",vy=1));coupled.apply_pending()
    assert coupled.frame().tug_dynamics[0].connection_state == "tow_slack"
    assert coupled.tug_wrench(0) == (0,0,0)
    coupled.advance(20)
    state = coupled.frame().tug_dynamics[0]
    assert state.connection_state == "tow_taut" and state.tow_tension_lbf > 0
    assert state.transferred_y_lbf > 0 and coupled.integrator.state[1] > 100
    ship,tug = coupled.integrator.state,coupled.auxiliary_at()[:6]
    c = coupled.tug_dynamics.connections(ship,coupled.auxiliary_at())["T1"]
    ship_force = rotate(ship[2],*c.ship_wrench[:2])
    tug_force = rotate(tug[2],*c.tug_wrench[:2])
    assert tuple(a+b for a,b in zip(ship_force,tug_force)) == pytest.approx((0,0),abs=1e-10)
    total_moment = (c.ship_wrench[2]+ship[0]*ship_force[1]-ship[1]*ship_force[0]
                    +c.tug_wrench[2]+tug[0]*tug_force[1]-tug[1]*tug_force[0])
    assert total_moment == pytest.approx(0,abs=1e-7)


def test_release_records_elastic_energy_without_velocity_jump(coupled):
    coupled.schedule(order(coupled,mode="tow",vy=1));coupled.apply_pending();coupled.advance(20)
    before = coupled.total_energy()
    velocities = (coupled.integrator.state,coupled.integrator.auxiliary_state)
    coupled.schedule(order(coupled,mode="free",vy=1));coupled.apply_pending()
    assert velocities == (coupled.integrator.state,coupled.integrator.auxiliary_state)
    assert coupled.tug_event_energy == pytest.approx(coupled.total_energy()-before)
    assert coupled.tug_wrench(coupled.t) == (0,0,0)


def test_rich_tug_motion_acceleration_matches_forces(coupled):
    coupled.schedule(order(coupled,mode="free"));coupled.apply_pending();coupled.advance(1)
    f = rich.rich_frame(coupled,session_id="s",run_id="r",sequence=0,scene=rich.build_scene(coupled))
    tug = f.tug_states[0]
    assert tug.position.y_ft == coupled.auxiliary_at()[1]
    assert tug.velocity.y_fps < 0 and tug.acceleration.y_fps2 < 0
    assert tug.commanded_force is None and tug.actual_force.y_lbf == 0
    assert not any(r.code == "PRESCRIBED_TUG_KINEMATICS" for r in tug.validity.reasons)
    cfg = coupled.tug_dynamics.configs["T1"]
    u,thrust = coupled.auxiliary_at()[3],coupled.auxiliary_at()[6]
    assert -tug.acceleration.y_fps2 == pytest.approx((thrust-cfg.damping_surge_lbf_per_fps*u)/cfg.mass_slug)


def test_clone_dense_sample_and_chunking_preserve_complete_tug_state(coupled):
    coupled.schedule(order(coupled));coupled.apply_pending();coupled.advance(3)
    clone = coupled.clone_for_prediction()
    assert clone.integrator.coupled_step.__self__ is clone
    original_aux = coupled.auxiliary_at()
    previous_t = clone.integrator.previous[0]
    sample = clone.integrator.sample_auxiliary((previous_t+clone.t)/2)
    assert sample != clone.auxiliary_at() and clone.auxiliary_at() == original_aux
    clone.advance(12)
    assert coupled.auxiliary_at() == original_aux
    for _ in range(1000):
        if coupled.t >= 12-1e-9:
            break
        coupled.advance(12,max_work=7)
    assert coupled.integrator.state == clone.integrator.state
    assert coupled.auxiliary_at() == clone.auxiliary_at()
    assert coupled.diagnostics() == clone.diagnostics()


def test_direct_force_bypass_and_unbounded_velocity_order_rejected(coupled):
    with pytest.raises(ValueError,match="direct ship-force"):
        coupled.schedule(SimTugCommandMessage(type="tug_command",t_s=0,tug_id="T1",force_lbf=10000,direction_rel_deg=90))
    with pytest.raises(ValueError,match="velocity"):
        coupled.schedule(order(coupled,vy=100))
    assert not coupled.pending


def test_reseed_tug_is_explicit_and_resets_dense_history(coupled):
    state = (450,200,.5,1,2,.1)
    ship = coupled.integrator.state
    coupled.reseed_tug("T1",state,reset_actuators=True)
    assert coupled.integrator.state == ship
    assert coupled.auxiliary_at()[:6] == state
    assert coupled.integrator.previous_auxiliary_state == coupled.auxiliary_at()
    with pytest.raises(ValueError,match="six finite"):
        coupled.reseed_tug("T1",(*state[:5],float("nan")))


def test_unsupported_free_hull_overlap_stops_without_inventing_collision_force(coupled):
    coupled.schedule(order(coupled,mode="free"));coupled.apply_pending()
    with pytest.raises(ValueError,match="tug connection"):
        coupled.advance(20)
    frame = coupled.frame()
    assert frame.validity.state == "invalid"
    assert frame.tug_dynamics[0].connection_state == "free"
    assert frame.tug_dynamics[0].transferred_y_lbf == 0


def test_supplied_tug_numerical_stiffness_bound_is_enforced(coupled):
    with pytest.raises(ValueError,match="dt <="):
        BerthingModel(coupled.sc,coupled.initial,coupled.env,controls=coupled.controls_config,dt=1)
