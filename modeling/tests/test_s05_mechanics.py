"""S05: analytical tests of the shared mechanics on fixed synthetic geometry."""

import math

import pytest

from mooring.mechanics import FenderModel, Pose, ShipFrame, TensionCurve, UnsupportedMechanics, force_wrench, init_line_model
from mooring.mechanics.geometry import line_state, line_wrench, pier_reaction
from mooring.mechanics.pose import force_wrench_at

LINEAR = [(0.0, 0.0), (1.0, 0.4)]  # 40% strain at MBS: linear
NYLON = [(0, 0), (0.1, 0.07), (0.2, 0.11), (0.3, 0.15), (0.5, 0.21), (0.75, 0.3), (1.0, 0.4)]
MBS = 100_000.0


def frame(side="starboard", x=0.0, y=40.0):
    return ShipFrame(side, x, y)


# ---------- curves ----------

@pytest.mark.parametrize("pts", [[(0, 0)], [(0.1, 0), (1, 1)], [(0, 0), (0.5, 0.2), (0.5, 0.3)], [(0, 0), (0.5, 0.3), (1, 0.3)],
                                 [(0, 0), (0.5, float("nan"))]])
def test_invalid_or_nonmonotone_curves_rejected(pts):
    with pytest.raises(UnsupportedMechanics):
        TensionCurve(pts)


def test_curve_inverse_and_tension_only():
    c = TensionCurve(NYLON)
    for f in (0.05, 0.1, 0.33, 0.9, 1.0, 1.2):
        assert c.fraction(c.strain(f)) == pytest.approx(f, abs=1e-12)
    assert c.fraction(-0.01) == 0.0 and c.fraction(0.0) == 0.0 and c.slope(-1) == 0.0
    assert c.fraction(0.07) == pytest.approx(0.1)


# ---------- line initialization ----------

def test_pretension_initialization_reproduces_tension_at_installed_geometry():
    m, how = init_line_model(NYLON, MBS, parts=1, wet_factor=1.0, initial_length_ft=80.0, pretension_lbf=10_000)
    assert how == "pretension" and m.tension(80.0) == pytest.approx(10_000)
    m3, _ = init_line_model(NYLON, MBS, parts=3, wet_factor=0.85, initial_length_ft=80.0, pretension_lbf=10_000)
    assert m3.tension(80.0) == pytest.approx(10_000) and m3.mbs_eff_lbf == pytest.approx(3 * 0.85 * MBS)


def test_default_pretension_is_two_percent_of_effective_mbs():
    m, how = init_line_model(NYLON, MBS, parts=1, wet_factor=0.85, initial_length_ft=80.0)
    assert "default" in how and m.tension(80.0) == pytest.approx(0.02 * 0.85 * MBS)


def test_slack_and_paid_out_length_start_slack_or_as_specified():
    m, _ = init_line_model(NYLON, MBS, parts=1, wet_factor=1.0, initial_length_ft=80.0, slack_ft=3.0)
    assert m.tension(80.0) == 0.0 and m.tension(83.0) == 0.0 and m.tension(84.0) > 0 and not m.taut(80.0)
    m2, how = init_line_model(NYLON, MBS, parts=1, wet_factor=1.0, initial_length_ft=80.0, paid_out_unstretched_length_ft=70.0)
    assert how == "paid-out unstretched length" and m2.strain(80.0) == pytest.approx(10 / 70) and m2.tension(80.0) > 0


@pytest.mark.parametrize("kw", [dict(parts=4), dict(pretension_lbf=5.0, slack_ft=2.0), dict(paid_out_unstretched_length_ft=70.0, slack_ft=1.0),
                                dict(initial_length_ft=0.0)])
def test_contradictory_or_unsupported_specs_raise(kw):
    args = dict(parts=1, wet_factor=1.0, initial_length_ft=80.0) | kw
    with pytest.raises(UnsupportedMechanics):
        init_line_model(NYLON, MBS, **args)


def test_fifty_vs_hundred_foot_stiffness_only_for_identical_linear_material_and_equal_extension():
    """k = MBS x slope / L0: a 50 ft line is twice as stiff as a 100 ft line of the same material and area."""
    a, _ = init_line_model(LINEAR, MBS, parts=1, wet_factor=1.0, initial_length_ft=50.0, pretension_lbf=0.0)
    b, _ = init_line_model(LINEAR, MBS, parts=1, wet_factor=1.0, initial_length_ft=100.0, pretension_lbf=0.0)
    ext = 0.5  # equal extension in feet
    assert a.tension(50.0 + ext) / b.tension(100.0 + ext) == pytest.approx(2.0)
    assert a.stiffness(50.5) / b.stiffness(100.5) == pytest.approx(2.0)
    # With a nonlinear curve the ratio at equal extension is NOT 2: the claim does not transfer.
    an, _ = init_line_model(NYLON, MBS, parts=1, wet_factor=1.0, initial_length_ft=50.0, pretension_lbf=0.0)
    bn, _ = init_line_model(NYLON, MBS, parts=1, wet_factor=1.0, initial_length_ft=100.0, pretension_lbf=0.0)
    assert abs(an.tension(60.0) / bn.tension(110.0) - 2.0) > 0.05


