"""Atomic observed-state adoption preserves mechanics and source-time forcing."""
import pytest

from test_motion_controls_physics import model, helm  # noqa: F401
from test_motion_controls_tug_dynamics import coupled, order  # noqa: F401
from test_motion_state import accept, observation
from mooring.berthing import rich
from mooring.berthing.simulator import BerthingModel
from mooring.core.schemas import ForcingSpec, SimTugCommandMessage
from mooring.core.schemas.motion_controls import SimLineControlMessage
from modeling_api.sim_sessions import Session


def test_reseed_preserves_ramps_lines_forcing_phase_and_future_trajectory(model):
    m = BerthingModel(model.sc,model.initial,model.env,controls=model.controls_config,dt=.05,duration=60,
        forcing=ForcingSpec(kind="gusts",seed=42,tide_amplitude_ft=1,tide_period_s=30))
    m.schedule(helm(port=.5,starboard=.5))
    m.schedule(SimTugCommandMessage(type="tug_command",t_s=0,tug_id="T1",force_lbf=1000,direction_rel_deg=90))
    m.schedule(SimLineControlMessage(type="line_control",t_s=0,line_number=1,attached=True,paid_out_length_ft=150))
    m.advance(2.25)
    state,actual,force = m.integrator.state,m.propulsion.actual(m.t),m.tug_force("T1",m.t)
    restored = m.reseeded(state)
    assert restored.t == 0 and m.t == pytest.approx(2.25)
    assert restored.forcing_time_offset_s == m.t
    assert restored.propulsion.actual(0) == actual and restored.tug_force("T1",0) == force
    assert restored.all_lines[1] in restored.system.lines
    assert restored.all_lines[1].model.rest_length_ft == 150
    assert restored.initial_energy == pytest.approx(restored.total_energy())
    assert restored.diagnostics().energy_residual_ftlbf == pytest.approx(0,abs=1e-8)
    assert restored.forcing_at(0)[0] == m.forcing_at(m.t)[0]
    m.advance(3.25);restored.advance(1)
    assert restored.integrator.state == pytest.approx(m.integrator.state,abs=1e-8)
    assert restored.forcing_at(1)[0].water_level_mllw_ft == pytest.approx(m.forcing_at(m.t)[0].water_level_mllw_ft)
    assert restored.forcing_at(1)[0].wind_speed_kt == pytest.approx(m.forcing_at(m.t)[0].wind_speed_kt)


def test_reseed_clears_future_orders_and_is_atomic_on_invalid_input(model):
    model.schedule(helm(port=1).model_copy(update={"t_s":10}))
    before = (model.integrator.state,list(model.pending))
    with pytest.raises(ValueError,match="finite"):
        model.reseeded((0,0,0,float("inf"),0,0))
    assert (model.integrator.state,model.pending) == before
    reseeded = model.reseeded((420,100,.1,1,0,.01))
    assert not reseeded.pending and model.pending
    assert reseeded.integrator.previous == (0,reseeded.integrator.state)
    assert reseeded.integrator.steps == 0 and reseeded.integrator.crossings == []


def test_tug_reseed_preserves_other_bodies_actual_propulsion_and_targets(coupled):
    coupled.schedule(order(coupled,mode="free"));coupled.apply_pending();coupled.advance(1)
    ship,aux = coupled.integrator.state,coupled.auxiliary_at()
    state = (700,200,.2,1,0,.01)
    restored = coupled.reseeded(state,tug_id="T1")
    assert restored.t == 0 and restored.integrator.state == ship
    assert restored.auxiliary_at()[:6] == state
    assert restored.auxiliary_at()[6:] == aux[6:]
    assert restored.tug_dynamics.orders == coupled.tug_dynamics.orders
    assert coupled.t == 1 and coupled.auxiliary_at() == aux
    assert restored.initial_energy == restored.total_energy()


def test_input_acceleration_stays_evidence_not_simulated_force(model):
    evidence = accept(observation(x_ft=400,y_ft=100,heading_true_deg=90,surge_fps=0,sway_fps=0,yaw_degps=0,
        measured_acceleration={"surge_fps2":99}),simulation_time_s=0)
    restored = model.reseeded(evidence.as_integrator_state())
    restored.state_inputs = [evidence]
    frame = rich.rich_frame(restored,session_id="s",run_id=evidence.run_id,sequence=0,scene=rich.build_scene(restored))
    assert frame.state_inputs == [evidence]
    assert frame.state_inputs[0].input.measured_acceleration.surge_fps2 == 99
    assert frame.motion.acceleration.surge_fps2 == 0
    assert "forcing_time_offset_s" not in frame.model_dump()
    assert "state_inputs" not in model.frame().model_dump()


def test_released_session_rejects_late_socket_attachment(model):
    session = Session(model)
    session.released = True
    with pytest.raises(ValueError,match="session released"):
        session.attach("late-controller")
    assert session.connection is None
