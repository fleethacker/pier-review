"""Independent session-rollout evidence on explicitly synthetic mechanics."""

import math

import pytest
from pydantic import ValidationError

from mooring import refdata
from mooring.berthing import motion_prediction as mp
from mooring.berthing.simulator import BerthingModel
from mooring.core.schemas import ForcingSample, ForcingSpec, Scenario, ShipState, SimLineEventMessage, SimTugCommandMessage
from mooring.core.schemas.motion_prediction import MotionPredictionRequest, MotionPredictionResponse
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship
from mooring.mechanics.dynamics import BodyParams


@pytest.fixture
def make(monkeypatch):
    ship, berth, spec = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
    monkeypatch.setattr(refdata, "ship", lambda _: ship.model_copy(deep=True))
    monkeypatch.setattr(refdata, "berth", lambda _: berth.model_copy(deep=True))
    monkeypatch.setattr(refdata, "line", lambda _: spec.model_copy(deep=True))
    # Functional correctness is independent of machine load. Deadline tests
    # below use a deterministic clock; measured throughput is not a CI gate.
    monkeypatch.setattr(mp.time, "monotonic", lambda: 0.0)

    def build(*, side="starboard", dt=.1, duration=200, forcing=None, params=None, controls=None, **state):
        sc = Scenario.model_validate({**EXAMPLES["scenario"], "scenario_id": "prediction-test",
            "created_at_utc": "2026-01-01T00:00:00Z", "ship_class_id": ship.class_id,
            "berth_id": berth.berth_id, "side_to": side, "config": breast_config(side_to=side, standoff=11)})
        initial = ShipState(x_ft=400, y_ft=state.pop("y_ft", 80),
            heading_true_deg=state.pop("heading_true_deg", 90 if side == "starboard" else 270), **state)
        kwargs = {} if params is None else {"params": params}
        if controls is not None:
            kwargs["controls"] = controls
        return BerthingModel(sc, initial, calm_env(), dt=dt, duration=duration, forcing=forcing, **kwargs)

    return build


def predict(model, **request):
    return mp.predict_motion(model, MotionPredictionRequest(**request), session_id="session", run_id="run",
                             sequence=7, scene_id="scene", scene_revision="1")


def state_of(point):
    p, v = point.pose, point.velocity
    return (p.x_ft, p.y_ft, math.radians(p.yaw_deg), v.surge_fps, v.sway_fps, math.radians(v.yaw_degps))


def tug(t, force=10000):
    return SimTugCommandMessage(type="tug_command", t_s=t, tug_id="T1", force_lbf=force, direction_rel_deg=90)


def test_exact_current_state_survives_and_prediction_does_not_advance_source(make):
    m = make(u_kt=-.7, v_kt=.3, r_degps=-.13, heading_true_deg=102)
    m.schedule(tug(.2))
    m.advance(.37)
    before = mp.snapshot_hash(m)
    result = predict(m, horizon_s=2.23, sample_interval_s=.5)
    assert mp.snapshot_hash(m) == before
    assert result.source.input_hash == before
    assert result.source.t_s == .37
    assert result.source.sequence == 7 and result.source.command_sequence == 1
    assert state_of(result.path[0]) == pytest.approx(m.integrator.state, abs=1e-14)
    assert result.path[0].velocity.surge_fps < 0 and result.path[0].velocity.sway_fps < 0
    assert result.path[0].velocity.yaw_degps < 0
    assert result.horizon_s == pytest.approx(2.23) and result.complete
    assert result.path[-1].t_s == pytest.approx(2.60)
    assert [p.elapsed_s for p in result.path] == pytest.approx([0, .5, 1, 1.5, 2, 2.23])
    MotionPredictionResponse.model_validate_json(result.model_dump_json())


