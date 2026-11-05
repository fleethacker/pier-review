"""S13: sequence generation and validation, with intermediate states and tug provenance."""

import copy

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.examples import EXAMPLES

client = TestClient(app)
P = "/api/v1"
CALM = {**EXAMPLES["mooring_sequence"]["environment"], "wind_speed_kt": 3, "wind_gust_kt": 4, "current_speed_kt": 0.1}


def body(**kw):
    b = copy.deepcopy(EXAMPLES["mooring_sequence"])
    b["environment"] = copy.deepcopy(CALM)
    b.update(kw)
    return b


def seq(**kw):
    r = client.post(f"{P}/mooring/sequence", json=body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


def codes(j):
    return {i["code"] for i in j["result"]["issues"]}


def validate(steps, **kw):
    r = client.post(f"{P}/mooring/sequence/validate", json={**body(**kw), "steps": steps})
    assert r.status_code == 200, r.text
    return r.json()


def test_generated_sequence_in_calm_conditions_has_no_blocking_issues_but_stays_a_draft():
    j = seq()
    r = j["result"]
    assert all(i["severity"] == "AMBER" for i in r["issues"]) and {i["code"] for i in r["issues"]} <= {"PARTIAL_RESTRAINT", "UNSAFE_LEAD", "INSUFFICIENT_CREWS"}
    assert r["review_status"] == "draft_unreviewed" and j["status"] == "AMBER" and j["validity"]["state"] == "limited"
    assert {"SEQUENCE_UNREVIEWED", "STATIC_CHECK_ONLY"} <= {x["code"] for x in j["validity"]["reasons"]}
    assert any("M11" in l for l in r["limitations"]) and r["timing_assumptions"] and r["total_duration_min"] > 0
    # every step has dependencies satisfied by earlier steps and intermediate states are annotated
    nums = {s["step"] for s in r["steps"]}
    assert all(set(s["depends_on"]) <= nums and all(d < s["step"] for d in s["depends_on"]) for s in r["steps"])
    assert any(s["state_ok"] is not None for s in r["steps"])


def test_valid_final_equilibrium_alone_does_not_validate_the_sequence():
    j = seq(environment={**CALM, "wind_speed_kt": 22, "wind_gust_kt": 30})
    assert "UNSAFE_INTERMEDIATE_STATE" in codes(j) and j["status"] == "RED" and j["validity"]["state"] == "invalid"


def test_the_first_lines_alone_cannot_hold_the_ship_and_this_is_reported_per_step():
    j = seq(environment={**CALM, "wind_speed_kt": 18, "wind_gust_kt": 24})
    first = next(s for s in j["result"]["steps"] if s["action"] == "secure_pier")
    assert first["state_ok"] is None and "not yet restrained" in first["state_note"] and "PARTIAL_RESTRAINT" in codes(j)


def tug_plan(**kw):
    b = copy.deepcopy(EXAMPLES["tugs_berthing_plan"])
    b.update(kw)
    r = client.post(f"{P}/tugs/berthing-plan", json=b)
    assert r.status_code == 200
    return r.json()


def test_tug_plan_reference_is_validated_for_existence_type_and_scenario():
    assert client.post(f"{P}/mooring/sequence", json=body(tug_plan_result_id="res_nope")).status_code == 422
    analysis = client.post(f"{P}/mooring/analyze", json=EXAMPLES["mooring_analyze"]).json()
    r = client.post(f"{P}/mooring/sequence", json=body(tug_plan_result_id=analysis["result_id"]))
    assert r.status_code == 422 and "not a tug plan" in r.text
    other = tug_plan(berth_id="NAVSTA-NORFOLK-P12-S")
    r = client.post(f"{P}/mooring/sequence", json=body(tug_plan_result_id=other["result_id"]))
    assert r.status_code == 422 and "different ship or berth" in r.text


def test_a_matching_tug_plan_is_used_for_holding_steps_and_intermediate_states():
    env = {**CALM, "wind_speed_kt": 18, "wind_gust_kt": 24}
    plan = tug_plan(environment=env)
    j = seq(environment=env, tug_plan_result_id=plan["result_id"])
    tugs = {t for s in j["result"]["steps"] for t in s["tug_ids"]}
    assert tugs and tugs <= {a["tug_id"] for a in plan["result"]["assignments"]}
    assert any(s["action"] == "hold" and s["tug_ids"] for s in j["result"]["steps"])


def steps_from(j):
    return copy.deepcopy(j["result"]["steps"])


def test_cyclic_dependencies_and_order_violations_are_found():
    steps = steps_from(seq())
    steps[1]["depends_on"], steps[2]["depends_on"] = [3], [2]
    j = validate(steps)
    assert {"CYCLIC_DEPENDENCY", "ORDER_VIOLATION"} <= codes(j) and j["status"] == "RED"


def test_conflicting_and_missing_actions_unknown_line_and_dependency():
    steps = steps_from(seq())
    steps = [s for s in steps if not (s["line_number"] == 3 and s["action"] == "secure_pier")]   # line 3 never secured
    steps.append({**steps[0], "step": 99, "action": "pass", "line_number": 2, "depends_on": []})   # line 2 passed twice
    steps.append({**steps[0], "step": 100, "action": "take_to_power", "line_number": 42, "depends_on": [7777]})
    j = validate(steps)
    c = codes(j)
    assert {"CONFLICTING_ACTION", "MISSING_LINE_ACTION", "UNKNOWN_LINE", "UNKNOWN_DEPENDENCY"} <= c


def test_take_to_power_before_secure_is_a_conflict():
    steps = steps_from(seq())
    tp = next(s for s in steps if s["action"] == "take_to_power" and s["line_number"] == 2)
    sec = next(s for s in steps if s["action"] == "secure_pier" and s["line_number"] == 2)
    tp["step"], sec["step"] = 0, 500       # executes first
    j = validate(steps)
    assert "CONFLICTING_ACTION" in codes(j)


@pytest.mark.parametrize("crews,code,severity,status", [(3, "INSUFFICIENT_CREWS", "RED", "RED"), (5, "INSUFFICIENT_CREWS", "AMBER", "AMBER")])
def test_insufficient_crews(crews, code, severity, status):
    j = seq(line_handling_crews=crews)
    issue = next(i for i in j["result"]["issues"] if i["code"] == code)
    assert issue["severity"] == severity and j["status"] == status


def test_unavailable_line_when_the_pier_fitting_is_occupied_or_unusable():
    berth = client.get(f"{P}/berths/{EXAMPLES['mooring_sequence']['berth_id']}").json()
    used = {l["pier_fitting_id"] for l in EXAMPLES["mooring_sequence"]["config"]["lines"]}
    for f in berth["fittings"]:
        if f["fitting_id"] in used:
            f["occupied_by"] = "another ship"
    berth["berth_id"] = "SEQ-TEST-BERTH"
    assert client.post(f"{P}/berths", json=berth).status_code == 201
    j = seq(berth_id="SEQ-TEST-BERTH")
    assert "LINE_UNAVAILABLE" in codes(j) and j["status"] == "RED"


def test_unsafe_lead_is_flagged():
    b = body()
    b["config"]["lines"][2]["pier_fitting_id"] = "P12N-B02"      # a bollard far from abeam: a poor breast lead
    b["config"]["lines"][2]["role"] = "breast"
    j = client.post(f"{P}/mooring/sequence", json=b).json()
    assert any(i["code"] == "UNSAFE_LEAD" for i in j["result"]["issues"])


def test_review_status_survives_to_the_safety_sheet_handoff():
    j = seq()
    assert j["result"]["review_status"] == "draft_unreviewed"


def test_sequence_respects_loading_when_depth_is_between_light_and_full_drafts():
    berth = client.get(f"{P}/berths/{EXAMPLES['mooring_sequence']['berth_id']}").json()
    berth["berth_id"] = "SEQ-LOADING-DEPTH"
    for point in berth["depth_profile"]:
        point["depth_mllw_ft"] = 29
    assert client.post(f"{P}/berths", json=berth).status_code == 201
    env = {**CALM, "current_speed_kt": 0, "water_level_mllw_ft": 0}
    full = seq(berth_id=berth["berth_id"], environment=env, loading="full_load")
    light = seq(berth_id=berth["berth_id"], environment=env, loading="light")
    assert full["validity"]["state"] == "invalid" and "INVALID_FINAL_PLAN" in codes(full)
    assert "INVALID_FINAL_PLAN" not in codes(light)


def test_requested_mst_reaches_sequence_strength_checks(monkeypatch):
    from mooring.berthing import sequence as impl
    original = impl.design_factor
    seen = []
    def factor(mst):
        seen.append(mst)
        return original(mst)
    monkeypatch.setattr(impl, "design_factor", factor)
    seq(mst="III")
    assert seen and set(seen) == {"III"}


def test_extra_line_parts_are_not_counted_before_double_up(monkeypatch):
    from mooring.berthing import sequence as impl
    original = impl.eq.build_system
    seen = []
    def build(ship, berth, cfg, *args, **kwargs):
        system = original(ship, berth, cfg, *args, **kwargs)
        seen.append({r.ln.line_number: r.model.parts for r in system.lines})
        return system
    monkeypatch.setattr(impl.eq, "build_system", build)
    b = body()
    for ln in b["config"]["lines"]:
        ln["parts"] = 2
    response = client.post(f"{P}/mooring/sequence", json=b)
    assert response.status_code == 200
    before = next(values for values in seen if len(values) == len(b["config"]["lines"]))
    assert set(before.values()) == {1} and set(seen[-1].values()) == {2}
    assert all(s["state_ok"] is not None or s["state_note"] for s in response.json()["result"]["steps"] if s["action"] == "double_up")


def test_poor_environment_cannot_validate_a_handling_sequence():
    j = seq(environment={**CALM, "metadata": {"basis": "observation", "quality": "poor", "age_s": 0}})
    assert j["status"] == "RED" and j["validity"]["state"] == "invalid"
    assert "INVALID_FINAL_PLAN" in codes(j)


def test_unknown_ship_fitting_reports_issue_instead_of_crashing():
    b = body()
    b["config"]["lines"][0]["ship_fitting_id"] = "not-a-fitting"
    r = client.post(f"{P}/mooring/sequence", json=b)
    assert r.status_code == 200 and "INVALID_LINE_REFERENCE" in codes(r.json())
    assert r.json()["validity"]["state"] == "invalid"


def test_invalid_tug_result_is_not_admitted_as_assistance():
    from mooring.core.envelopes import RESULTS, new_id
    plan = tug_plan()
    plan["result_id"] = new_id("test-invalid-tug")
    plan["validity"]["state"] = "invalid"
    RESULTS[plan["result_id"]] = plan
    r = client.post(f"{P}/mooring/sequence", json=body(tug_plan_result_id=plan["result_id"]))
    assert r.status_code == 422 and "invalid" in r.text


def test_one_step_cannot_require_more_crews_than_available():
    steps = steps_from(seq())
    steps[0]["crews"] = 7
    assert "INSUFFICIENT_STEP_CREWS" in codes(validate(steps))
    steps[0]["crews"] = -1
    assert client.post(f"{P}/mooring/sequence/validate", json={**body(), "steps": steps}).status_code == 422


def test_long_dependency_path_does_not_overflow_the_python_stack():
    from mooring.berthing.sequence import _critical_path
    from mooring.core.schemas import SequenceStep
    steps = [SequenceStep(step=n, line_number=None, action="hold", station="bridge", crews=1,
        trigger="fixture", reference="synthetic test", duration_min=1, depends_on=[n-1] if n else []) for n in range(3000)]
    assert _critical_path(steps) == 3000
    steps[0].depends_on = [2999]
    assert _critical_path(steps) is None


def test_sequence_keeps_declared_installation_tide_across_intermediate_states(monkeypatch):
    from mooring.mechanics import equilibrium as eq
    captured = []
    original = eq.build_system
    def build(*args, **kwargs):
        system = original(*args, **kwargs)
        captured.append((kwargs["install_water_level_ft"], system.env.water_level_mllw_ft))
        return system
    monkeypatch.setattr(eq, "build_system", build)
    result = seq(environment={**CALM, "water_level_mllw_ft": 3.5}, installed_at_water_level_mllw_ft=-1.25)
    assert len(captured) > 1
    assert set(captured) == {(-1.25, 3.5)}
    assert any("-1.25 ft MLLW" in a for a in result["assumptions"])
