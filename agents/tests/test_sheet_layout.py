"""Assessed layout provenance, persistence and printable artifact regressions."""
import xml.etree.ElementTree as ET

import pytest

from mooring import refdata
from mooring.core import store
from mooring.core.envelopes import new_id
from mooring.core.schemas import Scenario, TugAssignment, Validity
from mooring.demo_cases import docking_cases
from mooring.examples import T0
from mooring.moored.solver import analyze
from mooring_agents.planner.agent import PLANS, PlanRecord
from mooring_agents.planner.schemas import AgentPlan, RationaleItem
from mooring_agents.safety.schemas import ApprovalCreate, SafetyReview, SafetySheet, Thresholds
from mooring_agents.safety.sheet import SHEETS, approve, build, render_html, render_pdf
from mooring_agents.shared.layout import PlanGeometrySnapshot, capture_geometry, review_geometry_matches


@pytest.fixture
def record():
    case = docking_cases()[0]
    request = case.analysis_request.model_copy(deep=True)
    analysis = analyze(request)
    assert analysis.validity.state == "limited"
    ship = refdata.ship(request.ship_class_id).model_copy(deep=True)
    berth = refdata.berth(request.berth_id).model_copy(deep=True)
    scenario = Scenario(**case.scenario_request.model_dump(), scenario_id=new_id("layout-scenario"), created_at_utc=T0)
    plan = AgentPlan(plan_id=new_id("layout-plan"), scenario_id=scenario.scenario_id, state="succeeded",
        status=analysis.status, config=request.config.model_copy(deep=True), analysis_result_id=analysis.result_id,
        rationale=[RationaleItem(text="Assessment retained without recomputing loads.", cites=[analysis.result_id])])
    return PlanRecord(plan=plan, scenario=scenario, env=request.environment, analysis=analysis,
        geometry_snapshot=capture_geometry(ship, berth, analysis, plan.config, request.environment))


def test_catalog_change_between_assessment_and_sheet_never_changes_captured_layout(record, monkeypatch):
    snapshot = record.geometry_snapshot
    assert snapshot.unavailable_reason is None
    original_x = snapshot.ship.fittings[0].x_ft
    # Catalog access at sheet creation is forbidden, including a seemingly harmless lookup by ID.
    def forbidden(*args, **kwargs):
        raise AssertionError("Sheet construction/rendering fetched current catalog geometry")
    monkeypatch.setattr(refdata, "ship", forbidden)
    monkeypatch.setattr(refdata, "berth", forbidden)
    sheet = build(record)
    assert sheet.layout.state == "available"
    assert snapshot.ship.fittings[0].x_ft == original_x
    assert sheet.layout.analysis_result_id == record.analysis.result_id
    svg = ET.fromstring(sheet.layout.svg)
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    assert not any("href" in name for element in svg.iter() for name in element.attrib)
    text = " ".join(svg.itertext())
    assert sheet.sheet_id in text and sheet.plan_id in text
    assert "North" in text and "Wind toward" in text and "Current toward" in text
    assert record.plan.config.lines[0].ship_fitting_id in text
    assert record.plan.config.lines[0].spec_id in text
    assert sheet.layout.svg in render_html(sheet)
    assert "Pier fitting margins" in render_html(sheet)


def test_capture_is_detached_and_rejects_references_changed_during_planning(record):
    ship = record.geometry_snapshot.ship.model_copy(deep=True)
    berth = record.geometry_snapshot.berth.model_copy(deep=True)
    saved = capture_geometry(ship, berth, record.analysis, record.plan.config, record.env)
    ship.fittings[0].x_ft += 100
    berth.fittings[0].x_ft += 100
    assert saved.ship.fittings[0].x_ft != ship.fittings[0].x_ft
    assert saved.berth.fittings[0].x_ft != berth.fittings[0].x_ft
    changed = capture_geometry(ship, berth, record.analysis, record.plan.config, record.env)
    record.geometry_snapshot = changed
    sheet = build(record)
    assert sheet.layout.state == "unavailable" and sheet.layout.svg is None
    assert "reference revision" in sheet.layout.unavailable_reason


def test_independent_review_requires_matching_reference_manifests(record):
    from types import SimpleNamespace
    from mooring_agents.safety.layout import build_layout
    assert review_geometry_matches(record.geometry_snapshot, [record.analysis])
    changed = record.analysis.model_copy(deep=True)
    changed.manifest.records[0].revision = "different-revision"
    assert not review_geometry_matches(record.geometry_snapshot, [record.analysis, changed])
    assert not review_geometry_matches(record.geometry_snapshot, [SimpleNamespace(manifest=None)])
    sheet = build(record)
    for verified in (False, None):
        layout = build_layout(record, sheet, SimpleNamespace(plan_id=sheet.plan_id, geometry_snapshot_verified=verified))
        assert layout.state == "unavailable" and "independent review" in layout.unavailable_reason
    assert build_layout(record, sheet, SimpleNamespace(plan_id=sheet.plan_id, geometry_snapshot_verified=True)).state == "available"
    mismatch = build_layout(record, sheet, SimpleNamespace(plan_id="other-plan", geometry_snapshot_verified=True))
    assert mismatch.state == "unavailable" and "different plan" in mismatch.unavailable_reason