@pytest.mark.parametrize("side,heading,expected_sway", [("starboard", 90, -1), ("port", 270, 1)])
def test_side_and_true_heading_are_not_confused_with_body_yaw(make, side, heading, expected_sway):
    m = make(side=side, u_kt=-1, v_kt=.25, r_degps=.1)
    r = predict(m, horizon_s=.25)
    p = r.path[0]
    assert math.copysign(1, p.velocity.sway_fps) == expected_sway
    assert (m.berth.face_bearing_true_deg-p.pose.yaw_deg) % 360 == pytest.approx(heading)
    assert p.velocity.yaw_degps == .1
    assert max(x.x_ft for x in p.footprint)-min(x.x_ft for x in p.footprint) == pytest.approx(400)
    assert max(x.y_ft for x in p.footprint)-min(x.y_ft for x in p.footprint) == pytest.approx(60)


def test_prediction_equals_direct_model_with_current_ramps_and_future_commands(make):
    m = make(u_kt=-.2, v_kt=.05, r_degps=.01)
    m.schedule(tug(0)); m.advance(.37)
    m.schedule(tug(1.17, 5000))
    direct = m.clone_for_prediction()
    result = predict(m, horizon_s=4.13, sample_interval_s=.25)
    direct.advance(4.50)
    assert state_of(result.path[-1]) == pytest.approx(direct.integrator.state, abs=1e-10)
    assert result.work.integration_steps == direct.integrator.steps-m.integrator.steps
    assert result.work.commands_applied == 1
    assert result.transitions == direct.transitions[len(m.transitions):]
    assert m.pending[0][0] == 1.17 and m.t == .37


def test_display_sampling_does_not_change_trajectory_or_integrator_work(make):
    m = make(dt=.3, u_kt=.3, v_kt=.02, r_degps=.05)
    m.schedule(tug(.52))
    sparse = predict(m, horizon_s=3.13, sample_interval_s=2)
    dense = predict(m, horizon_s=3.13, sample_interval_s=.25)
    assert sparse.path[-1].pose == dense.path[-1].pose
    assert sparse.path[-1].velocity == dense.path[-1].velocity
    assert sparse.work == dense.work
    assert sparse.transitions == dense.transitions
    assert sparse.source.input_hash == dense.source.input_hash
    assert sparse.prediction_id != dense.prediction_id


def test_absolute_simulation_time_and_what_if_ordering(make):
    m = make()
    m.advance(2.37)
    m.schedule(tug(2.87, 2000))
    alternate = tug(2.87, 8000)
    result = predict(m, horizon_s=2, what_if_commands=[alternate])
    direct = m.clone_for_prediction(); direct.schedule(alternate); direct.advance(4.37)
    assert state_of(result.path[-1]) == pytest.approx(direct.integrator.state)
    assert result.work.commands_applied == 2
    assert m.sequence == 1 and len(m.pending) == 1
    hold = predict(m, horizon_s=2)
    assert hold.path[-1].pose != result.path[-1].pose
    assert hold.source == result.source
    assert hold.prediction_id != result.prediction_id


def test_omitted_what_if_time_is_current_snapshot_time(make):
    m = make(); m.advance(3.17)
    command = tug(None)
    r = predict(m, horizon_s=1, what_if_commands=[command])
    direct = m.clone_for_prediction(); direct.schedule(tug(3.17)); direct.advance(4.17)
    assert state_of(r.path[-1]) == pytest.approx(direct.integrator.state)
    assert command.t_s is None


@pytest.mark.parametrize("time", [0, 1.999, 3.001, 10])
def test_what_if_outside_absolute_horizon_is_rejected(make, time):
    m = make(); m.advance(2)
    before = mp.snapshot_hash(m)
    with pytest.raises(ValueError, match="absolute simulation-time"):
        predict(m, horizon_s=1, what_if_commands=[tug(time)])
    assert mp.snapshot_hash(m) == before


def test_queued_command_and_forcing_change_identity_even_at_unchanged_time(make):
    m = make(); original = predict(m, horizon_s=.25)
    m.schedule(tug(10))  # beyond this prediction, still part of immutable source identity
    queued = predict(m, horizon_s=.25)
    assert queued.source.t_s == original.source.t_s
    assert queued.source.input_hash != original.source.input_hash
    assert queued.source.command_sequence == 1
    m.env.water_level_mllw_ft += .1
    assert predict(m, horizon_s=.25).source.input_hash != queued.source.input_hash


