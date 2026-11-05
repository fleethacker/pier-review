"""Rule geometry and displayed line leads use solved state and the rotated ship frame."""
import math
from dataclasses import replace

import pytest

from mooring import refdata
from mooring.demo_cases import docking_cases
from mooring.mechanics import Pose
from mooring.moored import solver
from mooring.templates import template_config


@pytest.mark.parametrize('side', ['port', 'starboard'])
def test_solved_line_geometry_matches_rules_and_ship_relative_reporting(monkeypatch, side):
    req = docking_cases()[0].analysis_request.model_copy(deep=True)
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    req.config = template_config(ship, berth, side, 650, 'NYLON-DB-7IN')
    req.installed_at_water_level_mllw_ft = -3
    req.environment.water_level_mllw_ft = 4
    system, solution, specs = solver.solve_request(req)
    # Test report-coordinate plumbing at a prescribed pose, not equilibrium convergence.
    pose = Pose(dx_ft=2, dy_ft=1, dyaw_rad=math.radians(10))
    solution = replace(solution, pose=pose)
    contexts = []
    monkeypatch.setattr(solver, 'check_all', lambda ctx: contexts.append(ctx) or [])
    result, _, _ = solver.build_result(req, system, solution, specs)
    angle = system.frame.psi(pose)
    c, s = math.cos(angle), math.sin(angle)
    for (rec, state, _), line, geometry in zip(system.line_tensions(pose),result.lines,contexts[0].geometries):
        # Independent inverse rotation of the pier-minus-lead vector into ship coordinates.
        point = system.frame.to_berth(*rec.lead_xy, pose)
        dx, dy = rec.pier_xyz[0]-point[0], rec.pier_xyz[1]-point[1]
        x_ship, y_ship = c*dx+s*dy, -s*dx+c*dy
        expected = math.degrees(math.atan2(abs(x_ship),abs(y_ship)))
        assert line.horiz_angle_deg == round(expected,1)
        assert geometry.horiz_angle_deg == pytest.approx(expected)
        assert geometry.length_ft == pytest.approx(state.length_ft)
        assert line.length_ft == round(geometry.length_ft,1)
        assert line.vert_angle_deg == round(geometry.vert_angle_deg,1)
        assert line.breast_efficiency == round(geometry.breast_efficiency,3)
