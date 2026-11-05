"""A8: unsaved class intake and templates use supplied geometry, never DDG IDs."""

import json

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring import qualification, refdata
from mooring.berthing import sequence
from mooring.core.geometry import line_geometry
from mooring.core.schemas import AnalyzeRequest, EnvironmentSnapshot, RecommendRequest, SequenceRequest, ShipClass
from mooring.moored import search, solver
from mooring.templates import TemplateUnsupported, ship_template_slots, template_config


def supplied_ship() -> ShipClass:
    """An independently authored four-bitt-per-side toy hull, never catalog data."""
    return ShipClass.model_validate({
        "class_id": "SYNTHETIC-A8", "name": "A8 synthetic input fixture", "hull_type": "DDG",
        "loa_ft": 300, "lwl_ft": 280, "beam_ft": 50, "block_coefficient": 0.6,
        "loading_conditions": [{"name": "trial", "displacement_lt": 2500, "draft_fwd_ft": 15,
                                "draft_aft_ft": 15, "freeboard_ft": 12}],
        "wind_area_lateral_ft2": 4000, "wind_area_frontal_ft2": 1000,
        "hull_wind_area_lateral_ft2": 2500, "wind_drag_class": "typical", "mst_class": "II",
        "fittings": [{"fitting_id": f"{side}-station@{n}", "kind": "bitt", "side": side,
                      "x_ft": x, "y_ft": y, "z_ft": 8, "swl_lbf": 100000, "max_rope_circ_in": 8}
                     for side, y in (("port", 20), ("starboard", -20))
                     for n, x in enumerate((120, 50, -50, -120), 1)],
        "push_points": [], "standard_line_outfit": [{"spec_id": "NYLON-DB-7IN", "count": 8}],
        "provenance": {"source": "Independent synthetic A8 fixture; no real vessel", "confidence": "synthetic"},
    })


@pytest.mark.parametrize("class_id", ["CG-47", "LHD-1", "CVN-68"])
def test_existing_hull_only_classes_remain_explicitly_unsupported(class_id):
    with TestClient(app) as client:
        response = client.get(f"/api/v1/ships/{class_id}/capabilities")
    assert response.status_code == 200
    report = response.json()
    assert report["capabilities"]["environmental_loads"] == "limited"
    for key in ("static_mooring", "line_sequence", "template_port", "template_starboard"):
        assert report["capabilities"][key] == "unsupported"
    assert "NO_FITTINGS" in {i["code"] for i in report["issues"]}
    with pytest.raises(TemplateUnsupported, match="NO_FITTINGS"):
        ship_template_slots(refdata.ship(class_id), "starboard")


def test_intake_is_read_only_and_does_not_promote_supplied_provenance():
    candidate = supplied_ship()
    candidate.provenance.confidence = "published"
    before = [s.model_dump() for s in refdata.ships()]
    with TestClient(app) as client:
        response = client.post("/api/v1/ships/validate", json=candidate.model_dump(mode="json"))
        assert client.get(f"/api/v1/ships/{candidate.class_id}").status_code == 404
    assert response.status_code == 200
    report = response.json()
    assert report["level"] == "demonstration"
    assert report["capabilities"]["static_mooring"] == "limited"
    assert report["capabilities"]["template_port"] == "limited"
    assert "FITTING_HEIGHT_LOADING_UNSPECIFIED" in {i["code"] for i in report["issues"]}
    assert [s.model_dump() for s in refdata.ships()] == before


@pytest.mark.parametrize("side", ["port", "starboard"])
def test_non_ddg_ids_and_four_line_layout_reach_real_geometry_and_equilibrium(monkeypatch, side):
    # Parse supplied data through the same schema as the intake endpoint. Inject only
    # into this test's reference reader to exercise the solver; never register a class.
    ship = ShipClass.model_validate_json(supplied_ship().model_dump_json())
    catalog = dict(refdata._ships())
    monkeypatch.setattr(refdata, "_ships", lambda: {**catalog, ship.class_id: ship})
    berth = refdata.berth("NAVSTA-NORFOLK-P12-N")
    config = template_config(ship, berth, side, 650, "NYLON-DB-7IN")
    assert len(config.lines) == 4
    assert {line.role for line in config.lines} == {"breast", "spring_aft", "spring_fwd"}
    assert all(line.ship_fitting_id.startswith(side) and "@" in line.ship_fitting_id for line in config.lines)
    assert len({line.pier_fitting_id for line in config.lines}) == 4
    assert all(line_geometry(line, ship, berth, config, 0).length_ft > 0 for line in config.lines)
    env = EnvironmentSnapshot(wind_speed_kt=0, wind_gust_kt=0, wind_from_true_deg=0,
                              current_speed_kt=0, current_set_true_deg=0, water_level_mllw_ft=0)
    result = solver.analyze(AnalyzeRequest(ship_class_id=ship.class_id, loading="trial", berth_id=berth.berth_id,
                                          config=config, environment=env))
    assert len(result.result.lines) == 4
    assert result.validity.diagnostics.converged
    assert result.validity.state != "valid"  # a synthetic fixture never qualifies an asset
    assert "REFERENCE_DATA_NOT_QUALIFIED" in {reason.code for reason in result.validity.reasons}
    slots = search.template_slots(ship, side)
    for slot in slots:
        bitt, options = search._slot_options(ship, berth, slot, side, 650, set(), 2, "P" if side == "port" else "S")
        assert bitt.fitting_id == slot.ship_fitting_id and options
    recommendation = search.recommend(RecommendRequest(
        ship_class_id=ship.class_id, loading="trial", berth_id=berth.berth_id, side_to=side, ship_x_ft=650,
        design_basis="forecast_only", forecast_env=[env], max_candidates=1, max_evaluations=10, neighbors_per_line=1))
    assert recommendation.result.candidates
    selected = recommendation.result.candidates[0]
    assert len(selected.config.lines) == 4 and selected.feasible
    assert {line.ship_fitting_id for line in selected.config.lines} == {slot.ship_fitting_id for slot in slots}
    draft = sequence.sequence(SequenceRequest(ship_class_id=ship.class_id, loading="trial", berth_id=berth.berth_id,
                                               config=selected.config, environment=env))
    assert draft.result.review_status == "draft_unreviewed"
    assert {step.line_number for step in draft.result.steps if step.line_number is not None} == {1, 2, 3, 4}
    assert len(search.template_slots()) == 6  # legacy standalone helper remains compatible


