"""Analytic synthetic checks: no vessel qualification or live inputs."""
import math
import gc
import weakref

import pytest

from mooring import refdata
from mooring.berthing import rich
from mooring.berthing.loading import loading_state, synthetic_motion_controls
from mooring.berthing.simulator import BerthingModel
from mooring.core.schemas import Scenario, ShipState, SimControlMessage, SimTugCommandMessage
from mooring.core.schemas.motion_controls import (
    LoadingSpec, LocalDepthPatch, PayloadItem,
    SimHelmCommandMessage, SimLineControlMessage, SimLoadingCommandMessage,
)
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship
from mooring.mechanics.dynamics import BodyParams, _deriv, kinetic_energy, rk4
from modeling_api.sim_sessions import Session
from modeling_api.ws import SimClientMessage


@pytest.fixture
def model(monkeypatch):
    ship, berth, line = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
    monkeypatch.setattr(refdata,"ship",lambda _:ship.model_copy(deep=True))
    monkeypatch.setattr(refdata,"berth",lambda _:berth.model_copy(deep=True))
    monkeypatch.setattr(refdata,"line",lambda _:line.model_copy(deep=True))
    sc = Scenario.model_validate({**EXAMPLES["scenario"],"scenario_id":"controls", "ship_class_id":ship.class_id,
        "berth_id":berth.berth_id,"created_at_utc":"2026-01-01T00:00:00Z", "side_to":"starboard",
        "config":breast_config(standoff=11)})
    return BerthingModel(sc,ShipState(x_ft=400,y_ft=100,heading_true_deg=90),calm_env(),duration=60,
                         controls=synthetic_motion_controls(ship),dt=.05)


def helm(**values):
    return SimHelmCommandMessage(type="helm_command",t_s=0,**dict(
        port_throttle=values.pop("port",0),starboard_throttle=values.pop("starboard",0),
        rudder_deg=values.pop("rudder",0),bow_thruster=values.pop("bow",0),stern_thruster=values.pop("stern",0)),**values)


def test_off_center_mass_matrix_matches_newton_euler_about_cg():
    p = BodyParams(10,20,cg_x_ft=2,cg_y_ft=3)
    # F at origin => torque about CG is yG*Fx=300; alpha=15.
    # a(origin)=F/m-alpha cross r(CG)=(10,0)-(-45,30).
    assert _deriv(p,(0,0,0,0,0,0),(100,0,0))[3:] == pytest.approx((55,-30,15))
    state = (0,0,.4,1,2,.3)
    expected = .5*10*((1-3*.3)**2+(2+2*.3)**2)+.5*20*.3**2
    assert kinetic_energy(p,state) == pytest.approx(expected)
    initial = kinetic_energy(p,state)
    for n in range(200):
        state = rk4(p,lambda t,s:(0,0,0),n*.01,state,.01)
    assert kinetic_energy(p,state) == pytest.approx(initial,rel=1e-10)


def test_remote_reference_does_not_erase_positive_centroidal_inertia():
    params = BodyParams(1e6,1,cg_x_ft=1e9)
    # Pure unit couple gives alpha=N/Icg=1 even when origin-based inertia rounds
    # away the centroidal component during parallel-axis addition.
    assert _deriv(params,(0,0,0,0,0,0),(0,0,1))[3:] == pytest.approx((0,-1e9,1))
    with pytest.raises(ValueError,match="numerical range"):
        BodyParams(1e300,1,cg_x_ft=1e300)


def toy_loading():
    return LoadingSpec(basis="synthetic",source="analytic box",base_mass_slug=1000,base_izz_slug_ft2=100000,
        base_cg_x_ft=0,base_cg_y_ft=0,base_cg_z_ft=0,base_draft_ft=5,base_cb_z_ft=-2.5,
        waterplane_area_ft2=100,waterplane_ixx_ft4=10000,waterplane_iyy_ft4=100000,
        water_density_slug_ft3=2,gravity_fps2=10,added_surge_slug=0,added_sway_slug=0,added_yaw_slug_ft2=0,
        damping_surge_lbf_per_fps=0,damping_sway_lbf_per_fps=0,damping_yaw_ftlbf_per_radps=0,
        max_abs_attitude_deg=5,max_sinkage_fraction=.25,
        payloads=[PayloadItem(payload_id="p",label="point",weight_lbf=1000,x_ft=10,y_ft=2,z_ft=5)])


def test_payload_mass_parallel_axes_archimedes_and_hydrostatic_moments():
    loaded = loading_state(toy_loading(),40,10)
    assert loaded.total_mass_slug == 1100
    assert (loaded.cg_x_ft,loaded.cg_y_ft,loaded.cg_z_ft) == pytest.approx((1000/1100,200/1100,500/1100))
    assert loaded.izz_cg_slug_ft2 == pytest.approx(100000+1000*100/1100*(100+4))
    assert loaded.izz_origin_slug_ft2 == pytest.approx(100000+100*(100+4))
    assert loaded.sinkage_ft == pytest.approx(.5)
    assert loaded.mean_draft_ft == 5.5
    assert loaded.gm_transverse_ft == pytest.approx(-2.25-500/1100+10000/550)
    assert math.radians(loaded.roll_deg)*loaded.gm_transverse_ft == pytest.approx(-200/1100)
    assert math.radians(loaded.pitch_deg)*loaded.gm_longitudinal_ft == pytest.approx(1000/1100)
    assert loaded.roll_deg < 0 < loaded.pitch_deg
    assert loaded.draft_fwd_ft > loaded.draft_aft_ft
    assert loaded.under_keel_ft is None
    assert loaded.validity.state == "limited"


