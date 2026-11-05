"""S7 trajectory prediction: offline tests of the engine (S6 simulator driven from an observed state), geometry, hazards,
corridor, API and the real-NOAA contract example."""

import math
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring import refdata
from mooring.core.schemas import PredictionRequest, PredictionResponse, TransitRequest
from mooring.prediction import engine, presets
from mooring.prediction_examples import build
from mooring.transit import simulator as S
from mooring.transit.geo import LocalPlane

client = TestClient(app)
API = "/api/v1"
FT = 0.3048
AS_OF = presets.AS_OF


def base(**kw):
    d = {"vessel": {"vessel_id": "V", "ship_class_id": "DDG-51-FIIA", "observed_utc": (AS_OF - timedelta(seconds=1)).isoformat(),
                    "position": {"lat": 37.0, "lon": -76.0}, "heading_true_deg": 45.0, "surge_kt": 6.0, "rudder_deg": 3.0,
                    "engine_order": 0.2},
         "as_of_utc": AS_OF.isoformat(), "horizon_s": 120, "tick_s": 10}
    d.update(kw)
    return PredictionRequest.model_validate(d)


def local(plane, p):
    return plane.to_local(p.lat, p.lon)


def test_request_mapping():
    req = base(vessel={**base().vessel.model_dump(mode="json"), "surge_kt": -1.0, "sway_kt": 0.5,
                       "tugs": [{"tug_id": "T1", "point": "bow", "force_lbf": 1000, "direction_rel_deg": 90}]},
               alternatives=[{"alt_id": "a", "label": "a", "helm_commands": [{"t_s": 5, "rudder_deg": 10}]}])
    plane = LocalPlane(37.0, -76.0)
    tr = engine._transit_request(req, req.alternatives[0].helm_commands, [], dt=0.2, start_ll=(37.0, -76.0), heading=45.0,
                                 speed_kt=max(req.vessel.surge_kt, 0), env=None, plane=plane)
    v = tr.vessels[0]
    assert v.start.speed_kt == 0 and v.start.heading_true_deg == 45.0
    assert v.mode == "tug_assisted" and v.tug_commands[0].t_s == 0 and v.tug_commands[0].tug_id == "T1"
    assert [(h.t_s, h.rudder_deg, h.engine_order) for h in v.helm_commands] == [(0, 3.0, 0.2), (5, 10.0, None)]
    e, n = plane.to_local(v.route[0].lat, v.route[0].lon)           # waypoint ~20 nm ahead along the heading
    assert math.hypot(e, n) == pytest.approx(20 * 1852, rel=1e-6)
    assert math.degrees(math.atan2(e, n)) == pytest.approx(45.0, abs=1e-6)
    assert tr.duration_s == 120 and tr.sample_interval_s == 10 and tr.start_utc == AS_OF
    r = engine.predict(req)
    assert "PREDICTION_START_APPROXIMATED" in [x.code for x in r.validity.reasons]


def test_hold_equals_direct_simulator():
    req = base(environment={"wind_speed_kt": 12, "wind_gust_kt": 14, "wind_from_true_deg": 214, "current_speed_kt": 0.6,
                            "current_set_true_deg": 352, "water_level_mllw_ft": 1.0, "valid_at_utc": AS_OF.isoformat()})
    direct = TransitRequest.model_validate({
        "vessels": [{"vessel_id": "V", "ship_class_id": "DDG-51-FIIA",
                     "start": {"lat": 37.0, "lon": -76.0, "heading_true_deg": 45.0, "speed_kt": 6.0},
                     "route": [{"lat": 37.0 + 0.2 * math.cos(math.radians(45)), "lon": -76.0 + 0.25 * math.sin(math.radians(45)), "speed_kt": 6.0}],
                     "helm_commands": [{"t_s": 0, "rudder_deg": 3.0, "engine_order": 0.2}]}],
        "environment": req.environment.model_dump(mode="json"), "start_utc": AS_OF.isoformat(), "origin": {"lat": 37.0, "lon": -76.0},
        "duration_s": 120, "dt_s": 0.2, "sample_interval_s": 10})
    frames = S.run(direct).frames
    ticks = engine.predict(req).result.alternatives[0].ticks
    assert len(ticks) == len(frames)
    for f, t in zip(frames, ticks):
        s = f.vessels[0]
        assert t.position.lat == pytest.approx(s.lat, abs=1e-12) and t.position.lon == pytest.approx(s.lon, abs=1e-12)
        assert t.heading_true_deg == pytest.approx(s.heading_true_deg, abs=1e-9)
        assert t.sog_kt == pytest.approx(s.sog_kt, abs=1e-9) and t.t_s == f.t_s