def test_clone_callbacks_never_call_original_set_env_or_mutate_line_records(make, monkeypatch):
    forcing = ForcingSpec(kind="ramp", target=ForcingSample(t_s=10, water_level_mllw_ft=3))
    m = make(y_ft=42, forcing=forcing)
    m.schedule(SimLineEventMessage(type="line_event", t_s=0, line_number=1, event="secured"))
    m.advance(.2)
    m.schedule(SimLineEventMessage(type="line_event", t_s=.5, line_number=1, event="released"))
    before = mp.snapshot_hash(m)
    old_set_env = BerthingModel.set_env
    calls = []

    def spy(self, t, s):
        calls.append(self)
        assert self is not m, "prediction callback escaped its clone"
        return old_set_env(self, t, s)

    monkeypatch.setattr(BerthingModel, "set_env", spy)
    result = predict(m, horizon_s=1)
    assert calls and mp.snapshot_hash(m) == before
    assert len(m.system.lines) == 1 and m.pending[0][2].event == "released"
    assert any(t.kind == "released" and t.t_s == .5 for t in result.transitions)
    assert result.source.forcing_revision == m.forcing_revision


def test_time_varying_forcing_is_not_restarted_from_zero(make):
    forcing = ForcingSpec(kind="ramp", target=ForcingSample(t_s=10, wind_speed_kt=20,
        wind_gust_kt=20, wind_from_true_deg=0, water_level_mllw_ft=3))
    m = make(forcing=forcing); m.advance(3.17)
    direct = m.clone_for_prediction(); direct.advance(5.42)
    r = predict(m, horizon_s=2.25)
    assert state_of(r.path[-1]) == pytest.approx(direct.integrator.state, abs=1e-9)
    assert r.source.forcing_revision == m.forcing.revision


@pytest.mark.parametrize("policy", ["stop", "invalidate"])
def test_forcing_horizon_truncates_at_exact_coverage_without_held_extrapolation(make, policy):
    forcing = ForcingSpec(kind="replay", on_uncovered=policy, samples=[
        ForcingSample(t_s=0, water_level_mllw_ft=0), ForcingSample(t_s=2.37, water_level_mllw_ft=1)])
    m = make(forcing=forcing); m.advance(.7)
    r = predict(m, horizon_s=5)
    assert not r.complete and r.horizon_s == pytest.approx(1.67)
    assert r.path[-1].t_s == 2.37
    assert "PREDICTION_FORCING_END" in {w.code for w in r.warnings}
    assert "FORCING_UNCOVERED" not in {v.code for v in r.validity.reasons}


def test_session_end_preserves_final_partial_step(make):
    m = make(duration=2.37); m.advance(.7)
    direct = m.clone_for_prediction(); direct.advance(2.37)
    r = predict(m, horizon_s=5)
    assert not r.complete and r.path[-1].t_s == 2.37
    assert state_of(r.path[-1]) == pytest.approx(direct.integrator.state)
    assert "PREDICTION_SESSION_END" in {w.code for w in r.warnings}


def test_ended_session_returns_only_actual_state(make):
    m = make(duration=.37); m.advance(.37)
    r = predict(m, horizon_s=1)
    assert not r.complete and r.horizon_s == 0 and len(r.path) == 1
    assert r.work.integration_steps == r.work.commands_applied == 0


def test_work_budget_counts_commands_and_never_changes_dt(make, monkeypatch):
    m = make(dt=.0001)
    for _ in range(12):
        m.schedule(tug(0))
    monkeypatch.setattr(mp, "MAX_WORK", 19)
    r = predict(m, horizon_s=1)
    assert r.work.commands_applied == 12 and r.work.integration_steps == 7
    assert r.work.integration_dt_s == .0001 and r.work.work_limit == 19
    assert r.horizon_s == pytest.approx(.0007) and not r.complete
    assert "PREDICTION_WORK_LIMIT" in {w.code for w in r.warnings}
    assert m.t == 0 and len(m.pending) == 12