def test_depth_patch_does_not_extrapolate_and_keeps_missing_uncertainty():
    spec = toy_loading()
    spec.local_depth = LocalDepthPatch(basis="synthetic",source="test patch",depth_mllw_ft=8,
        x_min_ft=-25,x_max_ft=25,y_min_ft=-10,y_max_ft=10)
    center = loading_state(spec,40,10,(0,0,0,0,0,0),2)
    assert center.under_keel_ft == pytest.approx(10-center.maximum_draft_ft)
    assert center.under_keel_lower_ft is None
    assert loading_state(spec,40,10,(10,0,0,0,0,0),2).under_keel_ft is None
    spec.local_depth.uncertainty_ft = 5
    bad = loading_state(spec,40,10,(0,0,0,0,0,0),0)
    assert bad.under_keel_lower_ft < 0 and bad.validity.state == "invalid"


def test_unsupported_hydrostatic_states_rejected():
    spec = toy_loading()
    spec.payloads[0].z_ft = 1000
    with pytest.raises(ValueError,match="nonpositive GM"):
        loading_state(spec,40,10)
    spec = toy_loading()
    spec.payloads[0].y_ft = 100
    with pytest.raises(ValueError,match="small-angle"):
        loading_state(spec,40,10)


def test_actuator_slew_and_force_moments_are_bounded(model):
    p = model.propulsion
    p.order(helm(port=1,starboard=-1,bow=.5,stern=-.5,rudder=20),0)
    assert p.actual(0).port_throttle == 0
    assert p.actual(1).port_throttle == pytest.approx(.2)
    assert p.actual(1).rudder_deg == 5
    f = p.state(10,(100,200,math.pi/2,0,0,0))
    assert f.port_thrust_lbf == p.spec.max_ahead_thrust_lbf
    assert f.starboard_thrust_lbf == -p.spec.max_astern_thrust_lbf
    assert abs(f.rudder_force_lbf) <= p.spec.rudder_max_force_lbf
    assert sum(x.yaw_moment_ftlbf for x in f.actuators) == pytest.approx(f.yaw_moment_ftlbf)
    assert sum(x.x_lbf for x in f.actuators) == pytest.approx(-f.sway_force_lbf)
    assert sum(x.y_lbf for x in f.actuators) == pytest.approx(f.surge_force_lbf)
    previous = p.actual(2)
    p.order(helm(port=-1),2)
    assert p.actual(2) == previous


@pytest.mark.parametrize("surge",[-3,0,3])
def test_centered_rudder_opposes_local_lateral_motion_in_both_axial_directions(model,surge):
    p = model.propulsion
    for lateral in (-2,2):
        _,parts = p.forces(0,(0,0,0,surge,lateral,0))
        assert parts[2]*lateral <= 0


def test_symmetric_engines_accelerate_by_force_without_velocity_overwrite(model):
    initial = model.integrator.state
    model.schedule(helm(port=.5,starboard=.5)); model.apply_pending()
    assert model.integrator.state == initial
    assert model.propulsion.actual(0).port_throttle == 0
    model.advance(10)
    assert model.integrator.state[3] > 0 and model.integrator.state[0] > initial[0]
    assert model.integrator.state[4:] == pytest.approx((0,0),abs=1e-10)
    assert abs(model.diagnostics().energy_residual_ftlbf)/model.work < .001


def test_payload_changes_acceleration_and_prescribes_vertical_pose(model):
    original_mass = model.params.mass_slug
    original_acc = _deriv(model.params,model.integrator.state,(10000,0,0))[3]
    payload = PayloadItem(payload_id="heavy",label="synthetic payload",weight_lbf=500000,x_ft=0,y_ft=0,z_ft=0)
    model.schedule(SimLoadingCommandMessage(type="loading_command",t_s=0,payloads=[payload]));model.apply_pending()
    assert model.params.mass_slug > original_mass
    assert _deriv(model.params,model.integrator.state,(10000,0,0))[3] < original_acc
    f = rich.rich_frame(model,session_id="s",run_id="r",sequence=0,scene=rich.build_scene(model))
    assert f.motion.dofs.roll == f.motion.dofs.pitch == "prescribed"
    assert f.motion.pose.heave_mllw_ft == -f.loading.sinkage_ft
    assert f.motion.velocity.roll_degps is None


def test_loading_rejected_while_moving_and_preserves_existing_state(model):
    model.integrator.state = (*model.integrator.state[:3],1,0,0)
    before = model.params
    with pytest.raises(ValueError,match="stationary"):
        model.schedule(SimLoadingCommandMessage(type="loading_command",t_s=0,payloads=[]))
    assert model.params is before and not model.pending


