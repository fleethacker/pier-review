"""Synthetic mechanics and deterministic clocks; no vessel qualification implied."""
import asyncio
import math

import pytest
from pydantic import ValidationError

from mooring import refdata, scenarios
from mooring.berthing import simulator as sim
from mooring.core.jobs import JobCancelled
from mooring.core.schemas import (BerthingSimRequest, Scenario, ShipState, SimControlMessage,
                                  SimLineEventMessage, SimTugCommandMessage)
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship
from mooring.mechanics.dynamics import BodyParams, MooredBody
from mooring.mechanics import equilibrium as eq
from mooring.mechanics.streaming import Integrator
from modeling_api.sim_sessions import Session, create


class Clock:
    now = 0.0
    def __call__(self): return self.now


@pytest.fixture
def setup(monkeypatch):
    ship, berth, spec = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
    monkeypatch.setattr(refdata, "ship", lambda _: ship.model_copy(deep=True))
    monkeypatch.setattr(refdata, "berth", lambda _: berth.model_copy(deep=True))
    monkeypatch.setattr(refdata, "line", lambda _: spec.model_copy(deep=True))
    sc = Scenario.model_validate({**EXAMPLES["scenario"], "scenario_id":"test-sim", "created_at_utc":"2026-01-01T00:00:00Z",
        "ship_class_id":ship.class_id, "berth_id":berth.berth_id, "side_to":"starboard", "config":breast_config(standoff=11)})
    env = calm_env()
    initial = ShipState(x_ft=400, y_ft=41, heading_true_deg=90, v_kt=0.5)
    monkeypatch.setattr(scenarios, "get", lambda _: sc.model_copy(deep=True))
    monkeypatch.setattr(scenarios, "environment_for", lambda _: env.model_copy(deep=True))
    return sc, initial, env


def command(t=0, force=10000):
    return SimTugCommandMessage(type="tug_command", t_s=t, tug_id="T1", force_lbf=force, direction_rel_deg=90)


def test_batch_matches_interactive_independent_of_frame_consumption(setup):
    sc, initial, env = setup
    req = BerthingSimRequest(scenario_id=sc.scenario_id, initial_state=initial, duration_s=5,
        sample_interval_s=0.2, tug_commands=[command(0).model_dump(exclude={"type"}), command(2,0).model_dump(exclude={"type"})])
    response = sim.simulate_berthing(req, "equivalence", "/api/v1")
    frames = sim.SERIES["equivalence"].frames
    clock = Clock()
    session = Session(sim.BerthingModel(*setup,duration=5),clock=clock)
    session.attach("controller")
    # Arrival order differs from timestamp order. Neither message advances time.
    session.receive("controller", command(2,0)); session.receive("controller", command(0))
    assert session.model.t == 0
    for i in range(1,26):
        clock.now = i*0.2
        session.tick()
        assert session.latest.pose.model_dump() == pytest.approx(frames[i].pose.model_dump(),abs=1e-9)
    assert response.result.diagnostics.integration_steps == session.model.integrator.steps
    assert response.result.diagnostics.energy_residual_ftlbf == pytest.approx(session.model.diagnostics().energy_residual_ftlbf)
    assert response.validity.state == "limited" and response.status == "AMBER"
    assert all(f.validity and any(r.code=="VESSEL_DYNAMICS_UNQUALIFIED" for r in f.validity.reasons) for f in frames)
    assert response.result.transitions == session.model.transitions
    # Batch sampling does not alter trajectory, extrema, events or diagnostics.
    sparse=sim.simulate_berthing(req.model_copy(update={"sample_interval_s":2}), "sparse", "/api/v1")
    assert sparse.result.diagnostics == response.result.diagnostics
    assert sparse.result.contact == response.result.contact
    assert sparse.result.transitions == response.result.transitions


def test_pause_reset_disconnect_reconnect_and_exclusive_controller(setup):
    clock=Clock(); session=Session(sim.BerthingModel(*setup,duration=2),clock=clock)
    session.attach("a")
    with pytest.raises(ValueError,match="active controller"): session.attach("b")
    clock.now=0.5; session.tick(); state=session.model.integrator.state
    session.receive("a",SimControlMessage(type="pause"))
    clock.now=100; session.tick()
    assert session.model.t==pytest.approx(.5) and session.model.integrator.state==state
    session.receive("a",SimControlMessage(type="resume")); clock.now+=.5; session.tick()
    assert session.model.t==pytest.approx(1)
    session.detach("a"); clock.now=200; session.tick(); session.attach("b"); session.tick()
    assert session.paused and session.model.t==pytest.approx(1)
    with pytest.raises(ValueError,match="active session"): session.receive("a",command(1))
    with pytest.raises(ValueError,match="current simulation time"): session.receive("b",command(.9))
    session.receive("b",SimControlMessage(type="resume")); clock.now+=10; session.tick()
    assert session.model.t==pytest.approx(2)
    with pytest.raises(ValueError,match="ended"):
        session.receive("b",command(2))
    session.receive("b",SimControlMessage(type="reset"))
    assert session.model.t==0 and session.paused and not session.model.ramps and not session.model.pending


