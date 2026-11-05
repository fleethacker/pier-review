"""S11: exceedance, horizon, timeline and alerts."""

import copy
import math
import random
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import EnvironmentSnapshot
from mooring.environment import uncertainty as unc
from mooring.examples import EXAMPLES
from mooring.loads import compute_loads
from mooring.moored import risk

client = TestClient(app)
P = "/api/v1"


def wait(job, timeout=60):
    import time
    end = time.monotonic() + timeout
    st = client.get(job["status_url"]).json()
    while st["state"] in ("queued", "running") and time.monotonic() < end:
        time.sleep(0.02)
        st = client.get(job["status_url"]).json()
    assert st["state"] == "succeeded", st
    return st["result"]


def run(**kw):
    b = copy.deepcopy(EXAMPLES["risk_exceedance"])
    b.update(kw)
    r = client.post(f"{P}/risk/exceedance", json=b)
    assert r.status_code == 202, r.text
    return wait(r.json())


# ---------- statistics against known answers ----------

def test_wilson_interval_known_values():
    lo, hi = risk.wilson(0, 100)
    assert lo == pytest.approx(0.0, abs=1e-12) and hi == pytest.approx(0.0370, abs=1e-3)
    lo, hi = risk.wilson(100, 100)
    assert hi == 1.0 and lo == pytest.approx(0.9630, abs=1e-3)
    lo, hi = risk.wilson(50, 100)
    assert (lo, hi) == pytest.approx((0.4038, 0.5962), abs=1e-3)
    assert risk.wilson(0, 0) == (0.0, 1.0)


def test_exceedance_probability_matches_the_analytic_lognormal_value():
    mu, sigma, thr = 0.27, 0.08, 1.4
    exact = 1 - __import__("statistics").NormalDist(mu, sigma).cdf(math.log(thr))
    model = unc.SYNTHETIC_DEMO.model_copy(update={"gust_factor_mu": mu, "gust_factor_sigma": sigma})
    s = unc.Sampler(model, 12345)
    env = EnvironmentSnapshot(wind_speed_kt=20, wind_gust_kt=20, wind_from_true_deg=0, current_speed_kt=0, current_set_true_deg=0, water_level_mllw_ft=0)
    n = 20_000
    tally, per = risk.monte_carlo(lambda: s.instant(env), lambda e: {"gust": (e.wind_gust_kt / e.wind_speed_kt, thr, None)}, n)
    p = tally.any_wll / n
    lo, hi = risk.wilson(tally.any_wll, n)
    assert lo <= exact <= hi and abs(p - exact) < 4 * math.sqrt(exact * (1 - exact) / n)


def test_zero_and_all_exceedance_have_nonvacuous_bounds():
    env = EnvironmentSnapshot(wind_speed_kt=10, wind_gust_kt=10, wind_from_true_deg=0, current_speed_kt=0, current_set_true_deg=0, water_level_mllw_ft=0)
    s = unc.Sampler(unc.SYNTHETIC_DEMO, 1)
    none, _ = risk.monte_carlo(lambda: s.instant(env), lambda e: {"x": (0.0, 1.0, None)}, 500)
    every, _ = risk.monte_carlo(lambda: s.instant(env), lambda e: {"x": (2.0, 1.0, None)}, 500)
    assert none.any_wll == 0 and risk.wilson(0, 500)[1] > 0 and every.any_wll == 500 and risk.wilson(500, 500)[0] < 1


def test_failed_samples_are_counted_and_bound_the_probability():
    s = unc.Sampler(unc.SYNTHETIC_DEMO, 2)
    env = EnvironmentSnapshot(wind_speed_kt=10, wind_gust_kt=10, wind_from_true_deg=0, current_speed_kt=0, current_set_true_deg=0, water_level_mllw_ft=0)
    k = {"i": 0}
    def ev(e):
        k["i"] += 1
        return None if k["i"] % 10 == 0 else {"x": (2.0 if k["i"] % 2 else 0.0, 1.0, None)}
    t, _ = risk.monte_carlo(lambda: s.instant(env), ev, 1000)
    assert t.failed == 100 and t.n == 1000
    lower, upper = t.any_wll / t.n, (t.any_wll + t.failed) / t.n
    assert lower < t.any_wll / (t.n - t.failed) < upper + 1e-12


def test_failed_sampling_still_checks_cancellation():
    calls = []
    class Cancelled(Exception):
        pass
    def progress(i):
        calls.append(i)
        if i == 50:
            raise Cancelled
    with pytest.raises(Cancelled):
        risk.monte_carlo(lambda: None, lambda _: None, 1000, progress)
    assert calls == [0, 50]


@pytest.fixture
def horizon_inputs():
    from mooring.core.schemas import AnalyzeRequest, ExceedanceRequest
    req = ExceedanceRequest(**{**EXAMPLES["risk_exceedance"], "n_samples": 10, "n_trajectories": 10, "horizon_hours": 1.1})
    base = AnalyzeRequest.model_validate(req.model_dump(include=set(AnalyzeRequest.model_fields)))
    system, sol, specs = risk.solver.solve_request(base)
    return req, system, specs, sol, unc.SYNTHETIC_DEMO, risk.design_factor(req.mst)


