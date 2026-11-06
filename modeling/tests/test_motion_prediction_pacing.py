"""Prediction throughput must not buy speed by changing accepted dynamics."""
import pytest

from mooring.mechanics.dynamics import BodyParams
from mooring.mechanics.streaming import Integrator
from mooring.berthing import motion_prediction as prediction
from mooring.core.schemas.motion_prediction import MotionPredictionRequest
from test_motion_controls_tug_dynamics import coupled  # noqa: F401 - complete coupled model
from test_motion_controls_physics import model  # noqa: F401 - shared fixture dependency


def test_accepted_sampling_endpoints_do_not_reevaluate_changed_forces():
    calls = []
    def step(t, state, auxiliary, dt):
        calls.append((t, dt))
        return tuple(v+dt for v in state), tuple(v+2*dt for v in auxiliary)
    integrator = Integrator(BodyParams(1, 1), lambda *_: (0, 0, 0), (0,)*6, .1,
                            coupled_step=step, auxiliary_state=(3, 4))
    integrator.advance(.1)
    calls.clear()
    left, right = integrator.previous[1], integrator.state
    assert integrator.sample(0) is left
    assert integrator.sample(.1) is right
    assert integrator.sample_auxiliary(0) is integrator.previous_auxiliary_state
    assert integrator.sample_auxiliary(.1) is integrator.auxiliary_state
    assert not calls
    assert integrator.sample(.04) == pytest.approx((.04,)*6)
    assert integrator.sample_auxiliary(.04) == pytest.approx((3.08, 4.08))
    assert calls == [(0, .04), (0, .04)]
    with pytest.raises(ValueError, match="most recent"):
        integrator.sample(-.01)
    with pytest.raises(ValueError, match="most recent"):
        integrator.sample_auxiliary(.11)


def test_coupled_energy_accounting_reads_previous_endpoint_without_another_rk4(coupled):
    reference = coupled.clone_for_prediction()
    old = reference.integrator
    def recompute_auxiliary(t):
        if abs(t-old.t) < 1e-10:
            return old.auxiliary_state
        start, state = old.previous
        return old.step(start, state, old.previous_auxiliary_state, max(0, t-start))[1]
    old.sample_auxiliary = recompute_auxiliary
    integrator = coupled.integrator
    original = integrator.coupled_step
    steps = []
    def step(t, ship, auxiliary, dt):
        steps.append(dt)
        return original(t, ship, auxiliary, dt)
    integrator.coupled_step = step
    coupled.advance(.4)
    assert len(steps) == integrator.steps
    assert min(steps) > 0
    assert coupled.t == pytest.approx(.4)
    reference.advance(.4)
    assert integrator.state == old.state
    assert integrator.auxiliary_state == old.auxiliary_state
    assert coupled.work == reference.work
    assert coupled.dissipated == reference.dissipated
    assert coupled.transitions == reference.transitions


def forecast(model, horizon=1):
    return prediction.predict_motion(model, MotionPredictionRequest(horizon_s=horizon, sample_interval_s=.25),
        session_id="session", run_id="run", sequence=1, scene_id="scene", scene_revision="revision")


def test_prediction_cooperatively_yields_without_changing_complete_output(coupled, monkeypatch):
    before = prediction.snapshot_hash(coupled)
    monkeypatch.setattr(prediction.time, "monotonic", lambda: 0)
    expected = forecast(coupled)
    wall = [0.0]
    sleeps = []
    def monotonic():
        wall[0] += .002
        return wall[0]
    def sleep(duration):
        sleeps.append(duration)
        wall[0] += duration
    monkeypatch.setattr(prediction.time, "monotonic", monotonic)
    monkeypatch.setattr(prediction.time, "sleep", sleep)
    actual = forecast(coupled)
    assert sleeps and set(sleeps) == {prediction.YIELD_SLEEP_S}
    assert actual == expected
    assert prediction.snapshot_hash(coupled) == before


def test_prediction_runtime_budget_includes_time_given_to_live_work(coupled, monkeypatch):
    wall = [0.0]
    def monotonic():
        wall[0] += .002
        return wall[0]
    def sleep(_):
        wall[0] += prediction.MAX_RUNTIME_S
    monkeypatch.setattr(prediction.time, "monotonic", monotonic)
    monkeypatch.setattr(prediction.time, "sleep", sleep)
    result = forecast(coupled)
    assert not result.complete and 0 < result.horizon_s < 1
    assert "PREDICTION_RUNTIME_LIMIT" in {r.code for r in result.validity.reasons}
    assert coupled.t == 0
