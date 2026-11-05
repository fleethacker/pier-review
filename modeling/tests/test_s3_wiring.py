"""S3 wiring: tug geometry/slew and vertical state inside BerthingModel and rich rm0-v1 frames."""
import pytest

from mooring import refdata, scenarios
from mooring.berthing import rich, simulator as sim
from mooring.core.schemas import ForcingSpec, Scenario, ShipState, SimTugCommandMessage
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship


@pytest.fixture
def setup(monkeypatch):
    ship, berth, spec = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
    monkeypatch.setattr(refdata, "ship", lambda _: ship.model_copy(deep=True))
    monkeypatch.setattr(refdata, "berth", lambda _: berth.model_copy(deep=True))
    monkeypatch.setattr(refdata, "line", lambda _: spec.model_copy(deep=True))
    sc = Scenario.model_validate({**EXAMPLES["scenario"], "scenario_id": "test-s3", "created_at_utc": "2026-01-01T00:00:00Z",
        "ship_class_id": ship.class_id, "berth_id": berth.berth_id, "side_to": "starboard", "config": breast_config(standoff=11)})
    env = calm_env()
    monkeypatch.setattr(scenarios, "get", lambda _: sc.model_copy(deep=True))
    monkeypatch.setattr(scenarios, "environment_for", lambda _: env.model_copy(deep=True))
    return sc, ShipState(x_ft=400, y_ft=41, heading_true_deg=90, v_kt=0.5), env


def cmd(direction=90, force=10000, t=0, tug="T1"):
    return SimTugCommandMessage(type="tug_command", t_s=t, tug_id=tug, force_lbf=force, direction_rel_deg=direction)


def frame(m, **kw):
    scene = rich.build_scene(m)
    return rich.rich_frame(m, session_id="S", run_id="R", sequence=1, scene=scene, **kw)


def test_tug_slew_matches_linear_ramp_and_wrench(setup):
    m = sim.BerthingModel(*setup, duration=10)
    m.schedule(cmd(90, 10000)); m.apply_pending()
    tug, pp, (lo, hi) = m.anchors["T1"]
    rate = max(abs(lo), abs(hi)) / sim.SLEW_SECONDS
    assert m.tug_force("T1", 0.2) == pytest.approx(-rate * 0.2)
    assert m.tug_force("T1", 9.0) == pytest.approx(-10000)
    assert m.tug_wrench(9.0) == pytest.approx((0.0, -10000, -10000 * pp.x_ft))


def test_tug_validation_unchanged(setup):
    m = sim.BerthingModel(*setup, duration=10)
    with pytest.raises(ValueError, match="normal hull forces"):
        m.schedule(cmd(45))
    with pytest.raises(ValueError, match="rating exceeded"):
        m.schedule(cmd(90, 1e12))
    with pytest.raises(ValueError, match="push-point assignment"):
        m.schedule(cmd(90, tug="nope"))


def test_heave_unavailable_without_forcing(setup):
    m = sim.BerthingModel(*setup, duration=5)
    mo = frame(m).motion
    assert mo.pose.heave_mllw_ft is None
    assert mo.dofs.heave == "not_simulated" and mo.dofs.roll == "not_simulated" and mo.dofs.pitch == "not_simulated"


def test_heave_follows_tide_with_forcing(setup):
    env = setup[2]
    m = sim.BerthingModel(*setup, duration=20, forcing=ForcingSpec(kind="steady", tide_amplitude_ft=3, tide_period_s=40))
    m.set_env(10.0, m.integrator.state)
    fr = frame(m, state=m.integrator.state, t=10.0)
    assert fr.motion.pose.heave_mllw_ft == pytest.approx(env.water_level_mllw_ft + 3.0)
    assert fr.motion.dofs.heave == "prescribed"
    assert fr.motion.dofs.roll == "not_simulated" and fr.motion.pose.roll_deg is None
    assert all(t.position is None for t in fr.tug_states)
