"""S6 transit: autopilot, multi-vessel clock, determinism, presets, API job flow and request validation."""

import math
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from s6_helpers import env, request, run, states, vessel

from modeling_api.main import app
from mooring.core.jobs import JobCancelled
from mooring.core.schemas import (
    TransitPreset,
    TransitRequest,
    TransitResponse,
    TransitSeries,
)
from mooring.transit import coefficients as C
from mooring.transit import presets as P
from mooring.transit import simulator as S
from mooring.transit.geo import LocalPlane

client = TestClient(app)
API = "/api/v1"
KT = C.KT_MPS


def route_east(lat=37.0, lon0=-76.0, dlon=0.1, speed=10.0):
    return [{"lat": lat, "lon": lon0 + dlon, "speed_kt": speed}]


# ---------------- autopilot ----------------

def test_los_tracks_a_straight_leg_from_an_offset_start():
    v = vessel(speed=10.0, heading=90.0, route=route_east(lat=37.0, dlon=0.1))
    v["start"]["lat"] = 37.0 + 0.0008                                    # ~90 m north of the line
    r = run([v], dur=900, dt=0.2)
    st = states(r)
    assert abs(st[-1].cross_track_ft) < 15 and abs(st[-1].heading_true_deg - 90) < 1.0
    assert max(abs(s.cross_track_ft) for s in st) < 330                     # no wild overshoot (initial offset ~295 ft)