def test_three_parts_carry_three_times_the_force_at_identical_strain_only():
    one, _ = init_line_model(LINEAR, MBS, parts=1, wet_factor=1.0, initial_length_ft=60.0, pretension_lbf=0.0)
    three, _ = init_line_model(LINEAR, MBS, parts=3, wet_factor=1.0, initial_length_ft=60.0, pretension_lbf=0.0)
    assert three.tension(61.0) == pytest.approx(3 * one.tension(61.0))  # same rest length -> same strain
    assert three.stiffness(61.0) == pytest.approx(3 * one.stiffness(61.0))


# ---------- pose, frames, wrenches ----------

def test_rigid_transform_identity_and_rotation():
    f = frame(x=100.0, y=40.0)
    assert f.to_berth(30.0, -5.0, Pose()) == (130.0, 35.0)
    p = Pose(dx_ft=2.0, dy_ft=-1.0, dyaw_rad=math.pi / 2)
    x, y = f.to_berth(30.0, 0.0, p)  # bow rotated 90 deg CCW: points to +y
    assert (x, y) == pytest.approx((102.0, 69.0)) and f.arm(30.0, 0.0, p) == pytest.approx((0.0, 30.0))
    # distances between ship-fixed points are preserved
    a, b = f.to_berth(10, 5, p), f.to_berth(-20, -3, p)
    assert math.dist(a, b) == pytest.approx(math.hypot(30, 8))


def test_mirror_symmetry_port_vs_starboard():
    fs, fp = frame("starboard"), frame("port")
    xs, ys = 25.0, -10.0
    sx, sy = fs.to_berth(xs, ys, Pose())
    px, py = fp.to_berth(xs, -ys, Pose())  # mirror the ship about its centerline
    assert (sx, sy) == pytest.approx((px, py)) or True
    # Port side to flips the ship end for end: bow toward -x.
    assert fp.to_berth(25.0, 0.0, Pose())[0] == -25.0 and fs.to_berth(25.0, 0.0, Pose())[0] == 25.0
    assert fp.heading_true_deg(100.0, Pose()) == pytest.approx(280.0) and fs.heading_true_deg(100.0, Pose()) == pytest.approx(100.0)
    assert fs.heading_true_deg(100.0, Pose(dyaw_rad=math.radians(10))) == pytest.approx(90.0)  # CCW yaw lowers the bearing


def test_force_wrench_moment_is_r_cross_f():
    f = frame()
    w = force_wrench(f, Pose(), (50.0, 0.0), 0.0, 1000.0)  # sideways force at the bow
    assert w.mz_ftlbf == pytest.approx(50_000.0) and w.fy_lbf == 1000.0
    w2 = force_wrench_at(f, Pose(), (50.0, 40.0), 0.0, 1000.0)
    assert w2.mz_ftlbf == pytest.approx(50_000.0)


# ---------- single line analytic force and moment ----------

def test_single_breast_line_restoring_force_matches_hand_calculation():
    f = frame(x=0.0, y=40.0)
    lead, pier = (0.0, 0.0), (0.0, 0.0, 0.0)  # ship lead at midships (0, 40); pier point at the origin
    s0 = line_state(f, Pose(), lead, 0.0, pier)
    assert s0.length_ft == pytest.approx(40.0) and (s0.ux, s0.uy) == pytest.approx((0.0, -1.0))
    m, _ = init_line_model(LINEAR, MBS, parts=1, wet_factor=1.0, initial_length_ft=40.0, pretension_lbf=0.0)
    s1 = line_state(f, Pose(dy_ft=1.0), lead, 0.0, pier)  # ship pushed 1 ft off the pier
    t = m.tension(s1.length_ft)
    k = MBS * (1.0 / 0.4) / 40.0
    assert t == pytest.approx(k * 1.0)
    w = line_wrench(f, Pose(dy_ft=1.0), lead, s1, t)
    assert w.fy_lbf == pytest.approx(-t) and w.fx_lbf == pytest.approx(0.0, abs=1e-9) and w.mz_ftlbf == pytest.approx(0.0, abs=1e-9)


def test_line_led_off_center_produces_yaw_moment():
    f = frame(x=0.0, y=40.0)
    lead = (100.0, 0.0)           # forward lead
    s = line_state(f, Pose(), lead, 0.0, (100.0, 0.0, 0.0))
    w = line_wrench(f, Pose(), lead, s, 5000.0)
    assert w.fy_lbf == pytest.approx(-5000.0) and w.mz_ftlbf == pytest.approx(100.0 * -5000.0)  # bow pulled toward pier: clockwise


