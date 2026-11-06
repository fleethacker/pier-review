"""Product audit F06–F08/F26: full horizons, contact, environmental evidence and genuine spread sources."""
from datetime import UTC, datetime, timedelta

import pytest

from mooring import refdata
from mooring.core.forcing import ForcingSeries
from mooring.core.schemas import PredictionRequest
from mooring.loads.validity import environment_findings, wind_basis
from mooring.prediction import engine, forced
from mooring.transit import simulator
from mooring.transit.geo import LocalPlane

T0 = datetime(2026, 11, 5, 17, tzinfo=UTC)
PLANE = LocalPlane(37, -76)
CALM = dict(valid_at_utc=T0, wind_speed_kt=0, wind_gust_kt=0, wind_from_true_deg=0,
            current_speed_kt=0, current_set_true_deg=0, water_level_mllw_ft=0)


def request(**kw):
    body = dict(vessel=dict(vessel_id="V", ship_class_id="DDG-51-FIIA", observed_utc=T0,
                           position=dict(lat=37, lon=-76), heading_true_deg=90, surge_kt=10, engine_order=0.03),
                as_of_utc=T0, horizon_s=11, tick_s=10, dt_s=0.2, environment=CALM,
                hazards=dict(coastline=False, min_clearance_ft=0))
    return PredictionRequest.model_validate(body | kw)


def transit(req):
    return engine._transit_request(req, [], [], dt=req.dt_s, start_ll=(37, -76), heading=90, speed_kt=10,
                                   env=req.environment, plane=PLANE, sample_s=req.tick_s)


def other(lat, lon, length=1, beam=1):
    return dict(vessel_id="O", length_ft=length, beam_ft=beam, path=[
        dict(t_utc=T0, lat=lat, lon=lon, heading_true_deg=90),
        dict(t_utc=T0 + timedelta(seconds=30), lat=lat, lon=lon, heading_true_deg=90)])


@pytest.mark.parametrize("horizon", [1, 11, 10.3])
@pytest.mark.parametrize("forcing", [None, {"kind": "steady"}])
def test_full_horizon_is_integrated_and_retained_after_decimation(horizon, forcing):
    req = request(horizon_s=horizon, forcing=forcing)
    treq = transit(req)
    direct = simulator.run(treq) if forcing is None else forced.run(treq, ForcingSeries(req.forcing, req.environment, horizon))
    assert direct.t_end == horizon and direct.frames[-1].t_s == horizon
    assert direct.vessels[0].t == pytest.approx(horizon)
    ticks = engine.predict(req).result.alternatives[0].ticks
    assert ticks[-1].t_s == horizon
    assert ticks[-1].t_utc == T0 + timedelta(seconds=horizon)
    assert ticks[-1].position != ticks[0].position
    # An independent output cadence must end at the same physical state.
    dense = engine.predict(req.model_copy(update={"tick_s": 1})).result.alternatives[0].ticks[-1]
    assert ticks[-1].position.lat == pytest.approx(dense.position.lat, abs=1e-10)
    assert ticks[-1].position.lon == pytest.approx(dense.position.lon, abs=1e-10)


@pytest.mark.parametrize("horizon", [1, 11])
@pytest.mark.parametrize("forcing", [None, {"kind": "steady"}])
def test_contact_in_final_partial_interval_is_checked(horizon, forcing):
    dense = engine.predict(request(horizon_s=horizon, tick_s=1, forcing=forcing)).result.alternatives[0]
    p = dense.ticks[-2].position
    x, y = PLANE.to_local(p.lat, p.lon)
    lat, lon = PLANE.to_geo(x + refdata.ship("DDG-51-FIIA").loa_ft * 0.3048 / 2 + 1, y)
    response = engine.predict(request(horizon_s=horizon, forcing=forcing, others=[other(lat, lon)],
                                      hazards=dict(coastline=False, min_clearance_ft=0.1)))
    alt = response.result.alternatives[0]
    assert response.status == "RED" and alt.first_breach is not None
    assert alt.first_breach.t_s == horizon and alt.ticks[-1].t_s == horizon


@pytest.mark.parametrize("initial", [True, False])
def test_contact_at_zero_margin_counts_for_central_and_sampled_paths(initial):
    if initial:
        obstacle = other(37, -76, length=300, beam=60)
    else:
        prev = engine.predict(request(tick_s=1)).result.alternatives[0].ticks[-2].position
        x, y = PLANE.to_local(prev.lat, prev.lon)
        lat, lon = PLANE.to_geo(x + refdata.ship("DDG-51-FIIA").loa_ft * 0.3048 / 2 + 1, y)
        obstacle = other(lat, lon)
    v = request().vessel.model_dump() | {"uncertainty": {"position_sd_ft": 0.1, "heading_sd_deg": 0, "speed_sd_kt": 0}}
    response = engine.predict(request(vessel=v, others=[obstacle], uncertainty={"samples": 4, "seed": 1}))
    alt = response.result.alternatives[0]
    assert response.status == "RED" and alt.closest_approach.clearance_ft == 0
    assert alt.first_breach is not None and alt.first_breach.probability == 1
    assert alt.first_breach.t_s == (0 if initial else 11)


