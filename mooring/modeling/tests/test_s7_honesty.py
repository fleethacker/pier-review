"""S7 honesty and bounds: hazard coverage, swept hull between samples, uncertainty unavailable (not zero), clone safety."""

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from mooring.core.schemas import PredictionRequest
from mooring.prediction import engine, presets

AS_OF = presets.AS_OF


def req(**kw):
    d = {"vessel": {"vessel_id": "V", "ship_class_id": "DDG-51-FIIA", "observed_utc": (AS_OF - timedelta(seconds=1)).isoformat(),
                    "position": {"lat": 37.0, "lon": -76.0}, "heading_true_deg": 90.0, "surge_kt": 10.0, "engine_order": 0.3},
         "as_of_utc": AS_OF.isoformat(), "horizon_s": 120, "tick_s": 60, "hazards": {"coastline": False}}
    d.update(kw)
    return PredictionRequest.model_validate(d)


def codes(r):
    return [x.code for x in r.validity.reasons]


def other(lat, lon, hdg=0.0, **kw):
    return {"vessel_id": "O", "beam_ft": 60, "length_ft": 300, "path": [{"t_utc": AS_OF.isoformat(), "lat": lat, "lon": lon,
                                                                          "heading_true_deg": hdg}], **kw}


# ---- hazard coverage honesty
def test_no_hazard_layers_is_unknown_coverage_never_all_clear():
    r = engine.predict(req())
    a = r.result.alternatives[0]
    assert r.result.hazards_checked == []
    assert a.closest_approach is None and a.first_breach is None
    assert "HAZARD_COVERAGE_UNKNOWN" in codes(r) and r.validity.state == "limited"
    assert "NOT an all-clear" in next(x.message for x in r.validity.reasons if x.code == "HAZARD_COVERAGE_UNKNOWN")


def test_partial_coverage_names_the_unchecked_kinds():
    r = engine.predict(presets.approach_request(samples=0, alternatives=False))
    c = next(x for x in r.validity.reasons if x.code == "HAZARD_COVERAGE_INCOMPLETE")
    assert "coastline" in c.message and "vessel" in c.message and "pier" not in c.message.split("Checked:")[0]
    assert "HAZARD_COVERAGE_UNKNOWN" not in codes(r)


# ---- swept hull between samples
def test_other_vessel_between_samples_is_detected_by_the_swept_hull():
    # Own ship runs east at ~10 kt (about 308 m per 60 s tick). The other vessel sits directly on the track 150 m ahead:
    # no tick footprint touches it (ticks at 0 s and 60 s), but the swept hull between them does.
    # 150 m of longitude at 37 N:
    dlon = 150 / (111_320 * 0.7986)
    r = engine.predict(req(others=[other(37.0, -76.0 + dlon, 0.0)], hazards={"coastline": False, "min_clearance_ft": 50}))
    a = r.result.alternatives[0]
    tick_positions = [t.position.lon for t in a.ticks]
    assert all(abs(lon - (-76.0 + dlon)) > 40 / (111_320 * 0.7986) for lon in tick_positions)   # no tick sits on it
    assert a.first_breach is not None and a.first_breach.kind == "vessel"
    assert a.closest_approach.kind == "vessel" and a.closest_approach.clearance_ft <= 0.5      # contact between samples
    assert r.status == "RED"


def test_initial_overlap_is_reported_at_t0():
    r = engine.predict(req(others=[other(37.0, -76.0, 90.0)]))
    a = r.result.alternatives[0]
    assert a.first_breach is not None and a.first_breach.t_s == 0 and a.closest_approach.clearance_ft <= 0.0


def test_swept_check_adds_a_validity_note():
    assert "SWEPT_HULL_CHECK" in codes(engine.predict(req()))


def test_short_other_vessel_path_is_disclosed():
    r = engine.predict(req(others=[other(37.1, -76.1)]))     # one fix at as_of; horizon 120 s is not covered
    assert "OTHER_VESSEL_PATH_SHORT" in codes(r)


# ---- uncertainty unavailable, not zero width
def test_samples_without_any_spread_source_report_unavailable_not_zero_width():
    r = engine.predict(req(uncertainty={"samples": 8, "seed": 1}))      # no state uncertainty, no environment
    a = r.result.alternatives[0]
    assert a.corridor is None and all(t.position_sd_ft is None for t in a.ticks)
    assert "UNCERTAINTY_UNAVAILABLE" in codes(r) and "UNCERTAINTY_ILLUSTRATIVE" not in codes(r)


def test_zero_samples_report_unavailable():
    r = engine.predict(req())
    assert "UNCERTAINTY_UNAVAILABLE" in codes(r) and r.result.alternatives[0].corridor is None


def test_single_sample_cannot_give_a_spread():
    v = {**req().vessel.model_dump(mode="json"), "uncertainty": {"position_sd_ft": 15, "heading_sd_deg": 1, "speed_sd_kt": 0.2}}
    r = engine.predict(req(vessel=v, uncertainty={"samples": 1}))
    assert r.result.alternatives[0].corridor is None and "UNCERTAINTY_UNAVAILABLE" in codes(r)


def test_real_spread_still_gives_corridor_and_nonzero_sd():
    v = {**req().vessel.model_dump(mode="json"), "uncertainty": {"position_sd_ft": 15, "heading_sd_deg": 1, "speed_sd_kt": 0.2}}
    r = engine.predict(req(vessel=v, uncertainty={"samples": 6, "seed": 3}))
    a = r.result.alternatives[0]
    assert a.corridor and max(t.position_sd_ft for t in a.ticks) > 0
    assert "UNCERTAINTY_ILLUSTRATIVE" in codes(r) and "UNCERTAINTY_UNAVAILABLE" not in codes(r)


# ---- the prediction clone never mutates the caller's state
def test_predict_does_not_mutate_the_request():
    q = presets.approach_request(samples=4, alternatives=True)
    before = json.dumps(q.model_dump(mode="json"), sort_keys=True)
    a = engine.predict(q)
    assert json.dumps(q.model_dump(mode="json"), sort_keys=True) == before
    b = engine.predict(q)       # repeatable from the same untouched input
    assert a.result.alternatives[0].ticks[-1].position == b.result.alternatives[0].ticks[-1].position


def test_predict_does_not_touch_stored_sessions_or_missions():
    from mooring.core.store import db
    d = db()
    # The prediction response is an ordinary stored result (results/ownership rows); live state is docs (sessions, missions,
    # scenarios), jobs and snapshots, and none of those may change.
    live = ("docs", "jobs", "snapshots")
    counts = lambda: {t: d.execute(f"SELECT COUNT(*) FROM {t}")[0][0] for t in live}  # noqa: E731
    before = counts()
    engine.predict(presets.approach_request(samples=2, alternatives=False))
    assert counts() == before


# ---- bounds
@pytest.mark.parametrize("patch", [{"horizon_s": 901}, {"horizon_s": 0}, {"tick_s": 0.5}, {"uncertainty": {"samples": 65}},
                                   {"alternatives": [{"alt_id": f"a{i}", "label": "x"} for i in range(5)]},
                                   {"alternatives": [{"alt_id": "hold", "label": "x"}]}])
def test_request_bounds_rejected_by_schema(patch):
    with pytest.raises(ValidationError):
        req(**patch)


def test_non_finite_or_implausible_state_is_422_via_engine():
    for bad in (float("nan"), float("inf"), 500.0):
        q = req()
        q = q.model_copy(update={"vessel": q.vessel.model_copy(update={"surge_kt": bad})})
        with pytest.raises(engine.RequestInvalid):
            engine.predict(q)
