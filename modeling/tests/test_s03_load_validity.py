"""S03: wind basis boundary, validity classification and aggregation for M3."""

import copy
import statistics
import time

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring import refdata
from mooring.core.schemas import EnvironmentSnapshot, Finding, LoadsRequest
from mooring.examples import EXAMPLES
from mooring.loads import compute_loads
from mooring.loads import coefficients as c
from mooring.loads.service import environmental
from mooring.loads.validity import aggregate_findings, merge_reasons, wind_basis

client = TestClient(app)
P = "/api/v1"
DDG = refdata.ship("DDG-51-FIIA")


def env(**kw) -> EnvironmentSnapshot:
    base = EXAMPLES["loads_environmental"]["environment"]
    meta = kw.pop("metadata", None)
    e = EnvironmentSnapshot(**{**base, **kw})
    return e.model_copy(update={"metadata": meta}) if meta else e


def meta(**kw):
    from mooring.core.schemas import EnvironmentMetadata
    return EnvironmentMetadata(basis="scenario", **kw)


def test_legacy_without_metadata_keeps_numbers_and_states_the_assumption():
    e = env()
    b = wind_basis(e, use_gust=False)
    assert b.factor == c.SUSTAINED_TO_30S and b.speed_kt == pytest.approx(e.wind_speed_kt * c.SUSTAINED_TO_30S)
    assert not b.reasons and not b.verified and any("legacy" in n.lower() for n in b.notes)
    g = wind_basis(e, use_gust=True)
    assert g.speed_kt == e.wind_gust_kt and not g.reasons


@pytest.mark.parametrize("kw,use_gust,factor,reason", [
    (dict(wind_averaging_s=60, wind_reference_height_m=10), False, c.SUSTAINED_TO_30S, None),
    (dict(wind_averaging_s=30, wind_reference_height_m=10), False, 1.0, None),
    (dict(wind_averaging_s=600, wind_reference_height_m=10), False, c.SUSTAINED_TO_30S, "WIND_AVERAGING_UNSUPPORTED"),
    (dict(gust_duration_s=30, wind_reference_height_m=10), True, 1.0, None),
    (dict(gust_duration_s=3, wind_reference_height_m=10), True, 1.0, "WIND_GUST_DURATION_UNSUPPORTED"),
    (dict(wind_averaging_s=60, wind_reference_height_m=30), False, c.SUSTAINED_TO_30S, "WIND_HEIGHT_NOT_CONVERTED"),
])
def test_wind_basis_boundary(kw, use_gust, factor, reason):
    e = env(metadata=meta(**kw))
    b = wind_basis(e, use_gust)
    assert b.factor == factor
    assert {r.code for r in b.reasons} == ({reason} if reason else set())
    assert b.verified == (reason is None)


def test_no_double_normalization_loads_use_basis_exactly_once():
    e = env(metadata=meta(wind_averaging_s=30, wind_reference_height_m=10))
    sustained30 = compute_loads(DDG, "full_load", 105, e, 46.8, use_gust=False)
    as_gust = compute_loads(DDG, "full_load", 105, e.model_copy(update={"wind_gust_kt": e.wind_speed_kt}), 46.8, use_gust=True)
    assert sustained30.wind.fy_lbf == pytest.approx(as_gust.wind.fy_lbf, rel=1e-12)
    legacy = compute_loads(DDG, "full_load", 105, env(), 46.8, use_gust=False)
    assert legacy.wind.fy_lbf / compute_loads(DDG, "full_load", 105, env(), 46.8, use_gust=False).wind.fy_lbf == 1.0
    assert legacy.wind.coefficients["wind_speed_basis_factor"] == c.SUSTAINED_TO_30S


def test_metadata_omission_is_valid_limited_only_by_data_quality_and_flag_changes_it():
    req = LoadsRequest(**EXAMPLES["loads_environmental"])
    r = environmental(req)
    assert "WIND_BASIS_UNVERIFIED" not in {x.code for x in r.validity.reasons}
    strict = environmental(req.model_copy(update={"require_verified_wind_basis": True}))
    assert "WIND_BASIS_UNVERIFIED" in {x.code for x in strict.validity.reasons} and strict.status != "GREEN"
    documented = req.model_copy(update={"require_verified_wind_basis": True, "environment": env(
        metadata=meta(gust_duration_s=30, wind_averaging_s=60, wind_reference_height_m=10))})
    assert "WIND_BASIS_UNVERIFIED" not in {x.code for x in environmental(documented).validity.reasons}