def test_crab_compensation_holds_the_track_in_a_cross_current():
    e = env(cur_kt=2.0, cur_toward=0.0)                                   # current toward the north, track due east
    v = vessel(speed=10.0, heading=90.0, route=route_east(dlon=0.15, speed=10.0))
    r = run([v], dur=1500, dt=0.2, env=e)
    st = states(r)
    tail = st[len(st) // 2:]
    assert max(abs(s.cross_track_ft) for s in tail) < 25
    assert 5 < tail[-1].heading_true_deg - 90 < 20            # heading south of east cancels a northward set (asin(2/10) = 11.5 deg)
    assert tail[-1].cog_true_deg == pytest.approx(90, abs=1.5)


def test_waypoint_switching_and_events():
    route = [{"lat": 37.0, "lon": -75.95, "speed_kt": 10}, {"lat": 37.04, "lon": -75.95, "speed_kt": 10},
             {"lat": 37.04, "lon": -75.90, "speed_kt": 10, "acceptance_radius_ft": 600}]
    r = run([vessel(speed=10.0, heading=90.0, route=route)], dur=3600, dt=0.5)
    kinds = [e.kind for e in r.events if e.vessel_id == "A"]
    assert kinds.count("waypoint_reached") == 2 and kinds[-1] == "arrived"
    assert [s.leg_index for s in states(r)][0] == 0 and max(s.leg_index for s in states(r)) == 2


def test_arrival_slowdown_reaches_zero_speed_inside_radius():
    route = [{"lat": 37.0, "lon": -75.95, "speed_kt": 12, "acceptance_radius_ft": 300}]
    v = vessel(speed=12.0, heading=90.0, route=route, autopilot={"arrival_slowdown_nm": 0.5, "arrival_speed_kt": 0.0})
    r = run([v], dur=2400, dt=0.2)
    st = states(r)
    assert st[-1].status == "arrived"
    assert any(e.kind == "arrived" for e in r.events)
    assert st[-1].stw_kt <= 0.5 + 1e-9 and st[-1].distance_to_go_nm * 1852 < 300 * 0.3048 + 1
    # astern was used for braking near the end
    assert min(s.engine_order for s in st) < 0


def test_stopped_short_logic_and_manual_engine_exemption():
    from mooring.transit.autopilot import Autopilot
    def ap():
        return Autopilot([(0.0, 0.0), (0.0, 20000.0)], [8 * KT], [300.0], L=142.0, v_max=15.0, lookahead_ls=2.0, slow_dist_m=926.0,
                         v_arrival=0.0, max_rudder=0.6, m33=1e10, m11=1e7)
    a = ap()
    ev = []
    for k in range(700):                                  # stationary with an 8 kt target, far from the end: 140 s at dt 0.2
        ev += a.update(k * 0.2, 0.2, (0.0, 0.0), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0).events
    assert a.status == "stopped_short" and [k for k, _ in ev] == ["stopped_short"]
    b = ap()
    for k in range(700):                                  # same, but the engine is under scripted control: never declared
        b.update(k * 0.2, 0.2, (0.0, 0.0), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, engine_manual=True)
    assert b.status == "underway"
    # a ship making way never trips it
    r = run([vessel(speed=0.0, heading=90.0, route=route_east(dlon=0.05, speed=8.0))], dur=400, dt=0.5)
    assert not any(e.kind == "stopped_short" for e in r.events)


def test_start_utc_and_synthetic_epoch_in_tracks():
    req = request([vessel(speed=10.0, heading=90.0, route=route_east(dlon=0.05))], dur=100, sample=10.0)
    r = S.run(req)
    assert r.synthetic_epoch and r.vessels[0].track[0].t_utc == datetime(2000, 1, 1, tzinfo=UTC)
    assert all(f.t_utc is None for f in r.frames)
    t0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    req2 = request([vessel(speed=10.0, heading=90.0, route=route_east(dlon=0.05))], dur=100, sample=10.0, start_utc=t0.isoformat())
    r2 = S.run(req2)
    assert r2.frames[1].t_utc == t0.replace(second=10) and r2.vessels[0].track[1].t_utc == t0.replace(second=10)
    assert r2.vessels[0].track[1].source.startswith("simulated:")


# ---------------- clock, independence, determinism ----------------

def _two():
    a = vessel("A", "DDG-51-FIIA", speed=10.0, heading=90.0, route=route_east(dlon=0.08))
    b = vessel("B", "CVN-68", speed=8.0, heading=0.0, route=[{"lat": 37.05, "lon": -76.0, "speed_kt": 10}])
    b["start"]["lon"] = -75.99
    return a, b


def test_multi_vessel_independence_and_order_invariance():
    a, b = _two()
    alone = run([a], dur=600, dt=0.2)
    both = run([a, b], dur=600, dt=0.2)
    swapped = run([b, a], dur=600, dt=0.2)
    for other in (both, swapped):
        sa, sb = [s.model_dump() for s in states(alone)], [s.model_dump() for s in states(other)]
        n = min(len(sa), len(sb))
        assert sa[:n] == sb[:n]
    assert [s.model_dump() for s in states(both, "B")] == [s.model_dump() for s in states(swapped, "B")]
    assert {v.vessel_id for v in both.frames[-1].vessels} == {"A", "B"}


def test_determinism_same_request_identical_series_and_hash():
    req = request(list(_two()), dur=300, dt=0.2)
    a = S.simulate_transit(req, "det-a", "/api/v1")
    b = S.simulate_transit(req, "det-b", "/api/v1")
    assert [f.model_dump() for f in S.SERIES["det-a"].frames] == [f.model_dump() for f in S.SERIES["det-b"].frames]
    assert a.manifest.resolved_inputs_hash == b.manifest.resolved_inputs_hash and a.inputs_hash == b.inputs_hash
    assert [v.model_dump(exclude={"track"}) for v in a.result.vessels] == [v.model_dump(exclude={"track"}) for v in b.result.vessels]


def test_envelope_contents():
    req = request([vessel(speed=10.0, heading=90.0, route=route_east(dlon=0.03), mode="tug_assisted",
                          tug_assist={"policy": "auto", "tug_ids": ["T1", "T2"]})], dur=120)
    res = S.simulate_transit(req, "env-1", "/api/v1")
    assert res.model == "mooring.transit.simulator" and res.backend == "real" and res.status == "AMBER"
    codes = {r.code for r in res.validity.reasons}
    assert res.validity.state == "limited"
    assert {"TRANSIT_SURROGATE_MANEUVERING", "PROPULSION_ASSUMED", "DEEP_WATER_NO_SQUAT_OR_BANK", "NO_SHIP_INTERACTION",
            "TUG_KINEMATICS_NOT_MODELED", "CALM_ASSUMED", "SYNTHETIC_EPOCH"} <= codes
    assert res.manifest.resolved_inputs_hash and res.assumptions
    TransitResponse.model_validate(res.model_dump(mode="json"))
    own = S.simulate_transit(request([vessel(speed=10.0, heading=90.0, route=route_east(dlon=0.03))], dur=60,
                                     env=env(wind_kt=5, wind_from=10)), "env-2", "/api/v1")
    assert "CALM_ASSUMED" not in {r.code for r in own.validity.reasons}
    assert "TUG_KINEMATICS_NOT_MODELED" not in {r.code for r in own.validity.reasons}


def test_cancellation_is_cooperative():
    class Ctx:
        calls = 0
        def check_cancelled(self):
            self.calls += 1
            if self.calls == 3:
                raise JobCancelled()
        def progress(self, *a):
            pass
    with pytest.raises(JobCancelled):
        S.simulate_transit(request([vessel(speed=10.0, heading=90.0, route=route_east(dlon=0.3))], dur=3000), "c-1", "/api/v1", Ctx())


# ---------------- request validation ----------------

def test_unknown_speed_basis_is_invalid_not_guessed(monkeypatch):
    monkeypatch.delitem(C.DEFAULT_MAX_SPEED_KT, "LHD-1")
    req = request([vessel(cls="LHD-1", route=route_east())], dur=10)
    with pytest.raises(S.RequestInvalid, match="max_speed_kt"):
        S.prepare(req)
    ok = request([vessel(cls="LHD-1", route=route_east(), propulsion={"max_speed_kt": 20})], dur=10)
    S.prepare(ok)
    r = client.post(f"{API}/transit/simulate", json=req.model_dump(mode="json"))
    assert r.status_code == 422 and "max_speed_kt" in r.text


def test_api_422_for_own_thrust_with_tug_commands_and_unknown_tug():
    body = request([vessel(speed=5.0, route=route_east())], dur=10).model_dump(mode="json")
    body["vessels"][0]["tug_commands"] = [{"t_s": 0, "tug_id": "T1", "point": "bow", "force_lbf": 1000, "direction_rel_deg": 0}]
    assert client.post(f"{API}/transit/simulate", json=body).status_code == 422
    body["vessels"][0]["mode"] = "tug_assisted"
    body["vessels"][0]["tug_commands"][0]["tug_id"] = "NOPE"
    r = client.post(f"{API}/transit/simulate", json=body)
    assert r.status_code == 422 and "NOPE" in r.text
    body["vessels"][0]["tug_commands"] = []
    body["vessels"][0]["ship_class_id"] = "NOT-A-SHIP"
    assert client.post(f"{API}/transit/simulate", json=body).status_code == 422


def test_duplicate_vessel_ids_rejected():
    body = request([vessel(route=route_east())], dur=10).model_dump(mode="json")
    body["vessels"].append(dict(body["vessels"][0]))
    assert client.post(f"{API}/transit/simulate", json=body).status_code == 422


def test_range_beyond_40_km_is_flagged():
    far = request([vessel(route=[{"lat": 37.6, "lon": -76.0, "speed_kt": 10}])], dur=10)
    res = S.simulate_transit(far, "far-1", "/api/v1")
    assert "GEO_TANGENT_PLANE_RANGE" in {r.code for r in res.validity.reasons}


# ---------------- presets ----------------

def test_presets_list_and_each_validates():
    r = client.get(f"{API}/transit/presets")
    assert r.status_code == 200
    items = [TransitPreset.model_validate(p) for p in r.json()]
    assert len(items) == 4
    assert {i.preset_id for i in items} == {"ddg-inbound-own-thrust", "ddg-inbound-tug-assisted", "ddg-outbound-own-thrust", "two-vessels"}
    for i in items:
        assert i.validity.state == "limited" and "navigational advice" in i.description
        TransitRequest.model_validate(i.request.model_dump(mode="json"))
    assert any(len(i.request.vessels) == 2 for i in items)


@pytest.mark.parametrize("pid", ["ddg-inbound-own-thrust", "ddg-inbound-tug-assisted", "ddg-outbound-own-thrust", "two-vessels"])
def test_every_preset_completes_and_arrives(pid, capsys):
    preset = next(p for p in P.presets() if p.preset_id == pid)
    t = time.perf_counter()
    r = S.run(preset.request)
    wall = time.perf_counter() - t
    for v in r.vessels:
        assert v.status == "arrived", (pid, v.vt.vessel_id, v.status)
        assert not v.invalid
    assert r.t_end < preset.request.duration_s
    print(f"S6 preset {pid}: " + "; ".join(f"{v.vt.vessel_id} arrived {v.arrival_t:.0f} s, {v.dist_m / 1852:.2f} nm, max xtrack "
          f"{v.max_xt / 0.3048:.0f} ft, max rudder {math.degrees(v.max_rudder):.1f} deg, max tug {v.max_tug_n / C.LBF_N:.0f} lbf"
          for v in r.vessels) + f"; wall {wall:.2f} s")


def test_inbound_preset_ends_near_pier_and_tug_preset_uses_tugs():
    pre = {p.preset_id: p for p in P.presets()}
    own = S.run(pre["ddg-inbound-own-thrust"].request)
    assisted = S.run(pre["ddg-inbound-tug-assisted"].request)
    plat, plon = P.pier_point()
    for run_ in (own, assisted):
        s = run_.frames[-1].vessels[0]
        plane = LocalPlane(plat, plon)
        e, n = plane.to_local(s.lat, s.lon)
        assert math.hypot(e, n) < 300 * 0.3048 + 5
    assert not any(s.tugs for f in own.frames for s in f.vessels)
    assert any(s.tugs for f in assisted.frames for s in f.vessels)
    assert all(t.force_lbf <= 130000 + 1e-6 for f in assisted.frames for s in f.vessels for t in s.tugs)


# ---------------- API job flow ----------------

def _finish(accepted, timeout_s=60.0):
    deadline = time.monotonic() + timeout_s
    st = client.get(accepted["status_url"]).json()
    while st["state"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.02)
        st = client.get(accepted["status_url"]).json()
    assert st["state"] == "succeeded", st
    return st["result"]


def test_api_job_flow_simulate_series_summaries():
    preset = next(p for p in client.get(f"{API}/transit/presets").json() if p["preset_id"] == "two-vessels")
    r = client.post(f"{API}/transit/simulate", json=preset["request"])
    assert r.status_code == 202, r.text
    res = _finish(r.json())
    TransitResponse.model_validate(res)
    assert res["model"] == "mooring.transit.simulator" and res["backend"] == "real" and res["status"] == "AMBER"
    assert {v["vessel_id"] for v in res["result"]["vessels"]} == {"DDG-IN", "CG-OUT"}
    assert all(v["arrived"] for v in res["result"]["vessels"])
    series = client.get(res["result"]["series_url"])
    assert series.status_code == 200
    TransitSeries.model_validate(series.json())
    frames = series.json()["frames"]
    assert len(frames) > 100 and len(frames[0]["vessels"]) == 2
    track = res["result"]["vessels"][0]["track"]
    assert len(track) == len(frames) and track[0]["t_utc"].startswith("2000-01-01")
    assert client.get(f"{API}/transit/simulations/job_nope/series").status_code == 404
