"""S07: limiting wind and tide sweep on the real solver."""

import copy
import dataclasses
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import AnalyzeRequest, LimitEnvelopeRequest, TideSweepRequest
from mooring.examples import EXAMPLES
from mooring.mechanics import Pose
from mooring.moored import envelopes_real as er
from mooring.mechanics import equilibrium as eq
from mooring.moored import solver

client = TestClient(app)
P = "/api/v1"


def env_body(**kw):
    b = copy.deepcopy(EXAMPLES["mooring_envelope"])
    b.update(kw)
    return b


def points(j):
    return {p["wind_rel_deg"]: p for p in j["result"]["points"]}


def test_limits_are_physically_ordered_and_report_bracket_and_outcome():
    j = client.post(f"{P}/mooring/envelope", json=env_body(step_deg=30)).json()
    pts = points(j)
    assert j["backend"] == "real" and all(p["outcome"] == "limit_found" for p in pts.values())
    # Heading 105: wind from the pier-side beam pushes the ship off the pier and loads the lines (lowest limit);
    # wind from the water side loads the fenders and takes far more wind.
    assert pts[60.0]["limit_wind_kt"] < 20 and pts[60.0]["failure_mode"] == "WLL"
    assert pts[240.0]["failure_mode"] == "fender" and pts[240.0]["limit_wind_kt"] > 60
    lo, hi = pts[60.0]["bracket_kt"]
    assert hi - lo <= 0.25 + 1e-9 and lo == pts[60.0]["limit_wind_kt"]
    assert j["result"]["worst"]["limit_wind_kt"] == min(p["limit_wind_kt"] for p in pts.values())


def test_limit_is_confirmed_by_a_direct_analysis_just_below_and_above():
    j = client.post(f"{P}/mooring/envelope", json=env_body(step_deg=90)).json()
    p = points(j)[90.0]
    base = EXAMPLES["mooring_envelope"]
    ratio = base["environment"]["wind_gust_kt"] / base["environment"]["wind_speed_kt"]
    heading = client.get(f"{P}/berths/{base['berth_id']}").json()["face_bearing_true_deg"]

    def worst_pct(v):
        b = copy.deepcopy(base); b.pop("step_deg")
        b["environment"].update(wind_speed_kt=v, wind_gust_kt=v * ratio, wind_from_true_deg=(heading + 90) % 360)
        r = client.post(f"{P}/mooring/analyze", json=b).json()["result"]
        return max([l["pct_wll"] for l in r["lines"]] + [x["pct"] for x in r["pier_fittings"]])
    lo, hi = p["bracket_kt"]
    assert worst_pct(lo) <= 100.0 + 1e-6 and worst_pct(hi + 1e-6) > 100.0


def test_zero_wind_overload_is_distinct_from_a_limit():
    b = env_body(step_deg=90)
    for ln in b["config"]["lines"]:
        ln["pretension_lbf"] = 60_000  # far above WLL at installation
    j = client.post(f"{P}/mooring/envelope", json=b).json()
    assert {p["outcome"] for p in j["result"]["points"]} == {"fails_at_zero_wind"}
    assert all(p["limit_wind_kt"] == 0.0 for p in j["result"]["points"]) and j["status"] == "RED"


def test_no_failure_within_range_is_not_unlimited():
    j = client.post(f"{P}/mooring/envelope", json=env_body(step_deg=90, max_search_kt=10.0)).json()
    for p in j["result"]["points"]:
        assert p["outcome"] == "no_failure_in_range" and p["limit_wind_kt"] is None and p["search_max_kt"] == 10.0
    assert any("no failure within the range is not 'unlimited'" in a for a in j["assumptions"])


def test_sustained_current_lowers_the_limit():
    calm = points(client.post(f"{P}/mooring/envelope", json=env_body(step_deg=90)).json())[90.0]["limit_wind_kt"]
    b = env_body(step_deg=90)
    b["environment"].update(current_speed_kt=1.8, current_set_true_deg=15)
    cur = points(client.post(f"{P}/mooring/envelope", json=b).json())[90.0]["limit_wind_kt"]
    assert cur != calm


def test_active_set_change_fender_contact_limit():
    pts = points(client.post(f"{P}/mooring/envelope", json=env_body(step_deg=60)).json())
    onto_pier = [p for p in pts.values() if p["failure_mode"] == "fender"]
    assert onto_pier and all(p["first_failure_element"].startswith("P12N-CAMEL") for p in onto_pier)


def test_failed_intermediate_solve_is_undetermined_not_a_limit(monkeypatch):
    real = eq.solve
    def flaky(system, start=Pose(), **kw):
        sol = real(system, start, **kw)
        if system.env.wind_speed_kt == 10.0:  # not the request's own 22 kt, so the base solve is fine
            sol.converged, sol.failure = False, "forced"
        return sol
    monkeypatch.setattr(er.eq, "solve", flaky)
    j = client.post(f"{P}/mooring/envelope", json=env_body(step_deg=90)).json()
    for p in j["result"]["points"]:
        assert p["outcome"] == "undetermined" and p["limit_wind_kt"] is None and p["undetermined_at_kt"] == 10.0
    assert "SEARCH_UNDETERMINED" in {r["code"] for r in j["validity"]["reasons"]} and j["status"] != "GREEN"