def test_runtime_deadline_is_deterministic_and_returns_last_completed_chunk(make, monkeypatch):
    m = make()
    times = iter([0, 0, mp.MAX_RUNTIME_S+1])
    monkeypatch.setattr(mp.time, "monotonic", lambda: next(times))
    r = predict(m, horizon_s=10)
    assert r.work.integration_steps == mp.WORK_CHUNK
    assert r.horizon_s == pytest.approx(mp.WORK_CHUNK*m.dt) and not r.complete
    assert "PREDICTION_RUNTIME_LIMIT" in {w.code for w in r.warnings}


def test_budget_before_first_step_does_not_invent_future_motion(make, monkeypatch):
    m = make(u_kt=1)
    times = iter([0, mp.MAX_RUNTIME_S+1])
    monkeypatch.setattr(mp.time, "monotonic", lambda: next(times))
    r = predict(m, horizon_s=10)
    assert r.horizon_s == 0 and len(r.path) == 1 and not r.complete
    assert state_of(r.path[0]) == m.integrator.state


def test_initial_hazard_overlap_and_unknown_layers_never_all_clear(make):
    m = make(y_ft=39)
    r = predict(m, horizon_s=.25)
    assert r.path[0].pier_clearance_ft == 9
    assert r.path[0].fender_clearance_ft == 0
    assert r.status == "RED"
    assert any(w.code == "FENDER_CONTACT" and w.t_s == 0 for w in r.warnings)
    assert set(r.hazards_checked) == {"pier", "fender"}
    assert set(r.hazards_unchecked) == {"coastline", "other_vessels", "bathymetry"}
    assert r.uncertainty.availability == "unavailable" and r.uncertainty.corridor is None


def test_clearance_known_parallel_hull_and_no_fake_uncertainty(make):
    r = predict(make(y_ft=80), horizon_s=.25)
    assert r.path[0].pier_clearance_ft == 50
    assert r.path[0].fender_clearance_ft == 40
    assert r.status == "AMBER" and r.validity.state == "limited"
    assert {"UNCERTAINTY_UNAVAILABLE", "HAZARD_COVERAGE_INCOMPLETE"} <= {w.code for w in r.warnings}


def test_swept_pier_crossing_between_display_ticks_is_retained(make):
    params = BodyParams(1e6, 1e10)  # no damping: independent constant-velocity analytical case
    m = make(y_ft=40, v_kt=10, params=params)
    m.system.fenders = []  # deliberately no fender layer; no contact force masks pier crossing
    m.integrator.events = m.crossing_functions()
    r = predict(m, horizon_s=2, sample_interval_s=2)
    assert len(r.path) == 2
    assert r.path[-1].pose.y_ft == pytest.approx(40-2*10*1.6878098571)
    assert r.path[-1].pier_clearance_ft == 0
    assert any(w.code == "PIER_CONTACT" and 0 < w.t_s < 2 for w in r.warnings)
    assert r.path[-1].fender_clearance_ft is None
    assert "fender" not in r.hazards_checked


def test_contact_beyond_finite_face_endpoint_is_not_invented(make):
    m = make(y_ft=20)
    s = m.integrator.state
    m.integrator.state = (1100, *s[1:])
    r = predict(m, horizon_s=.25)
    assert r.path[0].pier_clearance_ft == pytest.approx(100)
    assert not any(w.code == "PIER_CONTACT" for w in r.warnings)


def test_line_overload_reports_failure_and_never_mutates_original(make):
    m = make(y_ft=80)
    m.schedule(SimLineEventMessage(type="line_event", t_s=.15, line_number=1, event="secured"))
    before = mp.snapshot_hash(m)
    r = predict(m, horizon_s=1)
    assert r.validity.state == "invalid" and r.status == "RED" and not r.complete
    assert any(w.code == "LINE_MBS_EXCEEDED" for w in r.warnings)
    assert any(e.kind == "line_overload" for e in r.events)
    assert r.path[-1].t_s == pytest.approx(r.horizon_s)
    assert mp.snapshot_hash(m) == before