def test_horizon_failure_is_unknown_with_bounds_and_endpoint_coverage(monkeypatch, horizon_inputs):
    calls = []
    def trajectory(self, base, n_steps, step_min):
        calls.append((n_steps, step_min))
        return [base] * n_steps
    monkeypatch.setattr(unc.Sampler, "trajectory", trajectory)
    # A whole failed trajectory must not be silently classified as non-exceeding.
    monkeypatch.setattr(risk, "_eval_env", lambda *args: None)
    h = risk._horizon(*horizon_inputs)
    assert h.n_failed == 10 and h.p_event_bounds == [0, 1] and h.p_event_ci95 == [0, 1]
    assert calls == [(4, 22.0)] * 10
    assert h.effective_step_min * (calls[0][0] - 1) == pytest.approx(h.horizon_hours * 60)


def test_horizon_mixed_results_preserve_failed_bounds(monkeypatch, horizon_inputs):
    outcomes = iter([None, {"line-1": (2, 1, 3)}] * 5)
    monkeypatch.setattr(risk, "_eval_env", lambda *args: next(outcomes))
    h = risk._horizon(*horizon_inputs)
    assert h.n_failed == 5 and h.p_event == 0.5 and h.p_event_bounds == [0.5, 1]
    assert h.p_event_ci95[1] == 1 and h.p_event_ci95[0] < 0.5


def test_horizon_checks_cancellation_within_a_trajectory(monkeypatch, horizon_inputs):
    class Cancelled(Exception):
        pass
    class Context:
        count = 0
        def check_cancelled(self):
            self.count += 1
            if self.count == 3:
                raise Cancelled
        def progress(self, *args):
            pass
    calls = []
    def evaluate(*args):
        calls.append(1)
        return {"line-1": (0, 1, 3)}
    monkeypatch.setattr(risk, "_eval_env", evaluate)
    with pytest.raises(Cancelled):
        risk._horizon(*horizon_inputs, ctx=Context())
    assert len(calls) == 1


def test_all_failed_risk_calculations_are_invalid(monkeypatch, horizon_inputs):
    monkeypatch.setattr(risk, "_eval_env", lambda *args: None)
    req = horizon_inputs[0].model_copy(update={"include_horizon": True})
    response = risk.exceedance(req)
    assert response.status == "RED" and response.validity.state == "invalid"
    assert response.result.n_valid == 0 and response.result.p_any_bounds == [0, 1]
    assert response.result.horizon.p_event_bounds == [0, 1]
    assert {"NO_VALID_RISK_SAMPLES", "FAILED_TRAJECTORIES"} <= {r.code for r in response.validity.reasons}


def test_async_risk_result_schemas_are_published_for_consumers():
    import re
    from modeling_api.main import openapi_schema
    contract = openapi_schema()
    schemas = contract["components"]["schemas"]
    assert {"ExceedanceResponse", "TimelineResponse", "HorizonRisk"} <= schemas.keys()
    assert {"p_event_bounds", "effective_step_min"} <= schemas["HorizonRisk"]["properties"].keys()
    # Every result promised in a job endpoint's public summary must be usable by consumers.
    for path, methods in contract["paths"].items():
        for operation in methods.values():
            match = re.search(r"(?:result is an? |job result: )(\w+Response)", operation.get("summary", ""))
            if match:
                assert match[1] in schemas, (path, match[1])


def test_sample_evaluator_includes_loaded_ship_fittings(horizon_inputs):
    _, system, _, sol, _, df = horizon_inputs
    evaluated = risk._eval_env(system, sol.pose, df)
    expected = {rec.ln.ship_fitting_id for rec in system.lines}
    rated = {f.fitting_id: f.swl_lbf for f in system.ship.fittings if f.swl_lbf}
    assert expected & rated.keys()
    for fid in expected & rated.keys():
        assert evaluated[fid][1:] == (rated[fid], None)


# ---------- service ----------

def test_requested_sample_count_is_honored_or_rejected_never_capped():
    assert run(n_samples=1234)["result"]["n_samples"] == 1234
    assert client.post(f"{P}/risk/exceedance", json={**EXAMPLES["risk_exceedance"], "n_samples": 20001}).status_code == 422


def test_reproducible_with_a_seed_and_records_provenance():
    a, b, c = run(seed=7), run(seed=7), run(seed=8)
    for x in (a, b):
        x.pop("result_id"); x.pop("computed_at_utc")
    assert a["result"] == b["result"]
    assert a["manifest"]["rng_seed"] == 7 and a["manifest"]["rng_model_revision"] == "synthetic-demo@1"
    assert run(seed=8)["result"]["p_any_exceeds_wll"] != 99 and c["result"]["seed"] == 8