def test_line_payout_attachment_and_event_energy(model):
    rec = model.all_lines[1]
    length = model.system.line_state(rec,model.body.pose(model.integrator.state)).length_ft
    model.schedule(SimLineControlMessage(type="line_control",t_s=0,line_number=1,attached=True,paid_out_length_ft=length+1))
    model.apply_pending()
    assert model.line_control_states()[0].tension_lbf == 0
    before = model.body.energy(model.integrator.state)
    model.schedule(SimLineControlMessage(type="line_control",t_s=0,line_number=1,paid_out_length_ft=length*.99))
    model.apply_pending()
    assert model.line_control_states()[0].tension_lbf > 0
    assert model.event_energy == pytest.approx(model.body.energy(model.integrator.state)-before)
    model.schedule(SimLineControlMessage(type="line_control",t_s=0,line_number=1,attached=False));model.apply_pending()
    assert model.line_control_states()[0].tension_lbf is None
    assert model.event_energy == pytest.approx(0,abs=1e-8)


def test_clone_rebinds_closures_and_is_deterministic(model):
    model.schedule(helm(port=.5,starboard=.5));model.apply_pending();model.advance(.4)
    model.schedule(helm(port=.2,starboard=.1).model_copy(update={"t_s":2.0}))
    clone = model.clone_for_prediction()
    assert clone.integrator.forces.__self__ is clone
    assert clone.integrator.gap.__self__ is clone.body
    original_set_env = model.set_env
    def forbidden(*args):
        raise AssertionError("clone crossing touched original model")
    model.set_env = forbidden
    clone.system.lines.append(clone.all_lines[1])
    clone.integrator.events["taut:line-1"](clone.t,clone.integrator.state)
    clone.system.lines.clear()
    model.set_env = original_set_env
    snapshot = model.integrator.state
    clone.advance(4)
    assert model.integrator.state == snapshot and model.t == pytest.approx(.4)
    model.advance(4)
    assert model.integrator.state == clone.integrator.state
    assert model.propulsion.actual(4) == clone.propulsion.actual(4)
    clone.all_lines[1].model.rest_length_ft += 10
    assert clone.all_lines[1].model.rest_length_ft != model.all_lines[1].model.rest_length_ft


def test_repeated_snapshots_do_not_retain_ancestor_models(model):
    current = model
    ancestors = []
    for _ in range(12):
        successor = current.clone_for_prediction()
        if current is not model:
            ancestors.append(weakref.ref(current))
        current = successor
    gc.collect()
    assert all(reference() is None for reference in ancestors)
    assert current.integrator.forces.__self__ is current


def test_session_paused_loading_echo_and_reset_preserve_configuration(model):
    session = Session(model,session_id="loading-test")
    session.attach("a");session.receive("a",SimControlMessage(type="pause"))
    payload = PayloadItem(payload_id="p",label="p",weight_lbf=100000,x_ft=10,y_ft=2,z_ft=5)
    session.receive("a",SimLoadingCommandMessage(type="loading_command",payloads=[payload]))
    assert session.model.t == 0 and session.latest.loading.payloads == [payload]
    clone = session.snapshot_model()
    assert clone.loading_spec.payloads == [payload]
    session.receive("a",SimControlMessage(type="reset"))
    assert session.model.loading_spec.payloads == []
    assert session.model.controls_config == model.controls_config
    assert session.model.propulsion.commanded.port_throttle == 0


def test_prescribed_tug_vectors_are_rigid_body_kinematics(model):
    model.integrator.state = (400,100,.2,2,1,.01)
    model.schedule(SimTugCommandMessage(type="tug_command",t_s=0,tug_id="T1",force_lbf=10000,direction_rel_deg=90))
    model.apply_pending()
    f = rich.rich_frame(model,session_id="s",run_id="r",sequence=0,scene=rich.build_scene(model))
    tug = next(t for t in f.tug_states if t.tug_id == "T1")
    px,py = model.tug_attachments["T1"]
    expected = (math.cos(.2)*(2-.01*py)-math.sin(.2)*(1+.01*px),
                math.sin(.2)*(2-.01*py)+math.cos(.2)*(1+.01*px))
    assert (tug.velocity.x_fps,tug.velocity.y_fps) == pytest.approx(expected)
    assert tug.position is not None and tug.acceleration is not None
    assert any(r.code == "PRESCRIBED_TUG_KINEMATICS" for r in tug.validity.reasons)


def test_wire_controls_validate_reject_nonfinite_and_keep_old_omissions(model):
    assert isinstance(SimClientMessage.validate_json(helm(port=.5).model_dump_json()),SimHelmCommandMessage)
    with pytest.raises(ValueError):
        SimClientMessage.validate_python({**helm().model_dump(),"port_throttle":float("nan")})
    old = BerthingModel(model.sc,model.initial,model.env)
    assert not {"controls","loading","line_controls"}.intersection(old.frame().model_dump())