def test_flood_and_unconsumed_frames_do_not_drive_or_block_physics(setup):
    clock=Clock(); a=Session(sim.BerthingModel(*setup),clock=clock); b=Session(sim.BerthingModel(*setup),clock=clock)
    a.attach("a"); b.attach("b")
    for _ in range(100): a.receive("a",command(1))
    with pytest.raises(ValueError,match="rate limit"): a.receive("a",command(1))
    assert a.model.t==b.model.t==0
    for i in range(1,31):
        clock.now=i*.1; a.tick(); b.tick()  # no client reads a's latest slot
    assert a.model.t==b.model.t==pytest.approx(3)
    assert a.latest.t_s==pytest.approx(3)
    assert not b.model.ramps and b.model.integrator.state!=a.model.integrator.state
    assert not hasattr(a,"frames")  # one replaceable slot, no growing output queue


def test_tug_ratings_slew_invalid_commands_and_duration(setup):
    model=sim.BerthingModel(*setup,duration=2)
    lo,hi=model.anchors["T1"][2]
    with pytest.raises(ValueError,match="rating"): model.schedule(command(0,abs(lo)+1))
    with pytest.raises(ValueError,match="normal hull"): model.schedule(command().model_copy(update={"direction_rel_deg":10}))
    with pytest.raises(ValueError,match="assignment"): model.schedule(command().model_copy(update={"tug_id":"missing"}))
    with pytest.raises(ValueError,match="configuration"):
        model.schedule(SimLineEventMessage(type="line_event",t_s=0,line_number=999,event="secured"))
    with pytest.raises(ValueError,match="session end"): model.schedule(command(3))
    model.schedule(command(0,abs(lo))); model.apply_pending()
    rate=max(abs(lo),abs(hi))/sim.SLEW_SECONDS
    assert model.tug_force("T1",.1)==pytest.approx(-min(abs(lo),.1*rate))
    model.advance(1)
    prior=model.tug_force("T1",1)
    model.schedule(command(1,0)); model.apply_pending()
    assert abs(model.tug_force("T1",1.1)-prior)<=rate*.1+1e-8
    with pytest.raises(ValidationError): BerthingSimRequest(scenario_id="s",initial_state=setup[1],duration_s=7201)
    with pytest.raises(ValidationError): BerthingSimRequest(scenario_id="s",initial_state=setup[1],duration_s=7200,sample_interval_s=.1)


def test_session_storage_limits(setup,monkeypatch):
    from mooring.core.jobs import JobQueueFull
    monkeypatch.setenv("MOORING_MAX_SESSIONS","1")
    sessions={}; create(sessions,"limit-one",sim.BerthingModel(*setup))
    with pytest.raises(JobQueueFull): create(sessions,"limit-two",sim.BerthingModel(*setup))


def test_progress_and_cancellation_check_inside_integration(setup):
    class Context:
        progress_values=[]
        checks=0
        def progress(self,fraction,message): self.progress_values.append(fraction)
        def check_cancelled(self):
            self.checks+=1
            if self.checks>105: raise JobCancelled()
    ctx=Context()
    req=BerthingSimRequest(scenario_id="s",initial_state=setup[1],duration_s=100)
    with pytest.raises(JobCancelled): sim.simulate_berthing(req,"cancelled-run","/api/v1",ctx)
    assert "cancelled-run" not in sim.SERIES
    assert ctx.progress_values and 0<ctx.progress_values[0]<.2


def test_streaming_contact_energy_compression_and_convergence(setup):
    errors=[]
    params=BodyParams(150000,4e9)
    for dt in (.05,.01,.002):
        m=sim.BerthingModel(*setup,dt=dt,duration=5,params=params)
        energy=m.initial_energy
        values=[]
        m.advance(5,observe=lambda *args: values.append(m.body.energy(m.integrator.state)))
        assert all(fr.reaction_lbf>=0 for fr in m.frame().fenders)
        assert max(abs(e-energy) for e in values)/energy<.002
        start=next(e.t_s for e in m.transitions if e.kind=="contact_start")
        assert start==pytest.approx(1/(.5*1.6878098571011957),abs=2e-5)
        assert any(e.kind=="contact_end" for e in m.transitions)
        errors.append(abs(m.integrator.state[4]-.5*1.6878098571011957))
    assert max(errors)<.002