def test_unqualified_model_makes_the_result_limited_and_pointwise_only_is_stated():
    j = run(n_samples=200)
    assert j["validity"]["state"] == "limited" and j["status"] != "GREEN"
    assert "UNQUALIFIED_UNCERTAINTY_MODEL" in {r["code"] for r in j["validity"]["reasons"]}
    assert j["result"]["pointwise_only"] is True and j["result"].get("horizon") is None
    assert any(w["rule_id"] == "RISK-HORIZON-UNSUPPORTED" for w in j["warnings"])
    assert client.post(f"{P}/risk/exceedance", json={**EXAMPLES["risk_exceedance"], "uncertainty_model_id": "nope"}).status_code == 422


def test_accounting_ci_and_element_semantics():
    r = run(n_samples=300)["result"]
    assert r["n_valid"] + r["n_failed"] == 300 and r["p_any_ci95"][0] <= r["p_any_exceeds_wll"] <= r["p_any_ci95"][1]
    assert r["p_any_bounds"][0] <= r["p_any_bounds"][1]
    fit = [e for e in r["elements"] if not e["element_id"].startswith("line-")]
    assert fit and all(e["p_exceed_mbs"] is None for e in fit)          # no fictitious MBS for fittings and fenders
    assert all(e["p_exceed_mbs"] is not None for e in r["elements"] if e["element_id"].startswith("line-"))
    assert "Wilson" in r["error_criterion"]


def test_dynamic_factor_scales_wind_force_exactly_once():
    from mooring import refdata
    ship = refdata.ship("DDG-51-FIIA")
    env = EnvironmentSnapshot(wind_speed_kt=30, wind_gust_kt=30, wind_from_true_deg=200, current_speed_kt=0.0001, current_set_true_deg=0, water_level_mllw_ft=0)
    f = 1.5
    base = compute_loads(ship, "full_load", 105, env, 46.8).wind.fy_lbf
    scaled = compute_loads(ship, "full_load", 105, risk._with_dynamic(env, f), 46.8).wind.fy_lbf
    assert scaled / base == pytest.approx(f, rel=1e-9)   # not f**2


def test_horizon_probability_comes_from_trajectories_and_is_not_a_sum_of_pointwise_values():
    j = run(n_samples=100, include_horizon=True, n_trajectories=40, horizon_hours=6, seed=3)
    h = j["result"]["horizon"]
    assert j["result"]["pointwise_only"] is False and h["n_trajectories"] == 40 and h["step_min"] == 30
    assert "any line" in h["event"] and 0 <= h["p_event"] <= 1 and h["p_event_ci95"][0] <= h["p_event"] <= h["p_event_ci95"][1]
    assert h["p_event"] >= j["result"]["p_any_exceeds_wll"] - 0.35   # a horizon event is at least about as likely as one instant


def test_empty_configuration_is_invalid_not_a_probability_of_safety():
    b = copy.deepcopy(EXAMPLES["risk_exceedance"])
    b["config"]["lines"] = []
    r = client.post(f"{P}/risk/exceedance", json=b)
    assert r.status_code == 202
    j = wait(r.json())
    assert j["validity"]["state"] == "invalid" and j["status"] == "RED"


def test_job_cancellation_stops_sampling():
    r = client.post(f"{P}/risk/exceedance", json={**EXAMPLES["risk_exceedance"], "n_samples": 20000}).json()
    client.delete(f"{P}/jobs/{r['job_id']}")
    assert client.get(r["status_url"]).json()["state"] == "cancelled"


# ---------- timeline and alerts ----------

def timeline(**kw):
    b = copy.deepcopy(EXAMPLES["risk_timeline"])
    b.update({"start_utc": "2026-11-04T12:00:00Z", **kw})
    r = client.post(f"{P}/risk/timeline", json=b)
    assert r.status_code == 202, r.text
    return wait(r.json())


def test_timeline_is_reproducible_with_an_injected_start_and_has_no_fake_probability():
    a, b = timeline(), timeline()
    for x in (a, b):
        x.pop("result_id"); x.pop("computed_at_utc")
    assert a["result"] == b["result"] and len(a["result"]["steps"]) == 25
    assert all(s["p_any_exceeds_wll"] is None and s["valid"] for s in a["result"]["steps"])
    assert any("pointwise per step" in s for s in a["assumptions"])


def test_timeline_with_sampling_gives_pointwise_probabilities_labeled_scenario_only():
    j = timeline(n_samples_per_step=20, forecast_hours=2)
    assert all(0 <= s["p_any_exceeds_wll"] <= 1 for s in j["result"]["steps"])
    assert "UNQUALIFIED_UNCERTAINTY_MODEL" in {r["code"] for r in j["validity"]["reasons"]}


def test_alert_carries_event_time_provenance_and_staleness():
    from mooring.core.schemas import AnalyzeRequest, EnvironmentMetadata
    req = AnalyzeRequest(**EXAMPLES["mooring_analyze"])
    fresh = risk.alert_for(req.environment, req)
    assert fresh.at_utc == req.environment.valid_at_utc and "no probability" in fresh.provenance and fresh.stale is False
    old = req.environment.model_copy(update={"metadata": EnvironmentMetadata(basis="observation", age_s=4000.0)})
    assert risk.alert_for(old, req).stale is True and "stale" in risk.alert_for(old, req).message