def test_alternatives_are_independent():
    alts = [{"alt_id": "r", "label": "r", "helm_commands": [{"t_s": 0, "rudder_deg": 20}]},
            {"alt_id": "t", "label": "t", "tug_commands": [{"t_s": 0, "tug_id": "T1", "point": "bow", "force_lbf": 30000, "direction_rel_deg": 90}]}]
    full = engine.predict(base(alternatives=alts)).result.alternatives
    only_t = engine.predict(base(alternatives=[alts[1]])).result.alternatives
    hold = engine.predict(base()).result.alternatives
    assert [a.alt_id for a in full] == ["hold", "r", "t"]
    assert full[0].ticks == hold[0].ticks and full[2].ticks == only_t[1].ticks
    assert full[1].ticks[-1].heading_true_deg != full[0].ticks[-1].heading_true_deg
    assert full[2].ticks[-1].position != full[0].ticks[-1].position


def test_footprint_geometry():
    r = engine.predict(base(vessel={**base().vessel.model_dump(mode="json"), "heading_true_deg": 90.0, "surge_kt": 0.0, "engine_order": 0.0,
                                    "rudder_deg": 0.0}, horizon_s=5, tick_s=1))
    t = r.result.alternatives[0].ticks[0]
    plane = LocalPlane(37.0, -76.0)
    pts = [local(plane, p) for p in t.footprint]
    ship = refdata.ship("DDG-51-FIIA")
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert max(xs) - min(xs) == pytest.approx(ship.loa_ft * FT, rel=1e-6)       # heading east: length along x
    assert max(ys) - min(ys) == pytest.approx(ship.beam_ft * FT, rel=1e-6)
    bow = max(pts, key=lambda p: p[0])
    assert bow[0] == pytest.approx(ship.loa_ft * FT / 2, rel=1e-4) and abs(bow[1]) < 1e-3     # bow points east
    # 0 deg: bow north; to port (+y body) is west
    assert engine.hull_polygon(0, 0, 0.0, 100, 20).bounds == pytest.approx((-10, -50, 10, 50))


def _beside_pier(offset_ft: float, **kw):
    b = refdata.berth("NAVSTA-NORFOLK-P12-N")
    plane = LocalPlane(b.origin_lat, b.origin_lon)
    t, w = math.radians(b.face_bearing_true_deg), math.radians(b.face_bearing_true_deg - 90)
    a, d = 696 * FT, offset_ft * FT
    lat, lon = plane.to_geo(a * math.sin(t) + d * math.sin(w), a * math.cos(t) + d * math.cos(w))
    v = {"vessel_id": "V", "ship_class_id": "DDG-51-FIIA", "observed_utc": AS_OF.isoformat(), "position": {"lat": lat, "lon": lon},
         "heading_true_deg": b.face_bearing_true_deg, "surge_kt": 0.0, "engine_order": 0.0}
    return base(vessel=v, horizon_s=5, tick_s=1, hazards={"berth_id": "NAVSTA-NORFOLK-P12-N", "min_clearance_ft": kw.pop("min", 50)}, **kw)


def test_pier_clearance_hand_built():
    r = engine.predict(_beside_pier(100.0))
    a = r.result.alternatives[0]
    # hull side is 33 ft from the centreline; fender faces stand 12 ft off the face => 100 - 12 - 33 = 55 ft
    assert a.closest_approach.kind == "fender" and a.closest_approach.clearance_ft == pytest.approx(55.0, abs=0.2)
    assert a.first_breach is None and r.result.hazards_checked == ["pier", "fender"]
    # beyond the fenders: hull parallel to the face at x=696, hull spans 441..951 so pier face distance 100-33 = 67 > 55: fender wins
    r2 = engine.predict(_beside_pier(100.0, min=60))
    assert r2.result.alternatives[0].first_breach.t_s == 0 and r2.status == "RED"