@pytest.mark.parametrize("forcing", [None, {"kind": "steady"}])
@pytest.mark.parametrize("issue,code,state", [
    ("quality", "ENVIRONMENT_POOR_QUALITY", "invalid"),
    ("interval", "ENVIRONMENT_OUTSIDE_VALID_INTERVAL", "invalid"),
    ("basis", "WIND_AVERAGING_UNSUPPORTED", "limited"),
])
def test_prediction_and_transit_honor_shared_environment_validity(forcing, issue, code, state):
    metadata = dict(basis="observation", source="offline-audit", quality="good", age_s=0, wind_averaging_s=60,
                    wind_reference_height_m=10, gust_duration_s=30)
    if issue == "quality":
        metadata["quality"] = "poor"
    elif issue == "interval":
        metadata["valid_to_utc"] = T0 - timedelta(seconds=1)
    else:
        metadata.update(wind_averaging_s=300, wind_reference_height_m=20)
    req = request(environment=CALM | {"source": "live", "metadata": metadata}, forcing=forcing)
    shared = {r.code for _, r in environment_findings(req.environment, False)} | {r.code for r in wind_basis(req.environment, False).reasons}
    assert code in shared
    response = engine.predict(req)
    assert response.validity.state == state
    assert shared <= {r.code for r in response.validity.reasons}
    if state == "invalid":
        assert response.status == "RED"
    treq = transit(req)
    assert simulator.validity_for(treq, simulator.run(treq)).state == state


def test_forcing_evidence_expiring_inside_horizon_invalidates_prediction():
    env = CALM | {"metadata": dict(basis="scenario", source="audit", quality="good", valid_to_utc=T0 + timedelta(seconds=5))}
    response = engine.predict(request(environment=env, forcing={"kind": "steady"}))
    assert response.status == "RED" and response.validity.state == "invalid"
    assert "ENVIRONMENT_OUTSIDE_VALID_INTERVAL" in {r.code for r in response.validity.reasons}


def timed_environment(*, offset_s=0, component=False, end_s=None):
    interval = dict(valid_from_utc=T0, valid_to_utc=T0 + timedelta(seconds=offset_s + 5 if end_s is None else end_s))
    metadata = dict(basis="observation", source="audit-observation", quality="good", issued_at_utc=T0,
                    wind_averaging_s=60, gust_duration_s=30, wind_reference_height_m=10)
    if component:
        metadata["components"] = [dict(component="wind", source="audit-wind", basis="observation", quality="good", **interval)]
    else:
        metadata.update(interval)
    return CALM | {"metadata": metadata}


@pytest.mark.parametrize("forcing", [None, {"kind": "steady"}])
@pytest.mark.parametrize("offset_s", [0, 10])
@pytest.mark.parametrize("component", [False, True])
def test_validity_interval_covers_actual_prediction_timeline(forcing, offset_s, component):
    """A held observation or forcing series cannot shift validity to its older snapshot clock."""
    req = request(environment=timed_environment(offset_s=offset_s, component=component),
                  as_of_utc=T0 + timedelta(seconds=offset_s), forcing=forcing)
    before = req.model_dump(mode="json")
    code = "ENVIRONMENT_COMPONENT_OUTSIDE_VALID_INTERVAL" if component else "ENVIRONMENT_OUTSIDE_VALID_INTERVAL"
    assert code not in {r.code for _, r in environment_findings(req.environment, False)}  # valid at observation time
    response = engine.predict(req)
    assert response.status == "RED" and response.validity.state == "invalid"
    assert code in {r.code for r in response.validity.reasons}
    assert response.result.alternatives[0].ticks[-1].t_utc == req.as_of_utc + timedelta(seconds=11)
    assert req.model_dump(mode="json") == before
    assert req.environment.valid_at_utc == T0 and req.environment.metadata.issued_at_utc == T0
    # The fixed transit service applies the same timeline checks independently of the prediction wrapper.
    treq = transit(req)
    validity = simulator.validity_for(treq, simulator.run(treq))
    assert validity.state == "invalid" and code in {r.code for r in validity.reasons}


