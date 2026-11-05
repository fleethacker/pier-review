"""S1: rm0-v1 frames and scene from actual BerthingModel state. Offline, deterministic, synthetic fixtures."""
import math

import pytest

from mooring import refdata, scenarios
from mooring.berthing import rich, simulator as sim
from mooring.core.geometry import PIER_FITTING_HEIGHT_FT
from mooring.core.schemas import (Scenario, ShipState, SimFrame, SimLineEventMessage, SimScene,
                                  SimTugCommandMessage)
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship


@pytest.fixture
def setup(monkeypatch):
    ship, berth, spec = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
    monkeypatch.setattr(refdata, "ship", lambda _: ship.model_copy(deep=True))
    monkeypatch.setattr(refdata, "berth", lambda _: berth.model_copy(deep=True))
    monkeypatch.setattr(refdata, "line", lambda _: spec.model_copy(deep=True))
    def scenario(config):
        return Scenario.model_validate({**EXAMPLES["scenario"], "scenario_id": "test-rich",
            "created_at_utc": "2026-01-01T00:00:00Z", "ship_class_id": ship.class_id, "berth_id": berth.berth_id,
            "side_to": "starboard", "config": config})
    sc = scenario(breast_config(standoff=11))
    env = calm_env()
    initial = ShipState(x_ft=400, y_ft=41, heading_true_deg=90, v_kt=0.5)
    monkeypatch.setattr(scenarios, "get", lambda _: sc.model_copy(deep=True))
    monkeypatch.setattr(scenarios, "environment_for", lambda _: env.model_copy(deep=True))
    return sc, initial, env, scenario


def tug(direction, force=10000, t=0):
    return SimTugCommandMessage(type="tug_command", t_s=t, tug_id="T1", force_lbf=force, direction_rel_deg=direction)


def secure_all(m):
    for n in m.all_lines:
        m.schedule(SimLineEventMessage(type="line_event", t_s=0, line_number=n, event="secured"))


def make(setup, **kw):
    sc, initial, env, _ = setup
    m = sim.BerthingModel(sc, initial.model_copy(update=kw.pop("update", {})), env, duration=30)
    return m


def frame_of(m, **kw):
    scene = rich.build_scene(m)
    return rich.rich_frame(m, session_id="S", run_id="R", sequence=7, scene=scene, **kw), scene


def contact_model(setup):
    """Yawed 1 degree at y=41 ft: lines secured and taut, one fender compressed, a tug mid-ramp."""
    m = make(setup, update={"y_ft": 41, "v_kt": 0, "heading_true_deg": 91})
    secure_all(m)
    m.schedule(tug(90, 50_000))
    m.advance(0.2)
    return m


def test_validates_round_trips_and_keeps_legacy_fields(setup):
    m = make(setup)
    m.schedule(tug(90)); m.advance(2)
    frame, _ = frame_of(m, alerts=["a legacy alert"])
    assert SimFrame.model_validate_json(frame.model_dump_json()) == frame
    legacy = m.frame(alerts=["a legacy alert"])
    for name in ("t_s", "pose", "tugs", "lines", "fenders", "alerts", "validity"):
        assert getattr(frame, name) == getattr(legacy, name)
    assert (frame.schema_version, frame.sequence, frame.session_id, frame.run_id) == ("rm0-v1", 7, "S", "R")
    scene_id, revision = rich.scene_id_for(m)
    assert (frame.scene_id, frame.scene_revision) == (scene_id, revision)
    assert frame.provenance.kind == "estimated" and frame.validity.state == "limited"
    assert [a.code for a in frame.structured_alerts] == ["SIMULATION_ALERT", "SYNTHETIC_DYNAMICS"]
    assert frame.structured_alerts[1].severity == "INFO"


def test_motion_dofs_and_heave_null(setup):
    m = make(setup, update={"v_kt": 0.4})
    m.advance(1)
    frame, _ = frame_of(m)
    s = m.integrator.state
    mo = frame.motion
    assert (mo.pose.x_ft, mo.pose.y_ft, mo.pose.yaw_deg) == (s[0], s[1], math.degrees(s[2]))
    assert (mo.velocity.surge_fps, mo.velocity.sway_fps, mo.velocity.yaw_degps) == (s[3], s[4], math.degrees(s[5]))
    assert (mo.dofs.surge, mo.dofs.sway, mo.dofs.yaw) == ("simulated",) * 3
    assert (mo.dofs.heave, mo.dofs.roll, mo.dofs.pitch) == ("not_simulated",) * 3
    assert mo.pose.heave_mllw_ft is None and mo.pose.roll_deg is None and mo.velocity.heave_fps is None
    assert mo.acceleration.heave_fps2 is None
    # Sway velocity is +port; legacy v_kt (toward the pier) flips sign for starboard-side berthing.
    assert mo.velocity.sway_fps == pytest.approx(-frame.pose.v_kt * 1.6878098571, rel=1e-6)


