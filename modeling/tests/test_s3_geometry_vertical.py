import math
from types import SimpleNamespace as NS

import pytest

from mooring.berthing.s3_tug_geometry import (NOT_MODELED, PushPointGeom, TugCommand, TugGeometryError, TugLimits,
                                              bind_push_point, clamp_force, slew_force, target_signed, tug_contact,
                                              total_wrench)
from mooring.berthing.s3_vertical import StabilityInputs, vertical_state

PPS = [PushPointGeom("PP-FWD-P", 100.0, "port", 80000), PushPointGeom("PP-AFT-P", -120.0, "port", 80000),
       PushPointGeom("PP-FWD-S", 100.0, "starboard", 80000)]
TUG = NS(bollard_pull_ahead_lbf=60000, bollard_pull_astern_lbf=50000)


def setup(force=40000, d=90, pid="PP-FWD-P"):
    cmd = TugCommand("T1", pid, force, d)
    pp = bind_push_point(cmd, PPS, side_to="starboard")
    return cmd, pp, TugLimits.from_specs(TUG, pp, slew_s=5)


def test_force_and_yaw_moment_analytic():
    cmd, pp, lim = setup()
    c = tug_contact("T1", pp, target_signed(cmd), 0.0, lim)
    assert c.wrench_ship == (0.0, -40000, 100.0 * -40000)
    assert c.force_berth_lbf == pytest.approx((0.0, -40000))
    assert c.mode == "push" and c.tug_position_ft is None and c.position_status == NOT_MODELED
    c = tug_contact("T1", pp, -40000, math.pi / 2, lim)
    assert c.force_berth_lbf == pytest.approx((40000, 0), abs=1e-6)
    assert c.wrench_ship[2] == -4e6


def test_aft_point_opposite_moment_and_sum():
    lim = TugLimits(-6e4, 5e4, 1)
    a = tug_contact("A", PPS[0], -1000, 0, lim)
    b = tug_contact("B", PPS[1], -1000, 0, lim)
    assert total_wrench([a, b]) == (0.0, -2000, -100000 + 120000)


def test_capacity_clamp_and_slew():
    cmd, pp, lim = setup(force=70000)
    assert (lim.lo_lbf, lim.hi_lbf) == (-60000, 50000)
    c = tug_contact("T1", pp, target_signed(cmd), 0, lim, requested=target_signed(cmd))
    assert c.signed_force_lbf == -60000 and c.clamped
    assert clamp_force(70000, lim) == (50000, True)
    assert slew_force(0, -60000, lim, 1.0) == pytest.approx(-12000)
    assert slew_force(-59000, -60000, lim, 1.0) == -60000


def test_pp_rating_limits():
    pp = PushPointGeom("X", 0, "port", 20000)
    assert TugLimits.from_specs(TUG, pp, slew_s=5).lo_lbf == -20000


def test_invalid_push_points_rejected():
    for cmd, kw in [(TugCommand("T", "NOPE", 1, 90), {}), (TugCommand("T", "PP-FWD-S", 1, 90), {}),
                    (TugCommand("T", "PP-FWD-P", 1, 45), {}), (TugCommand("T", "PP-FWD-P", -1, 90), {}),
                    (TugCommand("T", "PP-AFT-P", 1, 90), {"allowed_ids": ["PP-FWD-P"]})]:
        with pytest.raises(TugGeometryError):
            bind_push_point(cmd, PPS, side_to="starboard", **kw)


def test_kinematic_position_only_if_model():
    cmd, pp, lim = setup()
    c = tug_contact("T1", pp, -1, 0, lim, kinematics=lambda: (1.0, 2.0))
    assert c.tug_position_ft == (1.0, 2.0) and c.position_status == "modeled"


def test_tide_cycle_heave():
    levels = [2.0 * math.sin(2 * math.pi * t / 12.42) + 3.0 for t in (0, 3.105, 6.21, 9.315)]
    hs = [vertical_state(w).heave_mllw_ft for w in levels]
    assert hs == pytest.approx(levels) and max(hs) - min(hs) == pytest.approx(4.0)
    assert vertical_state(3.0).heave_dof == "prescribed"
    assert vertical_state(3.0, waterline_offset_ft=-1).heave_mllw_ft == 2.0


def test_missing_water_level_and_stability():
    v = vertical_state(None)
    assert v.heave_mllw_ft is None and v.heave_dof == "not_simulated"
    v = vertical_state(1.0)
    assert (v.roll_dof, v.pitch_dof, v.roll_deg, v.pitch_deg) == ("not_simulated", "not_simulated", None, None)
    v = vertical_state(1.0, stability=StabilityInputs(None, 9000, lambda t: (1, 2)))
    assert v.roll_dof == "not_simulated"
    v = vertical_state(1.0, stability=StabilityInputs(3.0, 9000, lambda t: (1.5, 0.5)))
    assert (v.roll_deg, v.pitch_deg, v.roll_dof) == (1.5, 0.5, "simulated")
