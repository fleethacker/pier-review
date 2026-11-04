"""S01: qualification separates schema validity from data confidence; catalog access is defensive."""

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring import qualification as q
from mooring import refdata
from mooring.rules.nstm582 import RULES

client = TestClient(app)
P = "/api/v1"


def spec(**kw):
    s = refdata.line("NYLON-DB-7IN")
    return s.model_copy(update=kw)


@pytest.mark.parametrize("curve,code", [
    ([(0, 0), (0.5, 0.2), (0.5, 0.3), (1.0, 0.4)], "CURVE_LOAD_NOT_INCREASING"),
    ([(0, 0), (0.5, 0.3), (1.0, 0.3)], "CURVE_NOT_MONOTONE"),
    ([(0, 0), (0.5, 0.3), (0.9, 0.4)], "CURVE_COVERAGE"),
    ([(0.1, 0.0), (1.0, 0.4)], "CURVE_NOT_FROM_ORIGIN"),
    ([(0, 0)], "CURVE_TOO_SHORT"),
])
def test_bad_line_curves_are_unqualified(curve, code):
    qual = q.qualify_line(spec(load_elongation=curve))
    assert qual.level == "unqualified" and code in {i.code for i in qual.issues if i.blocking}
    assert qual.capabilities["static_mooring"] == "unsupported"


def test_seed_data_is_demonstration_never_qualified():
    audit = q.audit_catalog()
    assert audit.ok and audit.problems == []
    assert {a.level for a in audit.assets} == {"demonstration"}  # all seed data is mock/estimated


def test_published_complete_record_can_qualify():
    s = spec(provenance=refdata.line("NYLON-DB-7IN").provenance.model_copy(update={"confidence": "published"}))
    qual = q.qualify_line(s)
    assert qual.level == "demonstration"  # the wet/dry-single-curve limitation is still disclosed
    assert any(i.code == "WET_DRY_CURVES_SINGLE" for i in qual.issues)


def test_ship_without_swl_or_with_dangling_refs():
    ship = refdata.ship("DDG-51-FIIA")
    ship.fittings[0].swl_lbf = None
    ship.fittings[1].paired_chock_id = "NOPE"
    qual = q.qualify_ship(ship, {"NYLON-DB-7IN"})
    codes = {i.code for i in qual.issues}
    assert {"MISSING_SWL", "DANGLING_CHOCK", "DANGLING_LINE_SPEC"} <= codes and qual.level == "unqualified"
    assert qual.capabilities["berthing_dynamics"] == "unsupported"


def test_class_without_fittings_is_unsupported_not_guessed():
    qual = q.qualify_ship(refdata.ship("CVN-68"))
    assert qual.capabilities["static_mooring"] == "unsupported" and "NO_FITTINGS" in {i.code for i in qual.issues}


def test_berth_duplicates_and_coverage():
    b = refdata.berth("NAVSTA-NORFOLK-P12-N")
    b.fittings.append(b.fittings[0].model_copy())
    b.depth_profile = b.depth_profile[:1]
    codes = {i.code for i in q.qualify_berth(b).issues}
    assert {"DUPLICATE_PIER_FITTING", "DEPTH_COVERAGE"} <= codes


def test_analysis_issues_missing_rating_blocks_a_real_analysis():
    ship = refdata.ship("DDG-51-FIIA")
    from mooring.examples import EXAMPLES
    from mooring.core.schemas import MooringConfig

    cfg = MooringConfig(**EXAMPLES["mooring_analyze"]["config"])
    specs = {s.spec_id: s for s in refdata.lines()}
    berth = refdata.berth("NAVSTA-NORFOLK-P12-N")
    assert not [i for i in q.analysis_issues(ship, berth, cfg, specs) if i.blocking]
    bitt = cfg.lines[0].ship_fitting_id
    next(f for f in ship.fittings if f.fitting_id == bitt).swl_lbf = None
    cfg.lines[1].chock_id = "BITT-2S"  # a bitt is not a chock
    blocking = {i.code for i in q.analysis_issues(ship, berth, cfg, specs) if i.blocking}
    assert {"MISSING_FITTING_RATING", "INVALID_CHOCK"} <= blocking


def test_catalog_access_returns_defensive_copies():
    a = refdata.ship("DDG-51-FIIA")
    a.fittings.clear()
    a.loa_ft = 1.0
    assert refdata.ship("DDG-51-FIIA").fittings and refdata.ship("DDG-51-FIIA").loa_ft == 509.5
    ln = refdata.line("NYLON-DB-7IN")
    ln.load_elongation.clear()
    assert refdata.line("NYLON-DB-7IN").load_elongation
    b = refdata.berth("NAVSTA-NORFOLK-P12-N")
    b.fittings.clear()
    assert refdata.berth("NAVSTA-NORFOLK-P12-N").fittings
    refdata.tugs()[0].power_hp = 1
    assert refdata.tugs()[0].power_hp != 1


def test_rule_audit_is_complete_and_honest():
    assert all(r.coverage and r.applicability for r in RULES)
    assert not any(r.source_verified for r in RULES)  # NSTM text is not in the repo
    assert {r.rule_id for r in RULES if r.coverage == "unsupported"} == {"NESTED-MST", "BERTHING-SPEED"}
    assert all(r.coverage == "unsupported" for r in RULES if not r.implemented)


def test_qualification_and_capability_endpoints():
    j = client.get(f"{P}/qualification").json()
    assert j["ok"] and {a["asset_kind"] for a in j["assets"]} == {"ship", "line_spec", "berth", "tug"}
    caps = {c["capability"]: c for c in client.get(f"{P}/capabilities").json()}
    assert caps["Approach planner"]["qualification"] == "mock" and caps["Approach planner"]["blockers"]
    assert caps["Berthing dynamics integrator"]["qualification"] == "unqualified" and caps["Gust risk (exceedance, timeline, alerts)"]["qualification"] == "unqualified"
    rules = client.get(f"{P}/rules").json()
    assert all("coverage" in r and r["source_verified"] is False for r in rules)