@pytest.mark.parametrize("direction", [90, 270])
def test_tug_force_and_moment_signs(setup, direction):
    m = make(setup, update={"heading_true_deg": 91})   # non-zero yaw so the rotation is exercised
    m.schedule(tug(direction, 10000)); m.advance(10)    # ramp (5 s) completed
    frame, _ = frame_of(m)
    psi = m.integrator.state[2]
    f_body = -10000.0 if direction == 90 else 10000.0   # signed ship-body +y force at the port push point
    expected = (-math.sin(psi) * f_body, math.cos(psi) * f_body)
    ts = frame.tug_states[0]
    assert (ts.actual_force.x_lbf, ts.actual_force.y_lbf) == pytest.approx(expected, rel=1e-9)
    assert (ts.commanded_force.x_lbf, ts.commanded_force.y_lbf) == pytest.approx(expected, rel=1e-9)
    assert ts.mode == ("push" if direction == 90 else "pull")
    assert ts.contact_state == ("contact" if direction == 90 else "line_made_up")
    assert ts.position is None and ts.velocity is None and ts.acceleration is None and ts.heading_true_deg is None
    pp = m.anchors["T1"][1]
    assert ts.push_point_id == pp.push_point_id
    px, py = m.system.frame.to_berth(pp.x_ft, m.ship.beam_ft / 2, m.body.pose(m.integrator.state))
    assert (ts.contact_position.x_ft, ts.contact_position.y_ft) == pytest.approx((px, py))
    assert frame.forces.tugs.yaw_moment_ftlbf == pytest.approx(pp.x_ft * f_body)
    assert ts.capacity_utilization_pct == pytest.approx(100 * 10000 / (m.anchors["T1"][2][0] * -1 if direction == 90 else m.anchors["T1"][2][1]))


def test_force_breakdown_sums_to_integrator_total(setup):
    m = contact_model(setup)
    s = m.integrator.state
    frame, _ = frame_of(m)
    assert any(l.status == "taut" for l in frame.line_states)
    assert any(f.reaction_lbf > 0 for f in frame.fender_states)
    X, Y, N = m.forces(m.t, s)
    c, sn = math.cos(s[2]), math.sin(s[2])
    total = (c * X - sn * Y, sn * X + c * Y, N)
    f = frame.forces
    parts = [f.wind, f.current, f.tugs, f.lines, f.fenders]
    got = (sum(p.force.x_lbf for p in parts), sum(p.force.y_lbf for p in parts), sum(p.yaw_moment_ftlbf for p in parts))
    assert got == pytest.approx(total, rel=1e-9, abs=1e-6)


def test_force_breakdown_with_wind_and_current(setup):
    sc, initial, env, _ = setup
    env = env.model_copy(update={"wind_speed_kt": 25, "wind_gust_kt": 30, "wind_from_true_deg": 200,
                                 "current_speed_kt": 1.0, "current_set_true_deg": 30})
    m = sim.BerthingModel(sc, initial.model_copy(update={"y_ft": 36, "v_kt": 0, "heading_true_deg": 93}), env, duration=30)
    secure_all(m); m.schedule(tug(90, 100_000)); m.advance(4)
    frame, _ = frame_of(m)
    assert frame.forces.wind.force.x_lbf != 0 or frame.forces.wind.force.y_lbf != 0
    s = m.integrator.state
    X, Y, N = m.forces(m.t, s)
    c, sn = math.cos(s[2]), math.sin(s[2])
    f = frame.forces
    parts = [f.wind, f.current, f.tugs, f.lines, f.fenders]
    assert (sum(p.force.x_lbf for p in parts), sum(p.force.y_lbf for p in parts), sum(p.yaw_moment_ftlbf for p in parts)) \
        == pytest.approx((c * X - sn * Y, sn * X + c * Y, N), rel=1e-9, abs=1e-6)
    assert frame.environment.wind.metadata == env.metadata and frame.environment.wind.speed_kt == 25


