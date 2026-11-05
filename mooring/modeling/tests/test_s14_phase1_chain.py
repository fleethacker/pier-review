"""S14: the Phase 1 chain end to end: environment -> loads -> equilibrium -> risk -> assistance -> search -> sequence.

Four labeled scenarios (supported, overload, invalid data, undetermined) on the DDG demonstration data plus a core-level
chain on the synthetic analytical fixture. This is evidence for a demonstration within documented assumptions. It is not
subject-matter review and it does not make the seed data qualified."""

import copy
import time

import pytest
from fastapi.testclient import TestClient

from modeling_api import state
from modeling_api.main import app
from mooring.core import store
from mooring.examples import EXAMPLES

client = TestClient(app)
P = "/api/v1"


def wait(job, timeout=120):
    end = time.monotonic() + timeout
    st = client.get(job["status_url"]).json()
    while st["state"] in ("queued", "running") and time.monotonic() < end:
        time.sleep(0.02)
        st = client.get(job["status_url"]).json()
    return st


def env(wind, gust, **kw):
    return {**EXAMPLES["mooring_analyze"]["environment"], "wind_speed_kt": wind, "wind_gust_kt": gust, **kw}


def chain(environment):
    """Run every stage with the same inputs and return their envelopes by stage."""
    a = copy.deepcopy(EXAMPLES["mooring_analyze"]); a["environment"] = environment
    out = {"loads": client.post(f"{P}/loads/environmental", json={**EXAMPLES["loads_environmental"], "environment": environment}).json(),
           "analyze": client.post(f"{P}/mooring/analyze", json=a).json()}
    risk = client.post(f"{P}/risk/exceedance", json={**a, "n_samples": 100, "seed": 5}).json()
    out["risk"] = wait(risk)["result"]
    out["hold"] = client.post(f"{P}/tugs/hold-plan", json={**a, "margin": 0.25}).json()
    out["tug_berth"] = client.post(f"{P}/tugs/berthing-plan", json={**EXAMPLES["tugs_berthing_plan"], "environment": environment}).json()
    rec = copy.deepcopy(EXAMPLES["mooring_recommend"]); rec["max_evaluations"] = 200
    out["recommend"] = wait(client.post(f"{P}/mooring/recommend", json=rec).json())["result"]
    seq = {"ship_class_id": a["ship_class_id"], "berth_id": a["berth_id"], "config": a["config"], "environment": environment, "tug_plan_result_id": out["tug_berth"]["result_id"]}
    out["sequence"] = client.post(f"{P}/mooring/sequence", json=seq).json()
    return out


def assert_traceable(stage):
    """Every downstream number resolves to stored, immutable inputs and results."""
    assert client.get(f"{P}/results/{stage['result_id']}").status_code == 200
    m = stage["manifest"]
    assert m and m["resolved_inputs_hash"].startswith("sha256:") and m["records"]
    if "request" in (store.load_snapshot(m["resolved_inputs_hash"]) or {}):
        assert store.load_snapshot(m["resolved_inputs_hash"])["request"]


def test_supported_calm_case_flows_through_every_stage_with_provenance_and_no_manufactured_green():
    o = chain(env(4, 5, current_speed_kt=0.1))
    for k in ("loads", "analyze", "hold", "tug_berth", "sequence"):
        assert_traceable(o[k])
    assert o["analyze"]["validity"]["diagnostics"]["converged"] and o["analyze"]["result"]["min_margin"]["pct_wll"] < 20
    # Demonstration data is never "valid": every stage is limited, so none is an unconditional GREEN.
    for k in ("loads", "analyze", "hold", "tug_berth", "sequence"):
        assert o[k]["validity"]["state"] == "limited" and o[k]["status"] != "GREEN", k
    assert "REFERENCE_DATA_NOT_QUALIFIED" in {r["code"] for r in o["analyze"]["validity"]["reasons"]}
    assert o["risk"]["validity"]["state"] == "limited" and o["risk"]["result"]["pointwise_only"] is True
    assert o["hold"]["result"]["feasible"] and o["hold"]["result"]["assignments"] == []
    assert o["sequence"]["result"]["review_status"] == "draft_unreviewed" and o["sequence"]["manifest"]["records"][-1]["kind"] == "tug_plan_result"
    for c in o["recommend"]["result"]["candidates"]:
        assert client.get(f"{P}/results/{c['analysis_result_id']}").status_code == 200


def test_overload_case_is_a_completed_red_result_at_every_stage_not_an_error():
    o = chain(env(75, 100))
    assert o["analyze"]["status"] == "RED" and o["analyze"]["validity"]["diagnostics"]["converged"]
    assert o["risk"]["result"]["p_any_exceeds_wll"] > 0.5 and o["risk"]["status"] == "RED"
    assert o["hold"]["status"] == "RED" and o["hold"]["result"]["feasible"] is False
    assert "not proof" in " ".join(o["hold"]["result"]["rationale"])
    assert o["recommend"]["status"] == "RED" and not any(c["feasible"] for c in o["recommend"]["result"]["candidates"])
    assert o["sequence"]["status"] == "RED"


def test_invalid_data_case_is_invalid_and_its_warning_survives_downstream():
    a = copy.deepcopy(EXAMPLES["mooring_analyze"])
    a["environment"]["water_level_mllw_ft"] = -41.0       # depth 4 ft against a 30.5 ft draft
    j = client.post(f"{P}/mooring/analyze", json=a).json()
    assert j["validity"]["state"] == "invalid" and j["status"] == "RED"
    assert "DEPTH_NOT_ABOVE_DRAFT" in {r["code"] for r in j["validity"]["reasons"]}
    assert any(w["rule_id"] == "UFC-DEPTH-RANGE" for w in j["warnings"])
    tug = client.post(f"{P}/tugs/berthing-plan", json={**EXAMPLES["tugs_berthing_plan"], "environment": a["environment"]}).json()
    assert tug["validity"]["state"] == "invalid" and tug["status"] == "RED"
    risk = wait(client.post(f"{P}/risk/exceedance", json={**a, "n_samples": 20, "seed": 1}).json())["result"]
    assert risk["validity"]["state"] == "invalid" and risk["status"] == "RED"


def test_undetermined_case_a_job_that_misses_its_deadline_is_failed_and_says_so():
    saved = state.JOBS.default_deadline_s
    state.JOBS.default_deadline_s = 0.0001
    try:
        job = client.post(f"{P}/risk/exceedance", json={**EXAMPLES["risk_exceedance"], "n_samples": 20000}).json()
        st = wait(job)
        assert st["state"] == "failed" and "deadline" in st["error"] and st["result"] is None   # undetermined, not "safe"
    finally:
        state.JOBS.default_deadline_s = saved


def test_core_chain_on_the_synthetic_fixture_can_be_valid():
    """Valid is reachable: synthetic provenance, documented wind basis, converged solve, no load-model warning."""
    from mooring.core.schemas import AnalyzeRequest
    from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship
    from mooring.mechanics import equilibrium as eq
    from mooring.rules.nstm582 import design_factor
    ship, berth, spec = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
    env = calm_env().model_copy(update={"wind_speed_kt": 8, "wind_gust_kt": 10, "wind_from_true_deg": 180.0})
    s = eq.build_system(ship, berth, breast_config(pairs=(1, 2, 3, 4), springs=True, pretension=1_000.0), {spec.spec_id: spec}, env, loading="full_load", lines_wet=False)
    sol = eq.solve(s)
    assert sol.converged and sol.positive_definite and sol.rank == 3
    assert max(p for _, p, _ in eq.utilization(s, sol.pose, design_factor("II"))) < 100