@pytest.mark.parametrize("change", ["config", "environment", "reference", "result", "missing_manifest"])
def test_changed_assessment_binding_cannot_draw_a_plausible_layout(record, change):
    if change == "config":
        record.plan.config.ship_x_ft += 100
    elif change == "environment":
        record.env.wind_from_true_deg += 10
    elif change == "reference":
        record.geometry_snapshot.berth.face_length_ft += 1
    elif change == "result":
        record.analysis.result_id = "other-analysis"
    else:
        record.analysis.manifest = None
        record.geometry_snapshot = capture_geometry(record.geometry_snapshot.ship, record.geometry_snapshot.berth,
            record.analysis, record.plan.config, record.env)
    sheet = build(record)
    assert sheet.layout.state == "unavailable" and sheet.layout.svg is None
    assert "<svg" not in render_html(sheet)


@pytest.mark.parametrize("state", ["invalid", "unknown", None])
def test_invalid_or_unknown_geometry_is_unavailable(record, state):
    record.analysis.validity = Validity(state=state, reasons=[{"code":"TEST", "message":"Unavailable fixture"}]) if state else None
    sheet = build(record)
    assert sheet.layout.state == "unavailable"
    assert "<svg" not in render_html(sheet)
    assert "No current map is substituted" in render_html(sheet)


@pytest.mark.parametrize("state", ["invalid", "unknown", None])
def test_later_usable_review_cannot_establish_the_original_unusable_pose(record, state):
    usable = record.analysis.validity.model_copy(deep=True)
    record.analysis.validity = Validity(state=state, reasons=[{"code": "TEST", "message": "Unusable original pose"}]) if state else None
    review = SafetyReview(review_id="later-review", plan_id=record.plan.plan_id, created_at_utc=T0,
        verdict="revise", status="AMBER", checks=[], validity=usable, geometry_snapshot_verified=True,
        thresholds=Thresholds(wind_rel_deg=None, governing_element=None, limit_wll_gust_kt=None,
            limit_breaking_gust_kt=None, forecast_max_gust_kt=5, cites=[]),
        summary="Later calculation was usable; the original pose was not.", backend="real")
    sheet = build(record, review)
    assert sheet.validity.state == "limited"
    assert sheet.layout.state == "unavailable" and sheet.layout.svg is None
    assert "<svg" not in render_html(sheet)


@pytest.mark.parametrize("kind", ["line_spec", "tug"])
def test_review_cannot_reuse_layout_after_real_material_or_tug_revision_change(monkeypatch, kind):
    request = docking_cases()[0].analysis_request.model_copy(deep=True)
    ship, berth = refdata.ship(request.ship_class_id), refdata.berth(request.berth_id)
    fleet = refdata.tugs()
    request.tugs = [TugAssignment(tug_id=fleet[0].tug_id, push_point_id=ship.push_points[0].push_point_id,
        mode="push", force_lbf=1000)]
    original = analyze(request)
    request.config = original.result.resolved_config.model_copy(deep=True)
    snapshot = capture_geometry(ship, berth, original, request.config, request.environment)
    assert review_geometry_matches(snapshot, [original])
    if kind == "line_spec":
        lookup = refdata.line
        changed_id = request.config.lines[0].spec_id
        def revised_line(spec_id):
            spec = lookup(spec_id).model_copy(deep=True)
            if spec_id == changed_id:
                spec.mbs_lbf *= 2
            return spec
        monkeypatch.setattr(refdata, "line", revised_line)
    else:
        fleet[0].bollard_pull_ahead_lbf *= 2
        monkeypatch.setattr(refdata, "tugs", lambda: fleet)
    reassessed = analyze(request)
    assert not review_geometry_matches(snapshot, [reassessed])
    assert review_geometry_matches(snapshot, [original])  # Saved identities did not follow catalog changes.
    if kind == "line_spec":
        assert reassessed.result.offset != original.result.offset


@pytest.mark.parametrize("change", ["legacy", "missing", "unversioned", "duplicate", "changed"])
def test_missing_or_changed_reference_snapshot_never_becomes_a_usable_layout(record, change):
    snapshot = record.geometry_snapshot
    if change == "legacy":
        payload = snapshot.model_dump(mode="json")
        payload.pop("reference_records")
        record.geometry_snapshot = PlanGeometrySnapshot.model_validate(payload)
    elif change == "missing":
        snapshot.reference_records = [r for r in snapshot.reference_records if r.kind != "line_spec"]
    elif change == "unversioned":
        snapshot.reference_records[-1].revision = None
    elif change == "duplicate":
        snapshot.reference_records.append(snapshot.reference_records[-1].model_copy(deep=True))
    else:
        snapshot.reference_records[-1].revision = "another-revision"
    assert not review_geometry_matches(record.geometry_snapshot, [record.analysis])
    sheet = build(record)
    assert sheet.layout.state == "unavailable" and sheet.layout.svg is None