def test_line_geometry_and_fitting_loads(setup):
    m = contact_model(setup)
    frame, _ = frame_of(m)
    pose = m.body.pose(m.integrator.state)
    by_number = {r.ln.line_number: r for r in m.system.lines}
    assert [l.line_number for l in frame.line_states] == [l.line_number for l in frame.lines]
    for ls in frame.line_states:
        rec = by_number[ls.line_number]
        bitt = next(f for f in m.ship.fittings if f.fitting_id == ls.ship_fitting_id)
        bx, by = m.system.frame.to_berth(bitt.x_ft, bitt.y_ft, pose)
        lx, ly = m.system.frame.to_berth(rec.lead_xy[0], rec.lead_xy[1], pose)
        assert (ls.ship_end.x_ft, ls.ship_end.y_ft) == pytest.approx((bx, by))
        assert ls.ship_end.z_mllw_ft == pytest.approx(m.env.water_level_mllw_ft + bitt.z_ft)
        assert (ls.pier_end.x_ft, ls.pier_end.y_ft, ls.pier_end.z_mllw_ft) == pytest.approx(rec.pier_xyz)
        assert ls.pier_end.z_mllw_ft == pytest.approx(m.berth.deck_height_mllw_ft + PIER_FITTING_HEIGHT_FT)
        assert ls.chock_id == bitt.paired_chock_id
        assert len(ls.polyline) == 3 and ls.polyline[0] == ls.ship_end and ls.polyline[-1] == ls.pier_end
        assert (ls.polyline[1].x_ft, ls.polyline[1].y_ft) == pytest.approx((lx, ly))
        assert ls.polyline[1].z_mllw_ft == pytest.approx(m.env.water_level_mllw_ft + rec.lead_height_ft)
        assert ls.status in ("slack", "taut") and (ls.status == "slack") == (ls.tension_lbf == 0)
        assert ls.ship_fitting_id == rec.ln.ship_fitting_id and ls.pier_fitting_id == rec.ln.pier_fitting_id
    # The external line segment establishes pier loads and the ship's total wrench, but does not establish
    # each redirected ship fitting reaction (inner-segment tension/friction is not modeled).
    for fl in frame.fitting_loads:
        assert fl.status is None
        if fl.owner == "ship":
            assert fl.availability == "unavailable" and fl.load_lbf is None and fl.force is None
            assert fl.utilization_pct is None and fl.validity.reasons[0].code == "ROUTING_REACTION_UNMODELED"
            continue
        assert fl.load_lbf == pytest.approx(math.sqrt(fl.force.x_lbf**2 + fl.force.y_lbf**2 + fl.force.z_lbf**2))
        assert fl.utilization_pct == pytest.approx(100 * fl.load_lbf / fl.capacity_lbf)
    ships = {f.fitting_id: f for f in frame.fitting_loads if f.owner == "ship"}
    piers = {f.fitting_id: f for f in frame.fitting_loads if f.owner == "pier"}
    assert ships and piers
    assert frame.forces.lines.force.y_lbf == pytest.approx(-sum(f.force.y_lbf for f in piers.values()))
    assert sum(l.tension_lbf for l in frame.line_states) > 0


def test_fender_reaction_under_contact(setup):
    m = contact_model(setup)
    frame, _ = frame_of(m)
    assert len(frame.fender_states) == len(m.system.fenders)
    contact = [f for f in frame.fender_states if f.compression_ft > 0]
    assert contact
    for fs in contact:
        model = next(fr.model for fr in m.system.fenders if fr.model.fender_id == fs.fender_id)
        assert fs.reaction_lbf == pytest.approx(model.force(fs.compression_ft)) and fs.reaction_lbf > 0
        assert (fs.force.x_lbf, fs.force.y_lbf) == (0.0, fs.reaction_lbf)
        assert fs.status in ("AMBER", "RED")
    assert frame.forces.fenders.force.y_lbf == pytest.approx(sum(f.reaction_lbf for f in frame.fender_states))
    assert frame.forces.fenders.force.y_lbf > 0
    for fs in frame.fender_states:
        if fs.compression_ft == 0:
            assert fs.reaction_lbf == 0


def test_direct_bitt_leads_still_report_resolved_fitting_loads(setup, monkeypatch):
    ship = refdata.ship(setup[0].ship_class_id)
    for fitting in ship.fittings:
        fitting.paired_chock_id = None
    monkeypatch.setattr(refdata, "ship", lambda _: ship.model_copy(deep=True))
    model = contact_model(setup)
    frame, _ = frame_of(model)
    assert all(line.chock_id is None and len(line.polyline) == 2 for line in frame.line_states)
    assert all(load.availability == "available" and load.force is not None for load in frame.fitting_loads)
    ship_force = [sum(getattr(load.force, axis) for load in frame.fitting_loads if load.owner == "ship")
                  for axis in ("x_lbf", "y_lbf", "z_lbf")]
    pier_force = [sum(getattr(load.force, axis) for load in frame.fitting_loads if load.owner == "pier")
                  for axis in ("x_lbf", "y_lbf", "z_lbf")]
    assert ship_force == pytest.approx([-force for force in pier_force])