@pytest.mark.parametrize("payload", [
    {"horizon_s": float("nan")}, {"horizon_s": float("inf")}, {"horizon_s": 0}, {"horizon_s": 120.01},
    {"horizon_s": 1e-12},
    {"sample_interval_s": .249}, {"sample_interval_s": float("inf")}, {"dt_s": .1},
    {"what_if_commands": [tug(0).model_dump()]*33},
    {"what_if_commands": [{"type": "helm_command", "port_throttle": 2, "starboard_throttle": 0,
        "rudder_deg": 0, "bow_thruster": 0, "stern_thruster": 0}]},
    {"what_if_commands": [{"type": "pause"}]},
])
def test_request_rejects_unbounded_unknown_and_nonfinite_inputs(payload):
    with pytest.raises(ValidationError):
        MotionPredictionRequest.model_validate(payload)


def test_identical_snapshot_request_and_completed_work_have_identical_identity(make):
    m = make()
    first, second = predict(m, horizon_s=1), predict(m, horizon_s=1)
    assert first == second


def test_result_contract_rejects_false_completion_or_time_identity(make):
    raw = predict(make(), horizon_s=.37).model_dump(mode="json")
    raw["horizon_s"] = 1
    with pytest.raises(ValidationError, match="last path point"):
        MotionPredictionResponse.model_validate(raw)


def test_live_mid_slew_helm_and_what_if_use_same_actuator_state(make):
    from mooring.berthing.loading import synthetic_motion_controls
    from mooring.core.schemas.motion_controls import SimHelmCommandMessage

    controls = synthetic_motion_controls(synthetic_ship())
    m = make(controls=controls, u_kt=-.05, v_kt=.02, r_degps=.01)
    helm = SimHelmCommandMessage(type="helm_command", t_s=0, port_throttle=.6, starboard_throttle=.2,
                                rudder_deg=10, bow_thruster=.3, stern_thruster=-.2)
    m.schedule(helm); m.advance(.7)
    actual = m.propulsion.actual(m.t)
    assert 0 < actual.port_throttle < .6 and 0 < actual.rudder_deg < 10
    future = helm.model_copy(update={"t_s": 1.13, "port_throttle": -.3, "rudder_deg": -10})
    before = mp.snapshot_hash(m)
    r = predict(m, horizon_s=2.37, sample_interval_s=.25, what_if_commands=[future])
    direct = m.clone_for_prediction(); direct.schedule(future); direct.advance(3.07)
    assert state_of(r.path[-1]) == pytest.approx(direct.integrator.state, abs=1e-10)
    assert mp.snapshot_hash(m) == before and m.propulsion.actual(m.t) == actual
    assert r.work.integration_steps == direct.integrator.steps-m.integrator.steps


def test_loaded_cg_inertia_and_current_paid_out_line_state_are_preserved(make):
    from mooring.berthing.loading import synthetic_motion_controls
    from mooring.core.schemas.motion_controls import PayloadItem, SimLineControlMessage

    controls = synthetic_motion_controls(synthetic_ship())
    controls.loading.payloads = [PayloadItem(payload_id="cargo", label="Synthetic cargo", weight_lbf=100_000,
                                             x_ft=90, y_ft=5, z_ft=10)]
    m = make(controls=controls, y_ft=42)
    m.schedule(SimLineControlMessage(type="line_control", t_s=0, line_number=1,
                                    attached=True, paid_out_length_ft=100))
    m.advance(.3)
    assert m.params.cg_x_ft > 0 and m.params.cg_y_ft > 0
    before = mp.snapshot_hash(m)
    command = SimLineControlMessage(type="line_control", t_s=.73, line_number=1, paid_out_length_ft=90)
    r = predict(m, horizon_s=1.27, what_if_commands=[command])
    direct = m.clone_for_prediction(); direct.schedule(command); direct.advance(1.57)
    assert state_of(r.path[-1]) == pytest.approx(direct.integrator.state, abs=1e-10)
    assert mp.snapshot_hash(m) == before and m.all_lines[1].model.rest_length_ft == 100
    changed = m.clone_for_prediction()
    changed.all_lines[1].model.rest_length_ft = 99
    assert mp.snapshot_hash(changed) != before


