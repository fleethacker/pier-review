"""S2 simulation-time forcing: synthetic series, stage-time resolution, batch/interactive equivalence."""
from dataclasses import fields

import pytest
from pydantic import ValidationError

from mooring import refdata, scenarios
from mooring.berthing import simulator as sim
from mooring.berthing.forcing import ForcingSeries, ForcingUncovered, apparent_wind
from mooring.core.schemas import (BerthingSimRequest, ForcingSpec, Scenario, ShipState, SimControlMessage,
                                  SimLineEventMessage, SimTugCommandMessage)
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship
from modeling_api.sim_sessions import Session


class Clock:
    now = 0.0
    def __call__(self): return self.now


@pytest.fixture
def setup(monkeypatch):
    ship, berth, spec = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
    monkeypatch.setattr(refdata, "ship", lambda _: ship.model_copy(deep=True))
    monkeypatch.setattr(refdata, "berth", lambda _: berth.model_copy(deep=True))
    monkeypatch.setattr(refdata, "line", lambda _: spec.model_copy(deep=True))
    sc = Scenario.model_validate({**EXAMPLES["scenario"], "scenario_id": "test-s2", "created_at_utc": "2026-01-01T00:00:00Z",
        "ship_class_id": ship.class_id, "berth_id": berth.berth_id, "side_to": "starboard", "config": breast_config(standoff=11)})
    env = calm_env()
    initial = ShipState(x_ft=400, y_ft=41, heading_true_deg=90, v_kt=0.5)
    monkeypatch.setattr(scenarios, "get", lambda _: sc.model_copy(deep=True))
    monkeypatch.setattr(scenarios, "environment_for", lambda _: env.model_copy(deep=True))
    return sc, initial, env


def ramp_spec(**kw):
    return ForcingSpec(kind="ramp", ramp_start_s=0, target={"t_s": 4, "wind_speed_kt": 25, "wind_gust_kt": 30,
                       "wind_from_true_deg": 200}, tide_amplitude_ft=2, tide_period_s=20, **kw)


def test_batch_matches_interactive_with_forcing(setup):
    sc, initial, env = setup
    forcing = ramp_spec(vessel_relative_wind=True)
    req = BerthingSimRequest(scenario_id=sc.scenario_id, initial_state=initial, duration_s=5, sample_interval_s=0.2,
                             forcing=forcing, line_events=[{"t_s": 0, "line_number": 1, "event": "secured"}],
                             tug_commands=[{"t_s": 1, "tug_id": "T1", "force_lbf": 10000, "direction_rel_deg": 90}])
    response = sim.simulate_berthing(req, "s2-eq", "/api/v1")
    frames = sim.SERIES["s2-eq"].frames
    clock = Clock()
    session = Session(sim.BerthingModel(*setup, duration=5, forcing=forcing), clock=clock)
    session.attach("c")
    session.receive("c", SimTugCommandMessage(type="tug_command", t_s=1, tug_id="T1", force_lbf=10000, direction_rel_deg=90))
    session.receive("c", SimLineEventMessage(type="line_event", t_s=0, line_number=1, event="secured"))
    for i in range(1, 26):
        clock.now = i*0.2
        session.tick()
        f = session.latest
        assert f.pose.model_dump() == pytest.approx(frames[i].pose.model_dump(), abs=1e-9)
        assert f.forcing_revision == frames[i].forcing_revision == response.result.forcing_revision
        assert f.environment.wind.speed_kt == pytest.approx(frames[i].environment.wind.speed_kt, abs=1e-9)
        assert f.environment.water.level_mllw_ft == pytest.approx(frames[i].environment.water.level_mllw_ft, abs=1e-12)
    assert response.result.diagnostics.integration_steps == session.model.integrator.steps
    # The forcing varies in time (environment at t, not frozen at session start).
    assert frames[0].environment.wind.speed_kt != frames[-1].environment.wind.speed_kt
    assert frames[-1].environment.t_s == frames[-1].t_s


def test_default_request_is_unchanged(setup):
    sc, initial, _ = setup
    req = BerthingSimRequest(scenario_id=sc.scenario_id, initial_state=initial, duration_s=2)
    assert "forcing" not in req.model_dump(mode="json")
    response = sim.simulate_berthing(req, "s2-default", "/api/v1")
    assert "forcing_revision" not in response.result.model_dump(mode="json")
    f = sim.SERIES["s2-default"].frames[0].model_dump(mode="json")
    assert "forcing_revision" not in f and "environment" not in f
    steady = sim.simulate_berthing(req.model_copy(update={"forcing": ForcingSpec(kind="steady")}), "s2-steady", "/api/v1")
    a, b = sim.SERIES["s2-default"].frames, sim.SERIES["s2-steady"].frames
    assert [x.pose for x in a] == [x.pose for x in b]
    assert steady.result.forcing_revision.startswith("frc-")


def test_gusts_deterministic_by_seed(setup):
    env = setup[2].model_copy(update={"wind_speed_kt": 15, "wind_gust_kt": 20})
    mk = lambda seed: ForcingSeries(ForcingSpec(kind="gusts", seed=seed, gust_sigma_kt=4, gust_correlation_s=2), env, 60)
    a, b, c = mk(7), mk(7), mk(8)
    times = [0, 0.3, 7.7, 31.1, 59.9, 60]
    assert [a.at(t)[0].wind_speed_kt for t in times] == [b.at(t)[0].wind_speed_kt for t in times]
    assert a.revision == b.revision != c.revision
    assert [a.at(t)[0].wind_speed_kt for t in times] != [c.at(t)[0].wind_speed_kt for t in times]
    # Pure function of time: evaluation order does not matter.
    assert [a.at(t)[0].wind_speed_kt for t in reversed(times)] == [b.at(t)[0].wind_speed_kt for t in reversed(times)]
    assert a.at(0)[0].wind_speed_kt == 15 and a.synthetic
    assert all(a.at(t)[0].wind_gust_kt >= a.at(t)[0].wind_speed_kt >= 0 for t in times)
    with pytest.raises(ValidationError):
        ForcingSpec(kind="gusts")