def test_waves_unavailable_not_zero(setup):
    m = make(setup)
    frame, _ = frame_of(m)
    for container in (frame.environment.waves, frame.forces.waves):
        for name in rich.WAVE_NAMES:
            c = getattr(container, name)
            assert c.availability == "unavailable" and c.validity.state == "unknown"
            assert c.validity.reasons[0].code == "WAVE_SOURCE_UNAVAILABLE"
    w = frame.environment.waves.ocean_swell
    assert w.height_ft is None and w.period_s is None
    assert frame.forces.waves.ship_wake.force is None and frame.forces.waves.ship_wake.yaw_moment_ftlbf is None
    assert frame.environment.t_s == frame.t_s and frame.environment.valid_at_utc is None


def test_state_and_time_arguments_do_not_advance_the_model(setup):
    m = make(setup)
    m.schedule(tug(90)); m.advance(2)
    t0, state0 = m.t, m.integrator.state
    frame, scene = frame_of(m, state=m.integrator.sample(m.t - 0.01), t=m.t - 0.01)
    assert frame.t_s == t0 - 0.01 and frame.environment.t_s == t0 - 0.01
    assert (m.t, m.integrator.state) == (t0, state0)


def test_scene_is_deterministic_and_content_addressed(setup):
    m1, m2 = make(setup), make(setup)
    a, b = rich.build_scene(m1), rich.build_scene(m2)
    assert a == b and a.scene_id == b.scene_id == rich.scene_id_for(m1)[0]
    assert a.scene_id.startswith("scene_") and len(a.scene_id) == len("scene_") + 16 and a.revision == "1"
    other = breast_config(standoff=11, pairs=(2, 3))
    sc, initial, env, scenario = setup
    m3 = sim.BerthingModel(scenario(other), initial, env, duration=30)
    assert rich.scene_id_for(m3)[0] != a.scene_id
    m4 = sim.BerthingModel(sc, initial, env, duration=30)
    m4.system.frame = m4.system.frame.__class__(m4.system.frame.side_to, m4.system.frame.ref_x_ft + 50, m4.system.frame.ref_y_ft)
    assert rich.scene_id_for(m4)[0] != a.scene_id


def test_scene_content_and_validation(setup):
    m = make(setup)
    scene = rich.build_scene(m)
    assert SimScene.model_validate_json(scene.model_dump_json()) == scene
    assert scene.face_bearing_true_deg == m.berth.face_bearing_true_deg
    assert scene.deck_height_mllw_ft == m.berth.deck_height_mllw_ft
    assert scene.berth_outline == []
    assert any("berth_outline is empty" in n for n in scene.provenance.notes)
    assert len(scene.ship_hull_outline) >= 5 and all(p.z_ft == 0 for p in scene.ship_hull_outline)
    assert scene.provenance.kind == "estimated" and scene.validity.state == "limited"
    fittings = {f.fitting_id: f for f in scene.ship_fittings}
    bitt = next(f for f in m.ship.fittings if f.kind == "bitt")
    assert (fittings[bitt.fitting_id].position.x_ft, fittings[bitt.fitting_id].position.z_ft) == (bitt.x_ft, bitt.z_ft)
    assert fittings[bitt.fitting_id].capacity_lbf == bitt.swl_lbf
    pushes = [f for f in scene.ship_fittings if f.kind == "tug_push_point"]
    assert len(pushes) == len(m.ship.push_points) and all(abs(p.position.y_ft) == m.ship.beam_ft / 2 for p in pushes)
    assert all(p.position.z_ft is None for p in pushes)
    pf = {f.fitting_id: f for f in scene.pier_fittings}
    for f in m.berth.fittings:
        assert pf[f.fitting_id].capacity_lbf == f.capacity_nominal_lbf
        assert pf[f.fitting_id].position.z_mllw_ft == m.berth.deck_height_mllw_ft + PIER_FITTING_HEIGHT_FT
    fenders = {f.fender_id: f for f in scene.fenders}
    for f in m.berth.fenders:
        assert (fenders[f.fender_id].length_ft, fenders[f.fender_id].standoff_ft) == (f.length_ft, f.standoff_ft)
        assert fenders[f.fender_id].position.y_ft == 0 and fenders[f.fender_id].position.z_mllw_ft is None
    assert [(d.position.x_ft, d.depth_mllw_ft) for d in scene.depth_profile] == [(0, 40), (800, 40)]
    for el in (*scene.ship_fittings, *scene.pier_fittings, *scene.fenders, *scene.depth_profile):
        assert el.availability == "available" and el.provenance.kind == "estimated"
        assert el.validity.reasons[0].code == "SEED_REFERENCE_DATA"