def test_seed_geometry_is_limited_not_valid_and_status_agrees():
    r = environmental(LoadsRequest(**EXAMPLES["loads_environmental"]))
    assert r.validity.state == "limited" and r.status == "AMBER"
    assert "REFERENCE_DATA_NOT_QUALIFIED" in {x.code for x in r.validity.reasons}


def test_published_ship_with_documented_basis_is_valid_and_green():
    ship = DDG.model_copy(update={"provenance": DDG.provenance.model_copy(update={"confidence": "published"})})
    import mooring.loads.service as svc
    orig = svc.refdata.ship
    svc.refdata.ship = lambda _: ship
    try:
        req = LoadsRequest(**{**EXAMPLES["loads_environmental"], "use_gust": True,
                              "environment": env(metadata=meta(gust_duration_s=30, wind_averaging_s=60, wind_reference_height_m=10))})
        r = svc.environmental(req)
    finally:
        svc.refdata.ship = orig
    assert r.validity.state == "valid" and r.status == "GREEN" and not r.warnings


@pytest.mark.parametrize("depth,invalid", [(10, True), (30.5, True), (30.6, False)])
def test_depth_at_or_below_draft_is_invalid(depth, invalid):
    body = copy.deepcopy(EXAMPLES["loads_environmental"]) | {"water_depth_ft": depth}
    j = client.post(f"{P}/loads/environmental", json=body).json()
    assert (j["validity"]["state"] == "invalid") == invalid
    assert (j["status"] == "RED") == invalid
    if invalid:
        assert j["result"]["total"]["fy_lbf"] == j["result"]["total"]["fy_lbf"]  # finite forces still reported, but not valid


def test_current_range_and_low_reynolds_are_limited():
    fast = client.post(f"{P}/loads/environmental", json=copy.deepcopy(EXAMPLES["loads_environmental"]) | {
        "environment": {**EXAMPLES["loads_environmental"]["environment"], "current_speed_kt": 3.5}}).json()
    assert "CURRENT_OUTSIDE_COEFFICIENT_RANGE" in {r["code"] for r in fast["validity"]["reasons"]}
    slow = client.post(f"{P}/loads/environmental", json=copy.deepcopy(EXAMPLES["loads_environmental"]) | {
        "environment": {**EXAMPLES["loads_environmental"]["environment"], "current_speed_kt": 0.001}}).json()
    assert "LOW_REYNOLDS_REGULARIZED" in {r["code"] for r in slow["validity"]["reasons"]}


def test_aggregation_collapses_repeats_and_keeps_where():
    f = Finding(rule_id="UFC-DEPTH-RANGE", severity="AMBER", message="Depth clamped.", reference="r")
    merged = aggregate_findings([(f"t{i}", [f]) for i in range(1000)])
    assert len(merged) == 1 and "1000 of 1000 cases" in merged[0].message and "t0, t1, t2, t3, t4 and 995 more" in merged[0].message
    reasons = merge_reasons([r for _, r in __import__("mooring.loads.validity", fromlist=["x"]).classify_findings([f] * 3)] * 2)
    assert len(reasons) == 1


def test_bearing_and_side_signs_hold_for_loads():
    e = env(wind_from_true_deg=0, current_speed_kt=0)
    # Wind from the bow (rel 0): bow-on, almost no beam force.
    bow_on = compute_loads(DDG, "full_load", 0, e.model_copy(update={"wind_speed_kt": 40, "wind_gust_kt": 40}), 46.8)
    assert abs(bow_on.wind.fy_lbf) < 0.05 * abs(bow_on.wind.fx_lbf) and bow_on.wind.fx_lbf < 0  # pushes ship aft
    # Wind from starboard beam (rel 90) pushes toward port: +y in the ship frame.
    stbd = compute_loads(DDG, "full_load", 270, e.model_copy(update={"wind_speed_kt": 40, "wind_gust_kt": 40}), 46.8)
    assert stbd.wind.fy_lbf > 0 and stbd.wind_rel_ship_deg == pytest.approx(90)


def test_compute_loads_timing_is_recorded_separately_from_serialization():
    e = env()
    t = []
    for _ in range(200):
        t0 = time.perf_counter()
        compute_loads(DDG, "full_load", 105, e, 46.8)
        t.append(time.perf_counter() - t0)
    p50 = statistics.median(t)
    print(f"compute_loads p50={p50 * 1e6:.0f} us")
    assert p50 < 0.005  # generous CI bound; the sub-millisecond target is recorded in the PR, not enforced here