def test_breach_detection_and_probability():
    r = engine.predict(presets.approach_request(alternatives=True))
    hold, rudder, tug = r.result.alternatives
    assert hold.first_breach is not None and hold.first_breach.clearance_ft < 50 and hold.first_breach.probability == 1.0
    assert hold.closest_approach.t_s >= hold.first_breach.t_s and r.status == "RED"
    assert rudder.first_breach is None and tug.first_breach is None
    nos = engine.predict(presets.approach_request(samples=0, alternatives=False)).result.alternatives[0]
    assert nos.first_breach.probability is None and nos.corridor is None and nos.ticks[0].position_sd_ft is None


def test_corridor_deterministic_and_contains_track():
    from shapely.geometry import Point, Polygon
    q = presets.approach_request(alternatives=False, samples=8, horizon_s=120)
    a, b = engine.predict(q), engine.predict(q)
    ca, cb = a.result.alternatives[0].corridor, b.result.alternatives[0].corridor
    assert ca == cb
    other = engine.predict(q.model_copy(update={"uncertainty": q.uncertainty.model_copy(update={"seed": 99})}))
    assert other.result.alternatives[0].corridor != ca
    plane = LocalPlane(q.vessel.position.lat, q.vessel.position.lon)
    poly = Polygon([local(plane, p) for p in ca])
    assert poly.is_valid
    for t in a.result.alternatives[0].ticks:
        assert poly.buffer(0.01).contains(Point(local(plane, t.position)))
    assert a.result.alternatives[0].ticks[-1].position_sd_ft > a.result.alternatives[0].ticks[0].position_sd_ft - 1e-9


def test_latency():
    q = presets.approach_request(alternatives=False, horizon_s=300, samples=16)
    engine.predict(q)
    t0 = time.perf_counter()
    engine.predict(q)
    dt = time.perf_counter() - t0
    print(f"S7 latency samples=16 horizon=300 hold only: {dt:.2f} s")
    assert dt < 3.0


def test_validity_stale_input_and_coastline():
    r = engine.predict(presets.approach_request(samples=0, alternatives=False, observed_s_ago=600))
    codes = [x.code for x in r.validity.reasons]
    assert r.validity.state == "limited" and r.backend == "real" and r.model == "mooring.prediction.trajectory"
    assert {"INPUT_AGE", "STALE_INPUT", "COASTLINE_NOT_CHECKED"} <= set(codes) and "pier" in r.result.hazards_checked
    assert "coastline" not in r.result.hazards_checked and r.result.input_age_s == 600
    assert r.manifest.resolved_inputs_hash


def test_other_vessel_clearance():
    req = base(others=[{"vessel_id": "O", "beam_ft": 60, "length_ft": 300, "path": [
        {"t_utc": AS_OF.isoformat(), "lat": 37.002, "lon": -75.998, "heading_true_deg": 0}]}])
    r = engine.predict(req)
    assert "vessel" in r.result.hazards_checked and r.result.alternatives[0].closest_approach.kind == "vessel"


def test_route_and_errors():
    q = presets.approach_request(samples=4)
    resp = client.post(f"{API}/predict/trajectory", json=q.model_dump(mode="json"))
    assert resp.status_code == 200
    PredictionResponse.model_validate(resp.json())
    bad = q.model_dump(mode="json"); bad["vessel"]["ship_class_id"] = "NOPE"
    assert client.post(f"{API}/predict/trajectory", json=bad).status_code == 422
    bad = q.model_dump(mode="json"); bad["hazards"]["berth_id"] = "NOPE"
    assert client.post(f"{API}/predict/trajectory", json=bad).status_code == 422
    pr = client.get(f"{API}/predict/presets")
    assert pr.status_code == 200 and len(pr.json()) == 2
    assert all(p["validity"]["state"] == "limited" and p["validity"]["reasons"][0]["code"] == "DEMONSTRATION_SCENARIO" for p in pr.json())


def test_examples_deterministic_and_real():
    a, b = build(), build()
    assert a == b
    resp = a["predict_trajectory_response"]
    assert "MOCK" not in str(resp) and resp["backend"] == "real" and resp["validity"]["state"] == "limited"
    PredictionRequest.model_validate(a["predict_trajectory_request"])
    env = a["predict_trajectory_request"]["environment"]
    assert env["source"] and env["metadata"]["basis"] == "observation"