def test_payload_what_if_changes_only_owned_clone(make):
    from mooring.berthing.loading import synthetic_motion_controls
    from mooring.core.schemas.motion_controls import SimLoadingCommandMessage

    m = make(controls=synthetic_motion_controls(synthetic_ship()))
    command = SimLoadingCommandMessage(type="loading_command", payloads=[{
        "payload_id": "cargo", "label": "Synthetic cargo", "weight_lbf": 100_000, "x_ft": 100, "y_ft": 5, "z_ft": 10}])
    r = predict(m, horizon_s=.73, what_if_commands=[command, tug(.1)])
    direct = m.clone_for_prediction(); direct.schedule(command); direct.schedule(tug(.1)); direct.advance(.73)
    assert state_of(r.path[-1]) == pytest.approx(direct.integrator.state)
    assert not m.loading_spec.payloads and direct.loading_spec.payloads


def test_prediction_has_no_recording_session_or_storage_side_effects(make, monkeypatch):
    from modeling_api.sim_sessions import Session
    from mooring.core import store

    session = Session(make(), session_id="isolation")
    source_hash = mp.snapshot_hash(session.model)
    before = (session.sequence, session.run_id, list(session.rec_frames), list(session.rec_lifecycle),
              session.rec_bytes, session.rec_dirty, session.latest.model_dump(mode="json"))

    def forbidden(*args, **kwargs):
        pytest.fail("prediction must not write storage")

    monkeypatch.setattr(store.DocStore, "__setitem__", forbidden)
    monkeypatch.setattr(store, "save_snapshot", forbidden)
    with session.lock:
        clone = session.snapshot_model()
        ids = dict(session_id=session.session_id, run_id=session.run_id, sequence=session.sequence,
                   scene_id=session.scene.scene_id, scene_revision=session.scene.revision)
    result = mp.predict_motion(clone, MotionPredictionRequest(horizon_s=.73), **ids)
    after = (session.sequence, session.run_id, list(session.rec_frames), list(session.rec_lifecycle),
             session.rec_bytes, session.rec_dirty, session.latest.model_dump(mode="json"))
    assert result.source.input_hash == source_hash and mp.snapshot_hash(session.model) == source_hash
    assert before == after and session.model.t == 0


def test_free_yaw_is_analytic_rotation_about_unchanged_body_reference(make):
    m = make(y_ft=1000, r_degps=2, params=BodyParams(1e6, 1e10))
    r = predict(m, horizon_s=3.37, sample_interval_s=.25)
    for p in r.path:
        assert p.pose.x_ft == 400 and p.pose.y_ft == 1000
        assert p.pose.yaw_deg == pytest.approx(2*p.elapsed_s, abs=1e-12)
        assert p.velocity.yaw_degps == pytest.approx(2, abs=1e-12)
        theta = math.radians(2*p.elapsed_s)
        assert p.footprint[0].x_ft == pytest.approx(400-200*math.cos(theta)+30*math.sin(theta))
        assert p.footprint[0].y_ft == pytest.approx(1000-200*math.sin(theta)-30*math.cos(theta))


def test_maximum_output_grid_is_bounded_and_final_partial_tick_is_included(make):
    r = predict(make(dt=.3), horizon_s=119.99, sample_interval_s=.25)
    assert len(r.path) == 481 and r.path[-1].elapsed_s == pytest.approx(119.99)
    assert r.work.integration_steps == 400
    assert r.work.integration_steps+r.work.commands_applied <= r.work.work_limit


