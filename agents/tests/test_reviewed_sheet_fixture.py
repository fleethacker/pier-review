"""Offline consumer evidence from the actual Intake/Planner/Safety HTTP chain."""
from pathlib import Path
import xml.etree.ElementTree as ET

from mooring_agents.safety.schemas import SafetySheet
from mooring_agents.safety.sheet import render_html


FIXTURE = Path(__file__).with_name("fixtures") / "reviewed_sheet.json"


def test_reviewed_consumer_fixture_preserves_saved_svg_and_evidence_identity():
    sheet = SafetySheet.model_validate_json(FIXTURE.read_text())
    before = sheet.model_dump_json()
    assert sheet.status == "AMBER" and sheet.validity.state == "limited"
    assert not sheet.locked and not sheet.approvals
    assert sheet.layout.state == "available"
    svg = ET.fromstring(sheet.layout.svg)
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    svg_text = " ".join(svg.itertext())
    html = render_html(sheet)
    assert sheet.layout.svg in html
    for field in ("sheet_id", "plan_id", "review_id", "analysis_result_id"):
        identity = getattr(sheet, field)
        assert identity and getattr(sheet.layout, field) == identity
        assert identity in svg_text and identity in html
    assert "Validity: limited" in html
    assert sheet.layout.sheet_version == sheet.version
    assert sheet.model_dump_json() == before


def test_reviewed_consumer_fixture_refuses_graphic_after_environment_mutation():
    sheet = SafetySheet.model_validate_json(FIXTURE.read_text())
    original_svg = sheet.layout.svg
    observed = sheet.environment.observed
    sheet.environment.observed = observed.model_copy(update={
        "current_set_true_deg": (observed.current_set_true_deg + 37) % 360})
    html = render_html(sheet)
    assert original_svg not in html and "<svg" not in html
    assert "saved layout binding" in html
    assert sheet.layout.svg == original_svg  # Rendering must not rewrite the evidence.