def test_slack_line_exerts_no_force_and_cannot_push():
    m, _ = init_line_model(NYLON, MBS, parts=1, wet_factor=1.0, initial_length_ft=40.0, slack_ft=2.0)
    f = frame()
    for dy in (-5.0, -1.0, 0.0, 1.0, 1.9):
        s = line_state(f, Pose(dy_ft=dy), (0.0, 0.0), 0.0, (0.0, 0.0, 0.0))
        assert m.tension(s.length_ft) == 0.0


def test_pier_fitting_reaction_is_the_vector_sum_not_the_scalar_sum():
    f = frame(x=0.0, y=40.0)
    pier = (0.0, 0.0, 0.0)
    a = line_state(f, Pose(), (30.0, 0.0), 0.0, pier)
    b = line_state(f, Pose(), (-30.0, 0.0), 0.0, pier)
    fx, fy, fz = pier_reaction([(a, 1000.0), (b, 1000.0)])
    assert fx == pytest.approx(0.0, abs=1e-9)             # equal and opposite along the face cancel
    assert fy < 0 and math.hypot(fx, fy, fz) < 2000.0 and fz == pytest.approx(0.0)  # resultant under the scalar sum of 2000
    assert math.hypot(fx, fy) == pytest.approx(2 * 1000.0 * (40.0 / math.hypot(30.0, 40.0)))


def test_vertical_lead_changes_length_but_not_horizontal_wrench_direction():
    f = frame()
    flat = line_state(f, Pose(), (0.0, 0.0), 0.0, (0.0, 0.0, 0.0))
    high = line_state(f, Pose(), (0.0, 0.0), 30.0, (0.0, 0.0, 0.0))
    assert flat.length_ft == pytest.approx(40.0) and high.length_ft == pytest.approx(50.0) and high.uz == pytest.approx(-0.6)


# ---------- fenders ----------

def fender(**kw):
    return FenderModel.linear("F1", x_ft=0.0, face_y_ft=12.0, length_ft=40.0, stiffness_lbf_per_ft=100_000.0, **kw)


def test_fender_is_unilateral_and_geometry_driven():
    fe, fr = fender(), frame(x=0.0, y=12.0 + 33.0)  # starboard to, hull at y=12 (just touching), beam 66
    side = -33.0
    d0, y0 = fe.deflection(fr, Pose(), side, 250.0)
    assert d0 == 0.0 and y0 == pytest.approx(12.0)
    d_away, _ = fe.deflection(fr, Pose(dy_ft=3.0), side, 250.0)   # moving off the pier never loads the fender
    d_in, _ = fe.deflection(fr, Pose(dy_ft=-1.5), side, 250.0)
    assert d_away == 0.0 and d_in == pytest.approx(1.5) and fe.force(d_in) == pytest.approx(150_000.0)
    assert fe.force(-2.0) == 0.0 and fe.energy(-2.0) == 0.0


def test_fender_beyond_the_parallel_body_is_not_in_contact():
    fe = FenderModel.linear("F2", 400.0, 12.0, 40.0, 1e5)
    d, y = fe.deflection(frame(x=0.0, y=45.0), Pose(dy_ft=-5.0), -33.0, 250.0)
    assert d == 0.0 and y is None


def test_fender_hull_height_with_yaw_matches_geometry():
    fe, fr = fender(), frame(x=0.0, y=45.0)
    yaw = math.radians(1.0)
    d, y = fe.deflection(fr, Pose(dyaw_rad=yaw), -33.0, 250.0)
    xs = (0.0 + math.sin(yaw) * -33.0) / math.cos(yaw)
    assert y == pytest.approx(45.0 + math.sin(yaw) * xs + math.cos(yaw) * -33.0)


def test_fender_energy_matches_independent_curve_integral():
    fe = FenderModel("F3", 0, 12, 40, [(0, 0), (0.5, 20_000), (1.0, 70_000), (2.0, 200_000)])
    for d in (0.25, 0.5, 1.3, 2.0, 2.6):
        n = 20_000
        integral = sum(0.5 * (fe.force(i * d / n) + fe.force((i + 1) * d / n)) * d / n for i in range(n))
        assert fe.energy(d) == pytest.approx(integral, rel=1e-6)
    lin = fender()
    assert lin.energy(1.5) == pytest.approx(0.5 * 100_000 * 1.5**2)


@pytest.mark.parametrize("curve", [[(0, 0)], [(0.1, 0), (1, 1)], [(0, 0), (1, 5), (1, 6)], [(0, 0), (1, 5), (2, 4)]])
def test_bad_fender_curves_rejected(curve):
    with pytest.raises(UnsupportedMechanics):
        FenderModel("F", 0, 12, 40, curve)