def test_tide_changes_depth_and_geometry_not_paid_out_length(setup):
    env = setup[2]
    m = sim.BerthingModel(*setup, duration=20, forcing=ForcingSpec(kind="steady", tide_amplitude_ft=3, tide_period_s=40))
    m.schedule(SimLineEventMessage(type="line_event", t_s=0, line_number=1, event="secured"))
    m.apply_pending()
    rec = m.all_lines[1]
    snap = lambda: {f.name: getattr(rec.model, f.name) for f in fields(rec.model)}
    rest_before = snap()
    state = m.integrator.state
    pose = m.body.pose(state)
    m.set_env(0.0, state)
    depth0, len0 = m.system.depth_ft(pose), m.system.line_state(rec, pose).length_ft
    m.set_env(10.0, state)
    depth1, len1 = m.system.depth_ft(pose), m.system.line_state(rec, pose).length_ft
    assert depth1 - depth0 == pytest.approx(3.0)   # quarter period of a 3 ft amplitude
    assert len1 != len0                            # geometry follows the water level
    assert snap() == rest_before       # paid-out (unstretched) length untouched
    assert m.forcing.at(0)[0].water_level_mllw_ft == env.water_level_mllw_ft


def test_apparent_wind_only_wind_and_identity_when_stationary(setup):
    env = setup[2].model_copy(update={"wind_speed_kt": 10, "wind_gust_kt": 14, "wind_from_true_deg": 90, "current_speed_kt": 1})
    still = apparent_wind(env, 0, 0, 0)
    assert still.wind_speed_kt == pytest.approx(10) and still.wind_from_true_deg == pytest.approx(90)
    fps = 1.6878098571 * 10
    moving = apparent_wind(env, 0, fps, 0)   # heading north at 10 kt in an easterly beam wind
    assert moving.wind_speed_kt == pytest.approx(14.142, abs=1e-2) and moving.wind_from_true_deg == pytest.approx(45, abs=1e-6)
    assert moving.current_speed_kt == env.current_speed_kt  # current untouched: body damping owns water drag


@pytest.mark.parametrize("policy", ["stop", "invalidate"])
def test_uncovered_forcing_policy_batch(setup, policy):
    sc, initial, _ = setup
    forcing = ForcingSpec(kind="replay", on_uncovered=policy, samples=[
        {"t_s": 0, "water_level_mllw_ft": 0.0}, {"t_s": 2, "water_level_mllw_ft": 1.0}])
    req = BerthingSimRequest(scenario_id=sc.scenario_id, initial_state=initial, duration_s=5, sample_interval_s=0.5, forcing=forcing)
    r = sim.simulate_berthing(req, "s2-unc-"+policy, "/api/v1")
    codes = {x.code for x in r.validity.reasons}
    frames = sim.SERIES["s2-unc-"+policy].frames
    assert "FORCING_UNCOVERED" in codes and r.validity.state == "invalid" and r.status == "RED"
    if policy == "stop":
        assert r.result.diagnostics.simulated_time_s < 3   # never integrated on invented forcing
    else:
        assert frames[-1].t_s == pytest.approx(5)
        assert frames[-1].environment.water.level_mllw_ft == pytest.approx(1.0)    # held, flagged invalid
        assert frames[-1].environment.water.validity.state == "invalid"


def test_uncovered_forcing_session_and_start(setup):
    forcing = ForcingSpec(kind="replay", samples=[{"t_s": 0, "water_level_mllw_ft": 0}, {"t_s": 1, "water_level_mllw_ft": 0.5}])
    clock = Clock()
    session = Session(sim.BerthingModel(*setup, duration=5, forcing=forcing), clock=clock)
    session.attach("c")
    clock.now = 3.0
    for _ in range(10):
        session.tick()
    assert session.error and any(r.code == "FORCING_UNCOVERED" for r in session.model.reasons)
    late = ForcingSpec(kind="replay", samples=[{"t_s": 5, "water_level_mllw_ft": 0}, {"t_s": 9, "water_level_mllw_ft": 0.5}])
    with pytest.raises(ForcingUncovered):
        sim.BerthingModel(*setup, duration=8, forcing=late)


def test_replay_missing_channel_is_unavailable_not_zero(setup):
    forcing = ForcingSpec(kind="replay", samples=[{"t_s": 0, "water_level_mllw_ft": 0}, {"t_s": 9, "water_level_mllw_ft": 1}])
    m = sim.BerthingModel(*setup, duration=5, forcing=forcing)
    env = m.frame().environment
    assert env.water.availability == "available" and env.water.provenance.kind == "unknown"
    assert env.wind.availability == "unavailable" and env.wind.speed_kt is None
    assert env.current.availability == "unavailable" and env.current.set_true_deg is None
    assert not m.forcing.synthetic
    with pytest.raises(ValidationError):
        ForcingSpec(kind="replay", samples=[{"t_s": 0, "water_level_mllw_ft": 0}, {"t_s": 1}])


def test_synthetic_labeled_and_reset_keeps_series(setup):
    clock = Clock()
    session = Session(sim.BerthingModel(*setup, duration=3, forcing=ramp_spec()), clock=clock)
    session.attach("c")
    rev = session.latest.forcing_revision
    assert session.latest.environment.wind.provenance.kind == "mock"
    session.receive("c", SimControlMessage(type="reset"))
    assert session.latest.forcing_revision == rev and session.model.t == 0
