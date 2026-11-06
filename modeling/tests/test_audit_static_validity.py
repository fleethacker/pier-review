"""Product audit F03/F04: convergence cannot turn invalid physical inputs into a usable limit."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from mooring import refdata
from mooring.core.schemas import AnalyzeRequest, DepthPoint, TideSweepRequest
from mooring.core.schemas.ultimate import UltimateGustRequest
from mooring.examples import EXAMPLES
from mooring.mechanics import equilibrium as eq
from mooring.moored import solver, ultimate
from mooring.moored.envelopes_real import tide_sweep

T0 = datetime(2026, 11, 5, 17, tzinfo=UTC)


def body():
    return deepcopy(EXAMPLES["mooring_analyze"])


def capacity_basis(req):
    return dict(basis_id="audit-fixture", evidence_status="synthetic_test_fixture",
                citation="Synthetic regression capacities; not engineering data", wind_basis="30 s at 10 m",
                lines=[dict(line_number=ln["line_number"], ultimate_capacity_lbf=70000 if ln["line_number"] == 3 else 1e12,
                            material_law_max_strain=10, factors="none (synthetic test)") for ln in req["config"]["lines"]])


def tide_request(monkeypatch, *, interior=False):
    b = body()
    b["environment"].update(wind_speed_kt=0, wind_gust_kt=0, current_speed_kt=0, water_level_mllw_ft=0)
    berth = refdata.berth(b["berth_id"]).model_copy(update={"depth_profile": [DepthPoint(x_ft=0, depth_mllw_ft=31)]})
    monkeypatch.setattr(refdata, "berth", lambda _: berth)
    times = [(0, 0), (15, -2), (30, 0)] if interior else [(0, 0), (60, -2)]
    return TideSweepRequest.model_validate({**b, "from_utc": T0, "to_utc": T0 + timedelta(minutes=times[-1][0]),
        "step_min": 30, "water_level_forecast": [dict(b["environment"], valid_at_utc=T0 + timedelta(minutes=m),
                                                     water_level_mllw_ft=level) for m, level in times]})


def test_grounding_tide_steps_have_no_usable_loads(monkeypatch):
    req = tide_request(monkeypatch)
    response = tide_sweep(req)
    assert response.status == "RED" and response.validity.state == "invalid"
    assert "DEPTH_NOT_ABOVE_DRAFT" in {r.code for r in response.validity.reasons}
    assert response.result.steps[0].valid
    for step in response.result.steps[1:]:
        assert not step.valid and step.lines == [] and step.max_pct_wll is None


def test_grounding_between_output_times_invalidates_entire_sweep(monkeypatch):
    req = tide_request(monkeypatch, interior=True)
    response = tide_sweep(req)
    assert all(step.water_level_mllw_ft == 0 for step in response.result.steps)
    assert response.status == "RED" and response.validity.state == "invalid"
    assert "DEPTH_NOT_ABOVE_DRAFT" in {r.code for r in response.validity.reasons}
    assert any("evaluated" in r.message for r in response.validity.reasons if r.code == "STEP_INPUT_INVALID")


@pytest.mark.parametrize("invalid", ["grounded", "poor_quality", "invalid_tug"])
def test_invalid_inputs_cannot_establish_an_ultimate_gust(invalid):
    b = body()
    if invalid == "grounded":
        b["environment"]["water_level_mllw_ft"] = -20
        code = "DEPTH_NOT_ABOVE_DRAFT"
    elif invalid == "poor_quality":
        b["environment"]["metadata"] = dict(basis="scenario", source="audit", quality="poor")
        code = "ENVIRONMENT_POOR_QUALITY"
    else:
        b["tugs"] = [dict(tug_id="T1", push_point_id="PP-FWD-P", mode="push", force_lbf=1e9)]
        code = "TUG_ASSIGNMENT_INVALID"
    ordinary = solver.analyze(AnalyzeRequest.model_validate(b))
    assert ordinary.validity.state == "invalid" and code in {r.code for r in ordinary.validity.reasons}
    response = ultimate.ultimate_gust(UltimateGustRequest.model_validate({**b, "capacity_basis": capacity_basis(b),
                                                                       "step_deg": 90, "max_search_kt": 40}))
    assert response.status == "RED" and response.validity.state == "invalid"
    assert code in {r.code for r in response.validity.reasons}
    assert response.result.outcome == "unavailable"
    assert response.result.assessed is None and response.result.governing is None and response.result.directions == []
    assert response.result.assessed_gust_margin_kt is None


def test_ultimate_rechecks_validity_inside_the_search(monkeypatch):
    """Inject a depth failure only above 10 kt to distinguish probe checks from baseline validation."""
    depth = eq.System.depth_ft
    monkeypatch.setattr(eq.System, "depth_ft", lambda self, pose: 1.0 if self.env.wind_speed_kt >= 10 else depth(self, pose))
    b = body()
    b["environment"].update(wind_speed_kt=1, wind_gust_kt=1)
    assert solver.analyze(AnalyzeRequest.model_validate(b)).validity.state != "invalid"
    result = ultimate.ultimate_gust(UltimateGustRequest.model_validate({**b, "capacity_basis": capacity_basis(b),
                                                                     "step_deg": 90, "max_search_kt": 40}))
    assert result.validity.state == "invalid" and result.status == "RED"
    assert result.result.outcome == "unavailable" and result.result.governing is None
    assert "DEPTH_NOT_ABOVE_DRAFT" in {r.code for r in result.validity.reasons}