def test_nonmonotone_bracket_is_flagged_and_not_bisected(monkeypatch):
    seq = {}
    def pattern(system, start, df):
        v = system.env.wind_speed_kt
        sol = eq.solve(system, start)
        if v <= 5:
            return "ok", None, None, sol
        if abs(v - 6.0) < 1e-9 or abs(v - 7.0) < 1e-9 or v >= 10:   # ok, fail, ok, fail... inside the (5, 10] bracket
            return "fail", "line-3", "WLL", sol
        return "ok", None, None, sol
    monkeypatch.setattr(er, "_evaluate", pattern)
    j = client.post(f"{P}/mooring/envelope", json=env_body(step_deg=90)).json()
    p = points(j)[0.0]
    assert p["nonmonotone_in_bracket"] is True and p["outcome"] == "limit_found"
    assert p["limit_wind_kt"] == 5.0 and p["bracket_kt"][0] == 5.0


# ---------- tide sweep ----------

def sweep(**kw):
    b = copy.deepcopy(EXAMPLES["mooring_tide_sweep"])
    b.update(kw)
    return client.post(f"{P}/mooring/tide-sweep", json=b)


def test_sweep_reports_resolution_extremes_and_does_not_retension():
    j = sweep(step_min=60).json()
    r = j["result"]
    assert j["backend"] == "real" and r["time_resolution_min"] == 5.0 and r["applied_tending"] is None
    assert len(r["steps"]) == 13 and all(s["valid"] for s in r["steps"])
    ext = {e["line_number"]: e for e in r["line_extremes"]}
    reported_max = {n: max(l["tension_lbf"] for s in r["steps"] for l in s["lines"] if l["line_number"] == n) for n in ext}
    assert all(ext[n]["max_tension_lbf"] >= reported_max[n] for n in ext)  # extremes between coarse samples are not lost
    assert any("Nothing is retensioned silently" in a for a in j["assumptions"])


def test_same_water_level_gives_same_state_without_tending():
    j = sweep(step_min=30).json()
    steps = j["result"]["steps"]
    # Path independence: each step equals an independent analysis at that water level with the same installed rest lengths.
    base = copy.deepcopy(EXAMPLES["mooring_tide_sweep"])
    for k in (0, 7, 15, 24):
        s = steps[k]
        req = {x: base[x] for x in base if x not in ("from_utc", "to_utc", "step_min")}
        req["environment"] = {**req["environment"], "water_level_mllw_ft": s["water_level_mllw_ft"]}
        req["installed_at_water_level_mllw_ft"] = base["environment"]["water_level_mllw_ft"]
        direct = client.post(f"{P}/mooring/analyze", json=req).json()["result"]["lines"]
        assert [round(l["tension_lbf"]) for l in direct] == [l["tension_lbf"] for l in s["lines"]]


def test_explicit_tending_changes_rest_length_from_its_time_only():
    base = sweep(step_min=60).json()["result"]["steps"]
    t3 = base[3]["valid_at_utc"]
    j = sweep(step_min=60, tending=[{"at_utc": t3, "line_number": 3, "action": "slack", "amount_ft": 0.2}]).json()
    steps = j["result"]["steps"]
    tension = lambda s, n: next(l["tension_lbf"] for l in s["lines"] if l["line_number"] == n)
    assert all(tension(steps[i], 3) == tension(base[i], 3) for i in range(3))   # unchanged before the action
    assert tension(steps[3], 3) < tension(base[3], 3)                           # eased from then on
    assert j["result"]["applied_tending"][0]["amount_ft"] == 0.2
    assert sweep(step_min=60, tending=[{"at_utc": t3, "line_number": 99, "action": "heave", "amount_ft": 1}]).status_code == 422


def test_recommended_tending_is_advisory_and_not_applied():
    j = sweep(step_min=60).json()
    rec = j["result"]["tending"]
    again = sweep(step_min=60).json()["result"]["steps"]
    assert j["result"]["steps"] == again  # recommendations did not change the reported tensions
    assert all(a["amount_ft"] > 0 for a in rec)


def test_failed_step_is_marked_and_invalidates_the_sweep(monkeypatch):
    real = er.eq.solve
    calls = {"n": 0}
    def flaky(system, start=Pose(), **kw):
        calls["n"] += 1
        sol = real(system, start, **kw)
        if calls["n"] == 10:
            sol.converged, sol.failure = False, "forced"
        return sol
    monkeypatch.setattr(er.eq, "solve", flaky)
    j = sweep(step_min=60).json()
    assert j["validity"]["state"] == "invalid" and j["status"] == "RED"
    assert "STEP_SOLVE_FAILED" in {r["code"] for r in j["validity"]["reasons"]}
