"""The route policy acts through bounded actuators at deterministic simulation times."""
import pytest

from test_motion_controls_physics import model, helm  # noqa: F401 - synthetic fixture
from mooring.berthing.simulator import BerthingModel
from mooring.berthing.route_guidance import RouteGuidance, RoutePoint
from mooring.core.schemas import SimControlMessage
from modeling_api.sim_sessions import Session


def guided(model):
    guidance = RouteGuidance([RoutePoint(400,100,1,"start"),RoutePoint(1400,100,0,"end")],"synthetic-test",400)
    return BerthingModel(model.sc,model.initial,model.env,controls=model.controls_config,guidance=guidance,dt=.1,duration=60)


def test_guidance_only_changes_commands_and_slew(model):
    m = guided(model)
    original = m.integrator.state
    m.advance(0)
    assert m.integrator.state == original
    assert m.propulsion.commanded.port_throttle > 0
    assert m.propulsion.actual(0).port_throttle == 0
    assert m.guidance.next_update_s == .5 and m.sequence == 1
    m.advance(2)
    assert m.integrator.state[0] > original[0]
    assert m.guidance.next_update_s == 2.5 and m.sequence == 5
    assert m.frame().guidance.active and m.frame().guidance.route_id == "synthetic-test"


def test_manual_helm_wins_at_guidance_boundary(model):
    m = guided(model)
    m.schedule(helm().model_copy(update={"t_s":.5}))
    m.advance(1)
    assert not m.guidance.active
    assert m.propulsion.commanded.port_throttle == 0
    assert m.guidance.next_update_s == .5


def test_guidance_is_independent_of_work_chunks_and_clones(model):
    whole = guided(model)
    chunks = whole.clone_for_prediction()
    whole.advance(3)
    while chunks.t < 3-1e-9 or chunks.commands_due():
        chunks.advance(3,max_work=1)
    assert chunks.integrator.state == whole.integrator.state
    assert chunks.guidance == whole.guidance and chunks.sequence == whole.sequence
    assert chunks.propulsion.actual(3) == whole.propulsion.actual(3)


def test_session_reset_restores_initial_guidance(model):
    s = Session(guided(model),session_id="guidance-reset",clock=lambda:0)
    s.attach("controller")
    s.receive("controller",helm())
    s.model.advance(1)
    assert not s.model.guidance.active
    s.receive("controller",SimControlMessage(type="reset"))
    assert s.model.guidance.active and s.model.guidance.next_update_s == 0
    assert s.model.t == 0 and s.paused


def test_guidance_due_counts_as_scheduler_work_at_same_clock(model):
    s = Session(guided(model),session_id="guidance-budget",clock=lambda:0)
    s.attach("controller")
    assert s.model.commands_due()
    s.tick(max_steps=1)
    assert s.model.t == 0 and not s.model.commands_due()
    assert s.model.frame().controls.commanded.port_throttle > 0
    assert s.model.integrator.state[3:] == pytest.approx((0,0,0))