def test_unknown_fitting_is_unavailable_instead_of_a_partial_diagram(record):
    record.plan.config.lines[0].chock_id = "missing-chock"
    record.geometry_snapshot.config = record.plan.config.model_copy(deep=True)
    sheet = build(record)
    assert sheet.layout.state == "unavailable"
    assert "incomplete or invalid" in sheet.layout.unavailable_reason


def test_legacy_plan_and_sheet_never_capture_the_current_map(record):
    record.geometry_snapshot = None
    sheet = build(record)
    assert sheet.layout.state == "unavailable"
    legacy = sheet.model_dump(mode="json")
    legacy.pop("layout")
    loaded = SafetySheet.model_validate(legacy)
    assert loaded.layout is None
    assert "legacy sheet" in render_html(loaded)
    assert "layout" not in loaded.model_dump()


def test_document_mutation_cannot_reuse_a_different_layout(record):
    sheet = build(record)
    assert "<svg" in render_html(sheet)
    sheet.environment.observed = sheet.environment.observed.model_copy(update={"current_set_true_deg": 42})
    assert "<svg" not in render_html(sheet)
    assert "saved layout binding" in render_html(sheet)


def test_later_plan_edits_cannot_mutate_an_issued_sheet(record):
    sheet = build(record)
    before = sheet.model_dump_json()
    record.env.current_speed_kt += 1
    record.plan.config.lines[0].spec_id = "edited-line-type"
    record.geometry_snapshot.ship.fittings[0].x_ft += 20
    assert sheet.model_dump_json() == before
    assert sheet.layout.svg in render_html(sheet)


def test_layout_and_identity_survive_persistence_approval_and_new_version(record, monkeypatch, tmp_path):
    path = str(tmp_path / "layout.sqlite")
    monkeypatch.setenv("AGENTS_PERSIST", "1")
    monkeypatch.setenv("MOORING_DB", path)
    store.reset_db(path)
    try:
        PLANS[record.plan.plan_id] = record
        store.reset_db(path)
        restored = PLANS[record.plan.plan_id]
        assert restored.geometry_snapshot == record.geometry_snapshot
        first = build(restored)
        original = first.layout.model_dump_json()
        approved = approve(first, ApprovalCreate(role="co", name="Reviewer", decision="approve"))
        assert approved.layout.model_dump_json() == original
        store.reset_db(path)
        assert SHEETS[first.sheet_id].layout.model_dump_json() == original
        second = build(PLANS[record.plan.plan_id])
        assert second.version == first.version + 1
        assert second.layout.sheet_id == second.sheet_id
        assert second.layout.geometry_hash == first.layout.geometry_hash
        assert second.layout.svg != first.layout.svg  # the version/identity printed on each graphic changes
        assert SHEETS[first.sheet_id].layout.model_dump_json() == original
    finally:
        store.reset_db(":memory:")


def test_port_side_layout_uses_ship_forward_surge_and_escapes_identifiers(record):
    from mooring_agents.safety.layout import _svg
    from mooring.core.schemas import Offset
    ship, berth = record.geometry_snapshot.ship, record.geometry_snapshot.berth
    cfg = record.plan.config.model_copy(deep=True)
    cfg.side_to = "port"
    sheet = build(record)
    sheet.plan_id = '<script>alert("bad")</script>'
    svg = _svg(ship, berth, cfg, Offset(surge_ft=3, sway_ft=0, yaw_deg=0), sheet)
    assert "<script>" not in svg and "&lt;script&gt;" in svg
    assert "port side to" in svg
    # Moving the nominal along-pier position by -3 is identical to +3 ship-forward for port side to.
    cfg.ship_x_ft -= 3
    other = _svg(ship, berth, cfg, Offset(surge_ft=0, sway_ft=0, yaw_deg=0), sheet)
    assert svg == other


def test_pdf_consumes_the_same_saved_graphic(record, monkeypatch):
    import sys
    from types import SimpleNamespace
    sheet = build(record)
    captured = {}
    class Document:
        def __init__(self, *, string):
            captured["html"] = string
        def write_pdf(self):
            return b"%PDF-fixture"
    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=Document))
    assert render_pdf(sheet) == b"%PDF-fixture"
    assert sheet.layout.svg in captured["html"]


@pytest.mark.parametrize("model,fields", [(PlanGeometrySnapshot, ("reference_records",)),
    (SafetySheet, ("layout", "forecast_manifest", "forecast_result_id")),
    (SafetyReview, ("geometry_snapshot_verified", "forecast_manifest", "forecast_result_id"))])
def test_additive_document_fields_remain_optional_for_generated_clients(model, fields):
    schema = model.model_json_schema(mode="serialization")
    for field in fields:
        assert field not in schema.get("required", [])
        assert "default" not in schema["properties"][field]
