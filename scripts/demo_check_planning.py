"""HTTP-only acceptance checks for the four planning cases and advance planning.

The supplied callbacks use the UI proxy, so these checks exercise the same service
boundary as the browser. They never calculate engineering results locally.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import time
import urllib.request


EXPECTED_CASES = {
    "ddg-supported-limited": ("AMBER", "limited", "AMBER", "limited", "ready_for_signature"),
    "ddg-overloaded": ("RED", "limited", "RED", "limited", "reject"),
    "ddg-invalid-data": ("RED", "invalid", "RED", "invalid", "revise"),
    # Search repairs the one-line input; the initial invalid result must survive.
    "ddg-undetermined": ("RED", "invalid", "AMBER", "limited", "ready_for_signature"),
}


def prediction_brief_check(ui: str, examples: Path, http) -> str:
    """Exercise the real S7 tool and cited explanation with explicitly synthetic local forcing."""
    modeling, agents = ui + "/api/modeling/api/v1", ui + "/api/agents/api/v1"
    body = json.loads((examples / "predict_trajectory_request.json").read_text())
    _, env = http("GET", modeling + "/env/now?berth_id=NAVSTA-NORFOLK-P12-N")
    assert env["source"] == "mock", "camera demo check requires explicitly mock forcing"
    body.update(environment=env, as_of_utc=env["valid_at_utc"], horizon_s=30, tick_s=5)
    body["vessel"].update(observed_utc=env["valid_at_utc"], source="synthetic:demo-check")
    body["uncertainty"]["samples"] = 0
    _, tool = http("POST", agents + "/physics/tools/predict_trajectory", {"input": body, "caller": "demo-check"})
    prediction = tool["output"]
    assert "error" not in prediction, prediction
    rid = prediction["result_id"]
    assert tool["call"]["result_id"] == rid
    assert prediction["validity"]["state"] == "limited"
    _, brief = http("GET", agents + f"/predictions/{rid}/brief")
    _, repeated = http("GET", agents + f"/predictions/{rid}/brief")
    _, saved = http("GET", modeling + f"/results/{rid}")
    assert saved == prediction and repeated == brief, "explaining a prediction changed its immutable evidence"
    assert brief["cites"] == [rid] and brief["validity"] == prediction["validity"]
    assert brief["warnings"] == prediction["warnings"] and brief["assumptions"] == prediction["assumptions"]
    assert "shoal/under-keel clearance" in brief["hazards_unavailable"]
    for actual, narrated in zip(prediction["result"]["alternatives"], brief["alternatives"], strict=True):
        assert narrated["first_breach"] == actual.get("first_breach")
        assert narrated["closest_approach"] == actual.get("closest_approach")
        assert narrated["cites"] == [rid]
        assert not narrated["corridor_available"] and "unavailable" in narrated["uncertainty_note"]
    return f"S7 {rid}; immutable cited alternatives/warnings, synthetic forcing, uncertainty and uncovered hazards explicit"


def finish(http, api: str, accepted: dict, timeout: float = 120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, job = http("GET", api + "/jobs/" + accepted["job_id"])
        if job["state"] == "succeeded":
            assert job.get("result") is not None, "successful job omitted its result"
            return job["result"]
        assert job["state"] in ("queued", "running"), job.get("error") or job["state"]
        time.sleep(0.1)
    raise AssertionError("job exceeded demo-check deadline")


def plan_events(url: str, timeout: float = 120.0) -> int:
    """Consume complete SSE records, with a deadline even when heartbeats continue."""
    events = []
    name, data = None, []
    deadline = time.monotonic() + timeout
    with urllib.request.urlopen(url, timeout=timeout) as response:
        assert response.headers.get_content_type() == "text/event-stream", "Planner response is not SSE"
        for raw in response:
            assert time.monotonic() < deadline, "Planner SSE exceeded demo-check deadline"
            line = raw.decode().rstrip("\r\n")
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif not line:
                if name:
                    events.append(name)
                if name == "done":
                    payload = json.loads("\n".join(data))
                    assert payload.get("state") in (None, "succeeded"), payload
                    assert not payload.get("error"), payload
                    assert "step" in events, "Planner emitted no progress steps"
                    return events.count("step")
                name, data = None, []
    raise AssertionError(f"Planner stream ended without done: {events}")


def outcome(result: dict) -> tuple[str, str]:
    return result["status"], result["validity"]["state"]


def saved_layout_check(sheet: dict, html: bytes) -> None:
    layout = sheet["layout"]
    for field in ("sheet_id", "plan_id", "review_id", "analysis_result_id"):
        assert layout[field] == sheet[field], f"layout {field} detached from sheet"
    assert layout["sheet_version"] == sheet["version"]
    if sheet["validity"]["state"] in ("invalid", "unknown"):
        assert layout["state"] == "unavailable" and layout["svg"] is None and layout["unavailable_reason"]
    else:
        assert layout["state"] == "available", layout
        assert "<svg" in layout["svg"] and sheet["sheet_id"] in layout["svg"]
        assert layout["svg"].encode() in html, "printable sheet omitted its saved diagram"
        assert all(layout[key].startswith("sha256:") for key in ("geometry_hash", "sheet_binding_hash", "ship_revision", "berth_revision"))


def forecast_binding_check(ui: str, examples: Path, http, scenario_id: str, stream=plan_events) -> str:
    agents = ui + "/api/agents/api/v1"
    request = json.loads((examples / "mooring_forecast_resolve.json").read_text())
    request["from_utc"] = request["as_of_utc"]
    request["to_utc"] = (datetime.fromisoformat(request["as_of_utc"].replace("Z", "+00:00")) + timedelta(hours=2)).isoformat()
    request["forecast"] = request["forecast"][:3]
    request["forecast_binding"] = {"source": "supplied", "source_id": "explicit-training", "revision": "v1"}
    _, accepted = http("POST", agents + "/intake/reports", {
        "scenario_id": scenario_id, "horizon_hours": 2, "forecast_request": request,
    })
    intake = finish(http, agents, accepted)
    _, accepted = http("POST", agents + "/agent/plans", {
        "scenario_id": scenario_id, "intake_report_id": intake["report_id"], "max_iterations": 1,
    })
    stream(ui + "/api/agents" + accepted["events_url"])
    _, plan = http("GET", agents + "/agent/plans/" + accepted["plan_id"])
    assert plan["state"] == "succeeded", plan
    _, accepted = http("POST", agents + "/safety/reviews", {"plan_id": plan["plan_id"]})
    review = finish(http, agents, accepted)
    assert review["geometry_snapshot_verified"], "review did not verify frozen references"
    _, created = http("POST", agents + "/safety-sheets", {"plan_id": plan["plan_id"], "review_id": review["review_id"]})
    sheet_url = agents + "/safety-sheets/" + created["sheet_id"]
    _, sheet = http("GET", sheet_url)
    manifest = intake["forecast_manifest"]
    assert all(item["forecast_manifest"] == manifest for item in (plan, review, sheet)), "forecast identity changed during handoff"
    assert manifest["source_id"] == "explicit-training" and manifest["revision"] == "v1"
    assert len({item["forecast_result_id"] for item in (intake, plan, review)}) == 3, "each stage must log its independent canonical resolve"
    assert sheet["forecast_result_id"] == review["forecast_result_id"]
    _, html = http("GET", sheet_url + "/render?format=html")
    assert manifest["content_hash"].encode() in html and manifest["binding_hash"].encode() in html and b"explicit-training" in html
    saved_layout_check(sheet, html)
    _, repeated = http("GET", sheet_url + "/render?format=html")
    assert html == repeated, "saved sheet render changed without a new sheet version"
    return "same source/revision/hash across Intake, Planner, independent Safety and immutable illustrated sheet"


def four_case_checks(ui: str, http, check, stream=plan_events) -> dict:
    modeling, agents = ui + "/api/modeling/api/v1", ui + "/api/agents/api/v1"
    _, cases = http("GET", modeling + "/demo/docking-cases")
    ids = [case["case_id"] for case in cases]
    assert len(ids) == len(set(ids)) and set(ids) == set(EXPECTED_CASES), f"unexpected demo catalog: {ids}"
    supported = {}

    for case in cases:
        def chain(case=case):
            expected = EXPECTED_CASES[case["case_id"]]
            _, initial = http("POST", modeling + "/mooring/analyze", case["analysis_request"])
            assert outcome(initial) == expected[:2], (case["case_id"], "initial", initial)
            if case["case_id"] == "ddg-undetermined":
                _, envelope = http("POST", modeling + "/mooring/envelope", case["envelope_request"])
                assert envelope["status"] == "RED"
                assert envelope["result"]["points"] and all(
                    p["outcome"] == "undetermined" and p["limit_wind_kt"] is None
                    for p in envelope["result"]["points"]
                ), "underconstrained limits must be unknown, never zero"
            _, weather = http("POST", modeling + "/env/scenarios", case["environment_request"])
            body = deepcopy(case["scenario_request"])
            body["name"] = "demo-check " + case["case_id"].removeprefix("ddg-")
            body["env_source"] = {"mode": "scenario", "env_scenario_id": weather["env_scenario_id"]}
            _, scenario = http("POST", modeling + "/scenarios", body)
            sid = scenario["scenario_id"]
            _, accepted = http("POST", agents + "/intake/reports", {"scenario_id": sid, "horizon_hours": 48})
            report = finish(http, agents, accepted)
            assert report["berth_id"] == scenario["berth_id"] and report["ship_class_id"] == scenario["ship_class_id"]
            assert report["current"]["source"] == "scenario", "Intake substituted the configured provider"
            assert all(report["current"][field] == case["environment_request"][field]
                       for field in ("wind_speed_kt", "wind_gust_kt", "current_speed_kt", "water_level_mllw_ft")), "Intake changed the saved forcing"
            _, accepted = http("POST", agents + "/agent/plans", {
                "scenario_id": sid, "intake_report_id": report["report_id"],
                "objective": "moor_for_forecast", "target_margin_pct_wll": 60, "max_iterations": 8,
            })
            count = stream(ui + "/api/agents" + accepted["events_url"])
            _, plan = http("GET", agents + "/agent/plans/" + accepted["plan_id"])
            assert plan["state"] == "succeeded" and plan["status"] == expected[2], plan
            assert plan["scenario_id"] == sid and plan["intake_report_id"] == report["report_id"], plan
            _, final = http("GET", modeling + "/results/" + plan["analysis_result_id"])
            assert outcome(final) == expected[2:4], (case["case_id"], "final", final)
            _, accepted = http("POST", agents + "/safety/reviews", {"plan_id": plan["plan_id"]})
            review = finish(http, agents, accepted)
            assert review["plan_id"] == plan["plan_id"] and review["intake_report_id"] == report["report_id"], review
            assert outcome(review) == expected[2:4] and review["verdict"] == expected[4], review
            _, created = http("POST", agents + "/safety-sheets", {"plan_id": plan["plan_id"], "review_id": review["review_id"]})
            sheet_url = agents + "/safety-sheets/" + created["sheet_id"]
            _, sheet = http("GET", sheet_url)
            assert sheet["plan_id"] == plan["plan_id"] and sheet["review_id"] == review["review_id"], sheet
            assert outcome(sheet) == expected[2:4] and not sheet["locked"] and not sheet["approvals"], sheet
            _, html = http("GET", sheet_url + "/render?format=html")
            assert len(html) > 500 and f"Validity: {expected[3]}".encode() in html, "sheet omitted validity"
            assert review["review_id"].encode() in html, "sheet omitted independent review identity"
            saved_layout_check(sheet, html)
            if expected[3] == "invalid":
                assert b"<td>Unavailable</td><td>Unavailable</td><td>Unavailable</td>" in html, "invalid sheet must withhold line loads and statuses"
            decision = "approve" if review["verdict"] == "ready_for_signature" else "reject"
            _, signed = http("POST", sheet_url + "/approvals", {
                "role": "co", "name": "Demo Check", "decision": decision, "comment": "Automated demonstration only",
            })
            assert signed["locked"] and signed["approvals"][-1]["decision"] == decision
            assert outcome(signed) == expected[2:4], "recording a signature changed engineering status"
            _, original = http("GET", modeling + "/results/" + initial["result_id"])
            assert outcome(original) == expected[:2], "Planner mutated the original analysis"
            if case["case_id"] == "ddg-supported-limited":
                supported.update(scenario_id=sid, tugs=[t["tug_id"] for t in scenario.get("tugs", [])],
                                 plan_id=plan["plan_id"], plan=plan, intake=report)
            return f"initial {expected[0]}/{expected[1]} → final {expected[2]}/{expected[3]}; {count} SSE steps; {review['verdict']}; sheet {decision} recorded"

        check(f"Planning chain: {case['case_id']} (A1)", chain)
    return supported


def advance_planning_check(ui: str, examples: Path, http) -> str:
    modeling = ui + "/api/modeling/api/v1"
    training_request = json.loads((examples / "data_simulation_forecast.json").read_text())
    _, training = http("POST", modeling + "/data-simulation/forecast", training_request)
    _, repeated = http("POST", modeling + "/data-simulation/forecast", training_request)
    assert training == repeated, "the same training seed did not reproduce its series"
    assert training["series"] and all(
        s["source"] == "scenario" and s["metadata"]["basis"] == "scenario"
        and any("not_a_forecast" in q["flags"] for q in s["quality"])
        for s in training["series"]
    ), "training samples must remain labeled synthetic"
    request = json.loads((examples / "mooring_forecast_plan.json").read_text())
    request["forecast"] = training["series"]
    _, accepted = http("POST", modeling + "/mooring/forecast-plan", request)
    response = finish(http, modeling, accepted)
    result = response["result"]
    assert response["manifest"]["resolved_inputs_hash"], "forecast assessment lacks reproducibility manifest"
    assert response["validity"]["state"] == "limited", "synthetic seed inputs cannot be qualified"
    assert result["complete"] and len(result["windows"]) > 1 and result["selected_arrival_utc"], result
    arrival = datetime.fromisoformat(result["selected_arrival_utc"].replace("Z", "+00:00"))
    as_of = datetime.fromisoformat(result["as_of_utc"].replace("Z", "+00:00"))
    assert arrival >= as_of + timedelta(hours=24), "arrival violates advance-planning lead time"
    assert result["sources"] and result["limitations"] and result["recheck_triggers"], "forecast provenance or recheck guidance missing"
    selected = result["selected_config"]
    assert selected and result["installed_at_water_level_mllw_ft"] is not None
    assert all(line.get("paid_out_unstretched_length_ft", 0) > 0 for line in selected["lines"]), "selected configuration lost installed line lengths"
    # Re-evaluate the selected installation through modeling, preserving its lengths and tide.
    sample = next(s for s in request["forecast"] if datetime.fromisoformat(s["valid_at_utc"].replace("Z", "+00:00")) == arrival)
    body = {k: request[k] for k in ("ship_class_id", "loading", "berth_id")}
    body.update(config=selected, environment=sample, tugs=result["tugs"],
                installed_at_water_level_mllw_ft=result["installed_at_water_level_mllw_ft"])
    _, analysis = http("POST", modeling + "/mooring/analyze", body)
    assert outcome(analysis) == ("AMBER", "limited"), analysis
    # Incomplete series must not produce an invented supported arrival.
    uncovered = {**request, "forecast": request["forecast"][:2]}
    _, accepted = http("POST", modeling + "/mooring/forecast-plan", uncovered)
    missing = finish(http, modeling, accepted)["result"]
    assert missing["selected_arrival_utc"] is None and missing["windows"]
    assert all(w["outcome"] == "unavailable" for w in missing["windows"]), missing
    return f"seed {training_request['seed']}; {len(result['windows'])} arrival alternatives; selected lengths/tide rechecked; uncovered arrivals unavailable (synthetic series)"