def test_acceleration_is_inertial_in_ship_axes(setup):
    """Independent check: rotate body velocity into berth axes at t and t+h, difference, rotate back at t."""
    from mooring.mechanics.dynamics import rk4
    m = make(setup)
    secure_all(m)
    m.advance(0.5)
    s = (m.integrator.state[0], m.integrator.state[1], math.radians(7.0), 0.8, -0.6, 0.05)
    t, h = m.t, 1e-4
    frame, _ = frame_of(m, state=s, t=t)
    s2 = rk4(m.params, m.forces, t, s, h)

    def berth_vel(st):
        c, sn = math.cos(st[2]), math.sin(st[2])
        return (st[3] * c - st[4] * sn, st[3] * sn + st[4] * c)
    (vx0, vy0), (vx1, vy1) = berth_vel(s), berth_vel(s2)
    ax, ay = (vx1 - vx0) / h, (vy1 - vy0) / h
    c, sn = math.cos(s[2]), math.sin(s[2])
    a_surge, a_sway = c * ax + sn * ay, -sn * ax + c * ay
    yaw_acc = math.degrees((s2[5] - s[5]) / h)
    acc = frame.motion.acceleration
    assert acc.surge_fps2 == pytest.approx(a_surge, rel=1e-3, abs=1e-3)
    assert acc.sway_fps2 == pytest.approx(a_sway, rel=1e-3, abs=1e-3)
    assert acc.yaw_degps2 == pytest.approx(yaw_acc, rel=1e-3, abs=1e-3)
    # The rotation terms are material here, so this would fail with the raw body-frame derivatives.
    raw = rich._deriv(m.params, s, m.forces(t, s))
    assert abs(acc.surge_fps2 - raw[3]) > 1e-3 and abs(acc.sway_fps2 - raw[4]) > 1e-3


def test_released_and_unmade_lines_are_listed_unavailable(setup):
    m = make(setup)
    nums = sorted(m.all_lines)
    assert len(nums) >= 2
    first, second = nums[0], nums[1]
    for n in (first, second):
        m.schedule(SimLineEventMessage(type="line_event", t_s=0, line_number=n, event="secured"))
    m.schedule(SimLineEventMessage(type="line_event", t_s=0.5, line_number=first, event="released"))
    m.advance(1)
    frame, _ = frame_of(m)
    assert [l.line_number for l in frame.line_states] == nums
    by = {l.line_number: l for l in frame.line_states}
    for n in nums:
        rec = m.all_lines[n]
        assert (by[n].ship_fitting_id, by[n].pier_fitting_id) == (rec.ln.ship_fitting_id, rec.ln.pier_fitting_id)
    rel = by[first]
    assert rel.availability == "unavailable" and rel.status == "unknown" and rel.validity.state == "unknown"
    assert rel.tension_lbf is None and rel.ship_end is None and rel.pier_end is None and not rel.polyline
    assert rel.validity.reasons[0].code == "LINE_NOT_ACTIVE" and "released" in rel.validity.reasons[0].message
    assert by[second].availability == "available" and by[second].tension_lbf is not None
    for n in nums[2:]:   # never secured
        r = by[n]
        assert r.availability == "unavailable" and r.validity.reasons[0].code == "LINE_NOT_ACTIVE"
        assert "not yet made fast" in r.validity.reasons[0].message and r.tension_lbf is None
    # Fitting loads only for fittings carrying active lines; legacy lines are exactly the active ones.
    active_ids = {rec.ln.ship_fitting_id for rec in m.system.lines} | {rec.ln.pier_fitting_id for rec in m.system.lines}
    active_ids |= {l.chock_id for l in frame.line_states if l.chock_id is not None}
    assert {f.fitting_id for f in frame.fitting_loads} == active_ids
    assert frame.lines == m.frame().lines
    assert [l.line_number for l in frame.lines] == [second]
    assert SimFrame.model_validate_json(frame.model_dump_json()) == frame
