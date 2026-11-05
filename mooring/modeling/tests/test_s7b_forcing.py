"""S7b: prediction with S2 time-varying forcing: same resolver, explicit basis, no silent extrapolation or engine switch."""
import copy
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from mooring.berthing.forcing import ForcingSeries
from mooring.core.schemas import PredictionRequest
from mooring.prediction import engine, presets

AS_OF = presets.AS_OF
ENV = {"wind_speed_kt": 10, "wind_gust_kt": 12, "wind_from_true_deg": 270, "current_speed_kt": 0.5, "current_set_true_deg": 90,
       "water_level_mllw_ft": 2.0, "valid_at_utc": AS_OF.isoformat()}


def req(**kw):
    d = {"vessel": {"vessel_id": "V", "ship_class_id": "DDG-51-FIIA", "observed_utc": (AS_OF - timedelta(seconds=1)).isoformat(),
                    "position": {"lat": 37.0, "lon": -76.0}, "heading_true_deg": 90.0, "surge_kt": 10.0, "engine_order": 0.3},
         "as_of_utc": AS_OF.isoformat(), "horizon_s": 120, "tick_s": 20, "environment": ENV, "hazards": {"coastline": False}}
    d.update(kw)
    return PredictionRequest.model_validate(d)


def codes(r):
    return [x.code for x in r.validity.reasons]


RAMP = {"kind": "ramp", "ramp_start_s": 0, "target": {"t_s": 120, "wind_speed_kt": 40, "wind_gust_kt": 45, "wind_from_true_deg": 0}}


def replay(end, policy="stop"):
    def mk(t, w):
        return {"t_s": t, "wind_speed_kt": w, "wind_gust_kt": w, "wind_from_true_deg": 0.0}
    return {"kind": "replay", "samples": [mk(0, 5), mk(end, 30)], "on_uncovered": policy}


def test_default_unchanged_and_fixed_basis():
    r = engine.predict(req(environment=None))
    assert r.result.forcing_basis.kind == "fixed_environment" and r.result.forcing_basis.revision is None
    wire = r.model_dump(mode="json")
    assert "forcing_basis" not in wire["result"]               # additive field omitted on the default wire shape
    assert "forcing" not in wire["result"] and "FORCING_TIME_VARYING" not in codes(r)
    assert "forcing" not in req().model_dump(mode="json") and "engine" not in req().model_dump(mode="json")


def test_time_varying_basis_and_dynamics_differ():
    fixed = engine.predict(req())
    vary = engine.predict(req(forcing=RAMP))
    b = vary.result.forcing_basis
    assert b.kind == "time_varying" and b.synthetic and b.revision.startswith("frc-")
    assert (b.coverage.start_s, b.coverage.end_s) == (0.0, 120.0) and not b.truncated
    assert {"FORCING_TIME_VARYING", "FORCING_SYNTHETIC"} <= set(codes(vary))
    f, v = fixed.result.alternatives[0].ticks, vary.result.alternatives[0].ticks
    assert f[0].position == v[0].position                      # anchor: identical start state
    assert (f[-1].position.lat, f[-1].position.lon) != (v[-1].position.lat, v[-1].position.lon)
    assert vary.model_dump(mode="json")["result"]["forcing_basis"]["kind"] == "time_varying"


def test_steady_forcing_matches_fixed_environment():
    a = engine.predict(req()).result.alternatives[0].ticks[-1]
    b = engine.predict(req(forcing={"kind": "steady"})).result.alternatives[0].ticks[-1]
    assert a.position.lat == pytest.approx(b.position.lat, abs=1e-6) and a.position.lon == pytest.approx(b.position.lon, abs=1e-6)


def test_same_resolver_revision_matches_s2_series():
    r = req(forcing=RAMP)
    got = engine.predict(r).result.forcing_basis.revision
    assert got == ForcingSeries(r.forcing, r.environment, r.horizon_s).revision


def test_deterministic():
    a = engine.predict(req(forcing=RAMP)).result.alternatives[0].ticks[-1].position
    b = engine.predict(req(forcing=RAMP)).result.alternatives[0].ticks[-1].position
    assert a == b


def test_replay_uncovered_stop_rejects():
    with pytest.raises(engine.RequestInvalid, match="FORCING_UNCOVERED"):
        engine.predict(req(forcing=replay(60)))


def test_replay_uncovered_invalidate_truncates_with_reason():
    r = engine.predict(req(forcing=replay(70, "invalidate")))
    b = r.result.forcing_basis
    assert b.truncated and b.requested_horizon_s == 120 and b.horizon_s == 60
    assert r.result.alternatives[0].ticks[-1].t_s == 60
    assert "FORCING_HORIZON_TRUNCATED" in codes(r) and "FORCING_SUPPLIED_UNVERIFIED" in codes(r)


def test_replay_not_covering_snapshot_time_rejected():
    spec = replay(300)
    for s in spec["samples"]:
        s["t_s"] += 30
    with pytest.raises(engine.RequestInvalid, match="FORCING_UNCOVERED"):
        engine.predict(req(forcing=spec))


def test_berthing_engine_unsupported_never_switched():
    with pytest.raises(engine.Unsupported, match="ENGINE_UNSUPPORTED"):
        engine.predict(req(engine="berthing"))
    from modeling_api.main import app
    resp = TestClient(app).post("/api/v1/predict/trajectory", json=req(engine="berthing").model_dump(mode="json"))
    assert resp.status_code == 501 and "ENGINE_UNSUPPORTED" in resp.text
    assert engine.predict(req()).result.engine == "transit"


def test_clone_and_no_mutation_with_forcing_and_alternatives():
    r = req(forcing=RAMP, alternatives=[{"alt_id": "left", "label": "L", "helm_commands": [{"t_s": 10, "rudder_deg": 15}]}],
            uncertainty={"samples": 4, "seed": 1})
    before = copy.deepcopy(r.model_dump(mode="json"))
    out = engine.predict(r)
    assert r.model_dump(mode="json") == before
    assert [a.alt_id for a in out.result.alternatives] == ["hold", "left"]
    assert all(a.corridor for a in out.result.alternatives)    # forcing gives a spread source
    assert out.result.alternatives[0].ticks[0].position == out.result.alternatives[1].ticks[0].position