def test_event_output_limit_is_explicit_and_cannot_report_complete(make, monkeypatch):
    # A single secured command produces line_taut plus secured at this stretched
    # initial pose, so one atomic command can exceed the remaining output slots.
    m = make(y_ft=42)
    for t, event in [(0, "secured"), (.1, "released"), (.2, "secured")]:
        m.schedule(SimLineEventMessage(type="line_event", t_s=t, line_number=1, event=event))
    monkeypatch.setattr(mp, "MAX_TRANSITIONS", 1)
    r = predict(m, horizon_s=.5)
    assert len(r.transitions) == 1 and not r.complete
    assert "PREDICTION_EVENTS_TRUNCATED" in {w.code for w in r.warnings}
    assert len(m.pending) == 3 and not m.system.lines


def test_event_budget_stops_before_applying_another_command(make, monkeypatch):
    m = make(y_ft=41)
    for t, event in [(0, "secured"), (.1, "released")]:
        m.schedule(SimLineEventMessage(type="line_event", t_s=t, line_number=1, event=event))
    monkeypatch.setattr(mp, "MAX_TRANSITIONS", 1)
    r = predict(m, horizon_s=.5)
    assert [t.kind for t in r.transitions] == ["secured"]
    assert r.horizon_s == 0 and r.work.commands_applied == 1 and r.work.integration_steps == 0
    assert "PREDICTION_EVENT_LIMIT" in {w.code for w in r.warnings}
    assert "PREDICTION_EVENTS_TRUNCATED" not in {w.code for w in r.warnings}


def test_warning_output_limit_never_downgrades_red(make, monkeypatch):
    monkeypatch.setattr(mp, "MAX_WARNINGS", 2)
    r = predict(make(y_ft=39), horizon_s=.25)
    assert len(r.warnings) == 2 and r.status == "RED"
    assert r.warnings[-1].code == "PREDICTION_WARNINGS_TRUNCATED"


def test_source_identity_is_frozen_after_publication(make):
    r = predict(make(), horizon_s=.25)
    with pytest.raises(ValidationError, match="frozen"):
        r.source.t_s = 123


@pytest.mark.parametrize("policy", ["stop", "invalidate"])
def test_reseeded_forcing_coverage_uses_source_clock_and_final_partial_step(make, policy):
    forcing = ForcingSpec(kind="replay", on_uncovered=policy, samples=[
        ForcingSample(t_s=0, water_level_mllw_ft=0), ForcingSample(t_s=3.37, water_level_mllw_ft=1)])
    original = make(forcing=forcing)
    original.advance(2)
    seeded = original.reseeded(original.integrator.state)
    seeded.advance(.2)
    # A second adoption accumulates the original source phase rather than
    # treating the previous run's local clock as the series clock.
    m = seeded.reseeded(seeded.integrator.state)
    assert m.forcing_time_offset_s == pytest.approx(2.2)
    before = mp.snapshot_hash(m)
    direct = m.clone_for_prediction()
    direct.advance(1.17)
    r = predict(m, horizon_s=2, sample_interval_s=.25)
    assert not r.complete and r.horizon_s == pytest.approx(1.17)
    assert r.path[-1].t_s == pytest.approx(1.17)
    assert state_of(r.path[-1]) == pytest.approx(direct.integrator.state, abs=1e-10)
    assert r.validity.state == "limited"
    assert "PREDICTION_FORCING_END" in {w.code for w in r.warnings}
    assert "FORCING_UNCOVERED" not in {v.code for v in r.validity.reasons}
    assert mp.snapshot_hash(m) == before == r.source.input_hash
    with pytest.raises(ValueError, match="available session/forcing horizon"):
        predict(m, horizon_s=2, what_if_commands=[tug(1.5)])


def test_reseeded_generated_forcing_does_not_extend_its_original_duration(make):
    original = make(duration=3, forcing=ForcingSpec(kind="steady", on_uncovered="invalidate"))
    original.advance(2)
    m = original.reseeded(original.integrator.state)
    result = predict(m, horizon_s=2)
    assert result.horizon_s == pytest.approx(1)
    assert result.validity.state == "limited" and not result.complete
    assert "PREDICTION_FORCING_END" in {w.code for w in result.warnings}