@pytest.mark.parametrize("mutation,code", [
    (lambda s: s.fittings.append(s.fittings[0].model_copy()), "DUPLICATE_SHIP_FITTING"),
    (lambda s: setattr(s.fittings[0], "paired_chock_id", "missing"), "DANGLING_CHOCK"),
    (lambda s: setattr(s.fittings[0], "paired_chock_id", s.fittings[1].fitting_id), "INVALID_CHOCK"),
    (lambda s: setattr(s.fittings[0], "swl_lbf", None), "MISSING_SWL"),
    (lambda s: setattr(s.fittings[0], "swl_lbf", -1), "MISSING_SWL"),
    (lambda s: setattr(s.fittings[0], "y_ft", -20), "FITTING_FRAME_CONFLICT"),
    (lambda s: setattr(s.fittings[0], "x_ft", 1000), "FITTING_OUTSIDE_HULL"),
    (lambda s: s.standard_line_outfit.append(s.standard_line_outfit[0].model_copy()), "DUPLICATE_LINE_INVENTORY"),
    (lambda s: setattr(s.standard_line_outfit[0], "spec_id", "unknown"), "DANGLING_LINE_SPEC"),
    (lambda s: s.loading_conditions.clear(), "MISSING_LOADING"),
    (lambda s: s.loading_conditions.append(s.loading_conditions[0].model_copy()), "DUPLICATE_LOADING"),
])
def test_semantically_invalid_input_cannot_advertise_planning(mutation, code):
    ship = supplied_ship()
    mutation(ship)
    with TestClient(app) as client:
        response = client.post("/api/v1/ships/validate", json=ship.model_dump(mode="json"))
    assert response.status_code == 200  # report, not registration
    report = response.json()
    assert report["level"] == "unqualified"
    assert any(issue["code"] == code and issue["blocking"] for issue in report["issues"])
    assert report["capabilities"]["static_mooring"] == "unsupported"
    assert report["capabilities"]["template_port"] == "unsupported"


@pytest.mark.parametrize("mutation,code", [
    (lambda s: s.fittings.clear(), "NO_FITTINGS"),
    (lambda s: s.fittings.pop(0), "INSUFFICIENT_SIDE_FITTINGS"),
    (lambda s: setattr(s.fittings[1], "x_ft", s.fittings[0].x_ft), "AMBIGUOUS_FITTING_ORDER"),
])
def test_incomplete_or_ambiguous_arrangements_raise_capability_errors(mutation, code):
    ship = supplied_ship()
    mutation(ship)
    with pytest.raises(TemplateUnsupported, match=code):
        ship_template_slots(ship, "port")


def test_insufficient_berth_and_incompatible_line_fail_coherently():
    ship, berth = supplied_ship(), refdata.berth("NAVSTA-NORFOLK-P12-N")
    berth.fittings = berth.fittings[:2]
    with pytest.raises(TemplateUnsupported, match="INSUFFICIENT_PIER_FITTINGS"):
        template_config(ship, berth, "starboard", 650, "NYLON-DB-7IN")
    for fitting in ship.fittings:
        fitting.max_rope_circ_in = 6
    with pytest.raises(TemplateUnsupported, match="LINE_SIZE_INCOMPATIBLE"):
        template_config(ship, berth, "starboard", 650, "NYLON-DB-7IN")


def test_validation_inherits_existing_auth_and_rejects_unknown_units(monkeypatch):
    key = "a" * 32
    monkeypatch.setenv("MOORING_API_KEYS", json.dumps({"reviewer": key}))
    monkeypatch.setenv("MOORING_AUTH_REQUIRED", "1")
    body = supplied_ship().model_dump(mode="json")
    with TestClient(app) as client:
        assert client.post("/api/v1/ships/validate", json=body).status_code == 401
        headers = {"Authorization": f"Bearer {key}"}
        assert client.post("/api/v1/ships/validate", json=body, headers=headers).status_code == 200
        assert client.post("/api/v1/ships/validate", json={**body, "coordinate_units": "meters"}, headers=headers).status_code == 422
    assert supplied_ship().class_id not in {s.class_id for s in refdata.ships()}


def test_missing_inventory_does_not_enable_template_or_sequence():
    ship = supplied_ship()
    ship.standard_line_outfit.clear()
    report = qualification.qualify_ship(ship, {s.spec_id for s in refdata.lines()})
    assert report.capabilities["template_starboard"] == report.capabilities["line_sequence"] == "unsupported"
    assert "MISSING_LINE_INVENTORY" in {i.code for i in report.issues}