@pytest.mark.parametrize("forcing", [None, {"kind": "steady"}])
@pytest.mark.parametrize("component", [False, True])
def test_validity_interval_includes_start_and_end_boundaries(forcing, component):
    req = request(environment=timed_environment(component=component, end_s=11), forcing=forcing)
    response = engine.predict(req)
    assert response.validity.state == "limited"
    assert not any("OUTSIDE_VALID_INTERVAL" in r.code for r in response.validity.reasons)


@pytest.mark.parametrize("forcing", [None, {"kind": "steady"}])
def test_observation_cannot_be_used_before_its_validity_interval(forcing):
    env = timed_environment(end_s=30)
    env["valid_at_utc"] = T0 + timedelta(seconds=10)
    env["metadata"]["valid_from_utc"] = T0 + timedelta(seconds=10)
    response = engine.predict(request(environment=env, forcing=forcing))
    assert response.validity.state == "invalid" and response.status == "RED"
    assert "ENVIRONMENT_OUTSIDE_VALID_INTERVAL" in {r.code for r in response.validity.reasons}


@pytest.mark.parametrize("forcing", [None, {"kind": "steady"}])
def test_default_as_of_is_the_same_clock_used_for_validity(monkeypatch, forcing):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return T0 + timedelta(seconds=10)

    monkeypatch.setattr(engine, "datetime", Clock)
    req = request(as_of_utc=None, environment=timed_environment(offset_s=10), forcing=forcing)
    response = engine.predict(req)
    assert response.result.as_of_utc == T0 + timedelta(seconds=10)
    assert response.validity.state == "invalid" and response.status == "RED"
    assert "ENVIRONMENT_OUTSIDE_VALID_INTERVAL" in {r.code for r in response.validity.reasons}
    assert req.as_of_utc is None and req.environment.valid_at_utc == T0


def test_transit_without_real_start_does_not_claim_interval_coverage():
    treq = transit(request(environment=timed_environment())).model_copy(update={"start_utc": None})
    result = simulator.run(treq)
    validity = simulator.validity_for(treq, result)
    assert validity.state == "limited"
    assert "ENVIRONMENT_RUN_TIME_UNSPECIFIED" in {r.code for r in validity.reasons}
    assert "ENVIRONMENT_OUTSIDE_VALID_INTERVAL" not in {r.code for r in validity.reasons}


@pytest.mark.parametrize("forcing", [None, {"kind": "steady"}, {"kind": "steady", "tide_amplitude_ft": 2, "tide_period_s": 20},
    {"kind": "replay", "samples": [{"t_s": 0, "water_level_mllw_ft": 0}, {"t_s": 11, "water_level_mllw_ft": 3}]}])
def test_calm_or_tide_only_forcing_does_not_claim_a_corridor(forcing):
    response = engine.predict(request(forcing=forcing, uncertainty={"samples": 4}))
    alt = response.result.alternatives[0]
    assert alt.corridor is None and all(t.position_sd_ft is None for t in alt.ticks)
    assert "UNCERTAINTY_UNAVAILABLE" in {r.code for r in response.validity.reasons}
    assert "UNCERTAINTY_ILLUSTRATIVE" not in {r.code for r in response.validity.reasons}
    assert response.manifest.numerical_settings["samples"] == 0


def test_nonzero_interior_forcing_is_a_spread_source_even_when_endpoints_are_calm():
    samples = [dict(t_s=t, wind_speed_kt=v, wind_gust_kt=v, wind_from_true_deg=0) for t, v in [(0, 0), (5, 20), (11, 0)]]
    response = engine.predict(request(forcing={"kind": "replay", "samples": samples}, uncertainty={"samples": 4}))
    assert response.result.alternatives[0].corridor is not None
    assert "UNCERTAINTY_ILLUSTRATIVE" in {r.code for r in response.validity.reasons}


def test_command_prediction_retains_partial_horizon():
    req = request(horizon_s=1)
    values = simulator.predict_constant_commands(transit(req).vessels[0], req.environment, 1, 0, 0.03, dt=0.2, sample_s=10)
    assert [t for t, _ in values] == [0, 1]
    assert values[-1][1].lon != values[0][1].lon


def test_forcing_truncation_retains_covered_time_shorter_than_a_tick():
    response = engine.predict(request(forcing={"kind": "replay", "on_uncovered": "invalidate", "samples": [
        {"t_s": 0, "water_level_mllw_ft": 0}, {"t_s": 1, "water_level_mllw_ft": 0}]}))
    assert response.result.forcing_basis.truncated
    assert response.result.forcing_basis.horizon_s == 1
    assert [t.t_s for t in response.result.alternatives[0].ticks] == [0, 1]
    assert "FORCING_HORIZON_TRUNCATED" in {r.code for r in response.validity.reasons}