def coupled_prediction_model(make, side):
    from mooring.berthing.loading import synthetic_motion_controls
    from mooring.berthing.tug_dynamics import synthetic_tug_dynamics_config
    base = make(side=side, y_ft=100)
    controls = synthetic_motion_controls(base.ship)
    tug_spec, point, _ = base.anchors["T1"]
    controls.tug_dynamics = [synthetic_tug_dynamics_config(tug_spec, base.ship, point,
        base.initial, base.berth.face_bearing_true_deg)]
    return BerthingModel(base.sc, base.initial, base.env, controls=controls, tug_ids=["T1"], dt=.05, duration=60)


@pytest.mark.parametrize("side", ["port", "starboard"])
def test_tug_what_if_rollout_keeps_coupled_state_and_live_isolation(make, side):
    from mooring.core.schemas.motion_controls import SimTugMotionCommandMessage
    m = coupled_prediction_model(make, side)
    command = SimTugMotionCommandMessage(type="tug_motion_command", tug_id="T1", mode="push",
        target_velocity_x_fps=0, target_velocity_y_fps=-.5, target_heading_true_deg=180, tow_length_ft=10)
    m.schedule(command.model_copy(update={"t_s": 0}))
    m.advance(3.17)
    m.schedule(command.model_copy(update={"t_s": 5, "target_velocity_y_fps": -.6}))
    before, original_aux = mp.snapshot_hash(m), m.auxiliary_at()
    what_if = command.model_copy(update={"t_s": 6.25, "target_velocity_y_fps": -.8})
    # Exercise the same wire discriminator as the HTTP request.
    request = MotionPredictionRequest.model_validate({"horizon_s": 9, "sample_interval_s": .5,
        "what_if_commands": [what_if.model_dump(mode="json")]})
    direct = m.clone_for_prediction()
    direct.schedule(what_if)
    direct.advance(12.17)
    result = predict(m, **request.model_dump(mode="json"))
    assert result.complete and result.source.input_hash == before
    assert state_of(result.path[-1]) == pytest.approx(direct.integrator.state, abs=1e-9)
    assert result.work.commands_applied == 2
    assert direct.frame().tug_dynamics[0].connection_state == "push_contact"
    assert direct.tug_wrench(direct.t)[1] != 0
    assert direct.auxiliary_at() != original_aux
    assert mp.snapshot_hash(m) == before and m.auxiliary_at() == original_aux
    assert m.t == 3.17 and len(m.pending) == 1
    changed = m.clone_for_prediction()
    changed.reseed_tug("T1", (*original_aux[:3], 1.5, *original_aux[4:6]))
    assert mp.snapshot_hash(changed) != before
    changed = m.clone_for_prediction()
    changed.tug_dynamics.order(what_if)
    assert mp.snapshot_hash(changed) != before


def test_guidance_orders_count_toward_prediction_work_and_finish_boundary(make, monkeypatch):
    from mooring.berthing.loading import synthetic_motion_controls
    from mooring.berthing.route_guidance import RouteGuidance, RoutePoint
    base = make(y_ft=100)
    guidance = RouteGuidance([RoutePoint(400, 100, 1, "start"), RoutePoint(1400, 100, 0, "end")], "test")
    m = BerthingModel(base.sc, base.initial, base.env, controls=synthetic_motion_controls(base.ship),
        guidance=guidance, tug_ids=[], dt=.1, duration=60)
    result = predict(m, horizon_s=1)
    assert result.complete and result.work.commands_applied == 3  # t=0, .5, 1
    assert result.work.integration_steps == 10
    assert m.sequence == 0 and m.guidance.next_update_s == 0
    monkeypatch.setattr(mp, "MAX_WORK", 2)
    bounded = predict(m, horizon_s=1)
    assert bounded.horizon_s == pytest.approx(.1) and not bounded.complete
    assert bounded.work.commands_applied == 1 and bounded.work.integration_steps == 1
    assert "PREDICTION_WORK_LIMIT" in {w.code for w in bounded.warnings}