def test_streaming_fourth_order_and_static_holding_consistency(setup):
    params=BodyParams(1e5,4e9)
    errors=[]
    for dt in (.2,.1,.05):
        step=Integrator(params,lambda t,s:(0,-3e5*s[1],0),(0,2,0,0,0,0),dt)
        step.advance(6)
        errors.append(abs(step.state[1]-2*math.cos(math.sqrt(3)*6)))
    assert errors[0]/errors[1]>10 and errors[1]/errors[2]>10
    sc,initial,env=setup
    sc.config=breast_config(pairs=(1,2,3,4),springs=True,pretension=2000)
    params=BodyParams(1e5,4e9,damping_lin=(4e5,4e5,2e10))
    m=sim.BerthingModel(sc,initial.model_copy(update={"y_ft":40,"v_kt":0}),env,dt=.1,duration=300,params=params)
    m.system.lines=list(m.all_lines.values())
    static=eq.solve(m.system)
    assert static.converged
    m.advance(300)
    pose=m.body.pose(m.integrator.state)
    assert (pose.dx_ft,pose.dy_ft,pose.dyaw_rad)==pytest.approx((static.pose.dx_ft,static.pose.dy_ft,static.pose.dyaw_rad),abs=.002)


def test_line_events_and_initial_taut_transition(setup):
    sc,initial,env=setup
    m=sim.BerthingModel(sc,initial.model_copy(update={"v_kt":-.5}),env,duration=2)
    for n in m.all_lines:
        m.schedule(SimLineEventMessage(type="line_event",t_s=.5,line_number=n,event="secured"))
        m.schedule(SimLineEventMessage(type="line_event",t_s=1.5,line_number=n,event="released"))
    m.advance(2)
    assert {e.kind for e in m.transitions}>={"secured","released","line_taut","line_slack"}
    assert not m.system.lines
    assert math.isfinite(m.diagnostics().energy_residual_ftlbf)


def test_websocket_handler_commands_backpressure_and_disconnect(setup,monkeypatch):
    """Drive the actual handler with an injected scheduler and a blocked transport."""
    from modeling_api import ws as route
    from starlette.websockets import WebSocketDisconnect
    class Socket:
        headers={}
        def __init__(self):
            self.incoming=asyncio.Queue(); self.sent=asyncio.Queue()
            self.waiting=asyncio.Event(); self.sending=asyncio.Event(); self.release=asyncio.Event()
            self.release.set(); self.closed=[]
        async def accept(self): pass
        async def receive(self):
            self.waiting.set()
            message=await self.incoming.get()
            if message is None: raise WebSocketDisconnect()
            return {"type":"websocket.receive","text":message}
        async def send_json(self,frame):
            self.sending.set()
            await self.release.wait()
            await self.sent.put(frame)
        async def close(self,code=1000,reason=""): self.closed.append((code,reason))
        async def command(self,msg):
            self.waiting.clear(); self.incoming.put_nowait(msg.model_dump_json())
            await self.waiting.wait()  # next receive means previous command was processed
    async def stopped_scheduler(self): await asyncio.Event().wait()
    monkeypatch.setattr(Session,"run",stopped_scheduler)
    async def exercise():
        clock=Clock(); session=Session(sim.BerthingModel(*setup),clock=clock)
        other=Session(sim.BerthingModel(*setup),clock=clock); other.attach("other")
        monkeypatch.setattr(route,"SESSIONS",{"socket-test":session})
        socket=Socket(); task=asyncio.create_task(route.ws_sim(socket,"socket-test"))
        assert (await socket.sent.get())["t_s"]==0
        await socket.command(command(0))
        assert session.model.t==0
        socket.release.clear(); socket.sending.clear()
        clock.now=.1; session.tick(); await socket.sending.wait()
        # Transport blocked: both physics sessions continue; frames overwrite one slot.
        for i in range(2,11):
            clock.now=i*.1; session.tick(); other.tick()
        assert session.model.t==other.model.t==pytest.approx(1)
        socket.release.set()
        await socket.sent.get()
        latest=await socket.sent.get()
        assert latest["t_s"]==pytest.approx(1)
        req=BerthingSimRequest(scenario_id="s",initial_state=setup[1],duration_s=1,
                              tug_commands=[command(0).model_dump(exclude={"type"})])
        sim.simulate_berthing(req,"ws-equivalent","/api/v1")
        assert latest["pose"]==pytest.approx(sim.SERIES["ws-equivalent"].frames[-1].pose.model_dump(),abs=1e-9)
        socket.incoming.put_nowait(None); await task
        assert session.paused and session.connection is None
        old=session.model.integrator.state; clock.now=500
        reconnect=Socket(); task=asyncio.create_task(route.ws_sim(reconnect,"socket-test"))
        assert (await reconnect.sent.get())["t_s"]==pytest.approx(1)
        session.tick(); assert session.model.integrator.state==old
        reconnect.incoming.put_nowait('{"type":"tug_command","force_lbf":-1}')
        await task
        assert any(code==1008 for code,_ in reconnect.closed)
        assert session.model.integrator.state==old and session.connection is None
        class TimedOutSocket(Socket):
            async def send_json(self,frame): raise TimeoutError("injected transport timeout")
        slow=TimedOutSocket()
        await route.ws_sim(slow,"socket-test")
        assert any(code==1013 for code,_ in slow.closed)
        assert session.model.integrator.state==old and session.connection is None
    asyncio.run(asyncio.wait_for(exercise(),timeout=5))


def test_tiny_steps_rejected_and_work_budget_returns_invalid(setup,monkeypatch):
    with pytest.raises(ValidationError):
        BerthingSimRequest(scenario_id="s",initial_state=setup[1],dt_s=1e-12)
    monkeypatch.setattr(sim,"MAX_STEPS",2)
    result=sim.simulate_berthing(BerthingSimRequest(scenario_id="s",initial_state=setup[1],duration_s=2),"budget-stop","/api/v1")
    assert result.validity.state=="invalid" and result.status=="RED"
    assert result.result.diagnostics.simulated_time_s<2
    assert sim.SERIES["budget-stop"].frames[-1].validity.state=="invalid"


def test_breaking_strength_stops_without_inventing_rupture(setup):
    sc,initial,env=setup
    m=sim.BerthingModel(sc,initial.model_copy(update={"y_ft":100,"v_kt":0}),env,duration=2)
    for n in m.all_lines:
        m.schedule(SimLineEventMessage(type="line_event",t_s=0,line_number=n,event="secured"))
    with pytest.raises(ValueError,match="rupture"): m.advance(1)
    assert m.invalid and any(r.code=="LINE_MBS_EXCEEDED" for r in m.reasons)
    assert any(e.kind=="line_overload" for e in m.events)


def test_wire_additions_are_omitted_for_legacy_payloads(setup):
    from mooring.core.schemas import SimSessionCreate, SimSessionCreated, SimFrame, BerthingSimResult
    from mooring.core.envelopes import inputs_hash
    session=SimSessionCreate(scenario_id="s",initial_state=setup[1])
    assert set(session.model_dump())=={"scenario_id","initial_state"}
    assert SimSessionCreated(session_id="s",ws_url="/s").model_dump()=={"session_id":"s","ws_url":"/s"}
    legacy=command().model_dump(exclude={"t_s"})
    assert SimTugCommandMessage.model_validate(legacy).model_dump()==legacy
    req=BerthingSimRequest(scenario_id="s",initial_state=setup[1])
    assert "sample_interval_s" not in req.model_dump()
    assert inputs_hash(req)==inputs_hash(req.model_copy(update={"sample_interval_s":None}))
    frame=SimFrame(t_s=0,pose=setup[1],tugs=[],lines=[],fenders=[],alerts=[])
    assert not ({"validity","diagnostics"}&frame.model_dump().keys())
    result=BerthingSimResult(series_url="/s",events=[],contact=None,max_line_tension_lbf=0)
    assert not ({"transitions","diagnostics"}&result.model_dump().keys())


def test_line_command_boundary_frames_match_session(setup):
    sc,initial,env=setup
    initial=initial.model_copy(update={"v_kt":-.1})
    events=[{"t_s":.5,"line_number":1,"event":"secured"},{"t_s":1,"line_number":1,"event":"released"}]
    req=BerthingSimRequest(scenario_id="s",initial_state=initial,duration_s=1,sample_interval_s=.5,line_events=events)
    sim.simulate_berthing(req,"line-boundaries","/api/v1")
    clock=Clock(); session=Session(sim.BerthingModel(sc,initial,env,duration=1),clock=clock)
    session.attach("a")
    for event in reversed(events): session.receive("a",SimLineEventMessage(type="line_event",**event))
    for t,frame in zip((.5,1),sim.SERIES["line-boundaries"].frames[1:]):
        clock.now=t; session.tick()
        assert session.latest.t_s==pytest.approx(frame.t_s)
        assert session.latest.model_dump(exclude={"t_s"})==frame.model_dump(exclude={"t_s"})


def test_ambiguous_line_commands_and_unrepresentable_initial_energy_rejected(setup):
    sc,initial,env=setup
    sc=sc.model_copy(deep=True)
    sc.config.lines.append(sc.config.lines[0].model_copy())
    with pytest.raises(ValueError,match="unique"): sim.BerthingModel(sc,initial,env)
    with pytest.raises(ValueError,match="numerical range"):
        sim.BerthingModel(setup[0],initial.model_copy(update={"u_kt":1e200}),env)
