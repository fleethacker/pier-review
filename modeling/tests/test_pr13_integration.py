"""PR #13 (D1-D4 providers) -> modeling: composed forecast -> S2 replay forcing, offshore waves -> S4 surrogate request."""
from datetime import UTC, datetime, timedelta

import pytest

from mooring import refdata, scenarios
from mooring.berthing import simulator as sim
from mooring.berthing.forcing import ForcingSeries
from mooring.berthing.forcing_adapters import composed_forecast_to_forcing, composed_forecast_to_forcing_detail
from mooring.core.schemas import BerthingSimRequest, ComposedForecast, OffshoreWaveSeries, Scenario, ShipState
from mooring.data_simulation.wave_adapter import OFFSHORE_LABEL, offshore_waves_to_surrogate, offshore_waves_to_surrogate_request
from mooring.data_simulation.wave_surrogate import generate
from mooring.environment.composed_forecast import ForecastComposer
from mooring.environment.coops import Fetcher
from mooring.environment.forecast_contract_examples import compose_partial_response_example
from mooring.environment.wave_contract_examples import wave_compose_partial_response_example
from mooring.examples import EXAMPLES
from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship
from mooring.moored.forecast_resolver import resolve_forecast
from test_d2_composed_forecast import AS_OF, END, START, FixtureNWS, prediction_transport, request


@pytest.fixture(scope="module")
def complete():
    composer = ForecastComposer(nws=FixtureNWS(), clock=lambda: AS_OF,
                                coops_fetcher=Fetcher(prediction_transport(), clock=lambda: AS_OF, retries=0, min_interval_s=0))
    c = composer.compose(request())
    assert c.manifest.status == "complete"
    return c


@pytest.fixture
def partial():
    return ComposedForecast.model_validate(compose_partial_response_example())


def comp(c, name):
    return next(x for x in c.manifest.components if x.availability.component == name)


def test_mapping_correctness(complete):
    spec, rep = composed_forecast_to_forcing_detail(complete, START)
    assert spec.kind == "replay" and spec.samples[0].t_s == 0
    assert set(rep.channels) == {"wind_speed_kt", "wind_gust_kt", "wind_from_true_deg", "current_speed_kt",
                                 "current_set_true_deg", "water_level_mllw_ft"}
    cur = comp(complete, "current").points
    lvl = comp(complete, "water_level").points
    for s in spec.samples:
        at = START + timedelta(seconds=s.t_s)
        for p in cur:
            if p.valid_at_utc == at:
                assert s.current_speed_kt == pytest.approx(p.current_speed_kt)
        for p in lvl:
            if p.valid_at_utc == at:
                assert s.water_level_mllw_ft == pytest.approx(p.water_level_mllw_ft)
    # Wind interval value sits at the interval midpoint (documented sampling choice).
    w = comp(complete, "wind").points[0]
    mid = w.valid_from_utc + (w.valid_to_utc - w.valid_from_utc) / 2
    if START < mid < END:
        hit = [s for s in spec.samples if s.t_s == (mid - START).total_seconds()]
        assert hit and hit[0].wind_speed_kt == pytest.approx(w.wind_speed_kt)


def test_unavailable_component_is_missing_not_zero(partial):
    anchor = datetime(2026, 11, 6, 5, tzinfo=UTC)
    spec, rep = composed_forecast_to_forcing_detail(partial, anchor, max_gap_s=9*3600)
    assert "wind" in rep.skipped and rep.skipped["wind"].startswith("unavailable")
    assert all(s.wind_speed_kt is None and s.wind_gust_kt is None and s.wind_from_true_deg is None for s in spec.samples)
    assert all(s.current_speed_kt is not None and s.water_level_mllw_ft is not None for s in spec.samples)
    # Through the series: wind reported unavailable, not zero.
    series = ForcingSeries(spec, calm_env(), 5)
    env, _ = series.at(1.0)
    me = series.motion_environment(env, 1.0)
    assert me.wind.availability == "unavailable" and me.current.availability == "available"


def test_mock_not_used_unless_allowed(complete):
    mock = complete.model_copy(deep=True)
    w = comp(mock, "wind")
    w.availability = w.availability.model_copy(update={"state": "mock"})
    spec, rep = composed_forecast_to_forcing_detail(mock, START)
    assert "wind" in rep.skipped and "wind_speed_kt" not in rep.channels
    spec2, rep2 = composed_forecast_to_forcing_detail(mock, START, allow_mock=True)
    assert "wind_speed_kt" in rep2.channels and "wind:mock" in spec2.label


def test_all_unavailable_is_refused():
    c = ComposedForecast.model_validate(compose_partial_response_example())
    for item in c.manifest.components:
        item.availability = item.availability.model_copy(update={"state": "unavailable", "reason": "x"})
        item.points = []
    with pytest.raises(ValueError, match="no usable component"):
        composed_forecast_to_forcing(c, datetime(2026, 11, 6, 5, tzinfo=UTC))


def test_provenance_and_replay_label(complete):
    spec, rep = composed_forecast_to_forcing_detail(complete, START)
    assert complete.manifest.revision in spec.label and spec.label.startswith("REPLAY (not live)")
    assert len(spec.label) <= 200
    assert rep.manifest_revision == complete.manifest.revision
    assert all(v["content_sha256"] for v in rep.used.values()) and rep.used["wind"]["basis"] == "prediction"
    assert "live" not in spec.label.lower().replace("(not live)", "")
    # A different forecast revision is a different forcing revision (label is part of the spec hash).
    other = complete.model_copy(deep=True)
    other.manifest = other.manifest.model_copy(update={"revision": "sha256:" + "1" * 64})
    s2 = composed_forecast_to_forcing(other, START)
    assert ForcingSeries(spec, calm_env(), 5).revision != ForcingSeries(s2, calm_env(), 5).revision
    assert ForcingSeries(spec, calm_env(), 5).provenance().kind != "live"


def test_anchor_outside_coverage_refused(complete, partial):
    with pytest.raises(ValueError, match="outside forecast coverage"):
        composed_forecast_to_forcing(complete, START - timedelta(hours=1))
    with pytest.raises(ValueError, match="outside forecast coverage"):
        composed_forecast_to_forcing(complete, END)
    with pytest.raises(ValueError, match="timezone-aware"):
        composed_forecast_to_forcing(complete, datetime(2026, 11, 6, 5))
    with pytest.raises(ValueError, match="outside forecast coverage"):
        composed_forecast_to_forcing(partial, datetime(2026, 11, 5, 5, tzinfo=UTC))


def test_wind_gap_not_bridged(complete):
    g = complete.model_copy(deep=True)
    pts = comp(g, "wind").points
    pts[1] = pts[1].model_copy(update={"valid_from_utc": pts[1].valid_from_utc + timedelta(minutes=20)})
    with pytest.raises(ValueError, match="gap"):
        composed_forecast_to_forcing(g, START)


@pytest.fixture
def setup(monkeypatch):
    ship, berth, spec = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
    monkeypatch.setattr(refdata, "ship", lambda _: ship.model_copy(deep=True))
    monkeypatch.setattr(refdata, "berth", lambda _: berth.model_copy(deep=True))
    monkeypatch.setattr(refdata, "line", lambda _: spec.model_copy(deep=True))
    sc = Scenario.model_validate({**EXAMPLES["scenario"], "scenario_id": "test-pr13", "created_at_utc": "2026-01-01T00:00:00Z",
        "ship_class_id": ship.class_id, "berth_id": berth.berth_id, "side_to": "starboard", "config": breast_config(standoff=11)})
    env = calm_env()
    monkeypatch.setattr(scenarios, "get", lambda _: sc.model_copy(deep=True))
    monkeypatch.setattr(scenarios, "environment_for", lambda _: env.model_copy(deep=True))
    return sc, ShipState(x_ft=400, y_ft=41, heading_true_deg=90, v_kt=0.5)


def test_adapter_output_runs_in_simulation(setup, complete):
    sc, initial = setup
    spec, rep = composed_forecast_to_forcing_detail(complete, START)
    req = BerthingSimRequest(scenario_id=sc.scenario_id, initial_state=initial, duration_s=3, sample_interval_s=0.5, forcing=spec)
    r = sim.simulate_berthing(req, "pr13-run", "/api/v1")
    frames = sim.SERIES["pr13-run"].frames
    assert r.result.forcing_revision.startswith("frc-")
    assert all(f.forcing_revision == r.result.forcing_revision for f in frames)
    assert frames[0].environment.wind.availability == "available"
    assert frames[0].environment.wind.provenance.kind == "unknown"   # replay of supplied samples, never "live"
    # Forecast water level is carried to the frame at t=0.
    assert frames[0].environment.water.level_mllw_ft == pytest.approx(spec.samples[0].water_level_mllw_ft)


def test_partial_forecast_runs_with_wind_unavailable(setup, partial):
    sc, initial = setup
    spec = composed_forecast_to_forcing(partial, datetime(2026, 11, 6, 5, tzinfo=UTC), max_gap_s=9*3600)
    req = BerthingSimRequest(scenario_id=sc.scenario_id, initial_state=initial, duration_s=2, sample_interval_s=0.5, forcing=spec)
    sim.simulate_berthing(req, "pr13-partial", "/api/v1")
    f = sim.SERIES["pr13-partial"].frames[0]
    assert f.environment.wind.availability == "unavailable" and f.environment.current.availability == "available"


def test_p1_resolver_accepts_complete_forecast_snapshots(complete):
    r = resolve_forecast(complete.snapshots, as_of_utc=AS_OF, from_utc=START, to_utc=END,
                         revision=complete.manifest.revision, source="supplied")
    assert r.revision == complete.manifest.revision
    r.require_coverage(START, END)


def test_p1_resolver_cannot_take_partial_forecast(partial):
    """A partial forecast carries no snapshots by contract, so the P1 resolver has nothing to resolve (documented gap)."""
    assert partial.snapshots == []
    with pytest.raises(refdata.InvalidReference):
        resolve_forecast(partial.snapshots, as_of_utc=datetime(2026, 11, 5, 5, tzinfo=UTC),
                         from_utc=datetime(2026, 11, 6, 5, tzinfo=UTC), to_utc=datetime(2026, 11, 6, 13, tzinfo=UTC))


# ---- waves (D4 -> S4) ----
@pytest.fixture
def obs():
    d = wave_compose_partial_response_example()
    return next(OffshoreWaveSeries.model_validate(s) for s in d["manifest"]["offshore_series"] if s["role"] == "observation")


@pytest.fixture
def unavailable_series():
    d = wave_compose_partial_response_example()
    return next(OffshoreWaveSeries.model_validate(s) for s in d["manifest"]["offshore_series"] if s["role"] == "forecast")


AT = datetime(2026, 11, 5, 16, 30, tzinfo=UTC)


def test_wave_total_vs_partitions_never_both(obs):
    # Example total uses an AVERAGE period: refused as a peak period unless explicitly proxied.
    req, rep = offshore_waves_to_surrogate(obs, AT, 1)
    assert req.spectrum is None and "not a peak period" in rep.reasons[0]
    req, rep = offshore_waves_to_surrogate(obs, AT, 1, allow_period_proxy=True)
    assert [c.label for c in req.spectrum.components] == ["total_sea"] and req.spectrum.kind == "total"
    assert OFFSHORE_LABEL in req.spectrum.source and rep.notes
    req = offshore_waves_to_surrogate_request(obs, AT, 1, representation="partitions")
    assert [c.label for c in req.spectrum.components] == ["swell", "wind_sea"]
    assert req.spectrum.reported_total_hs_ft == pytest.approx(3.608924)   # checked, never added
    res = generate(req)
    assert res.state == "synthetic" and "not berth forcing" in res.label


def test_wave_spectrum_only_and_unavailable_are_not_zero(obs, unavailable_series):
    spec_only = obs.model_copy(update={"points": [obs.points[-1]]})
    req, rep = offshore_waves_to_surrogate(spec_only, AT, 1)
    assert req.spectrum is None and "NotImplemented" in rep.reasons[0] and not rep.available
    assert generate(req).state == "unavailable"
    req, rep = offshore_waves_to_surrogate(unavailable_series, AT, 1)
    assert req.spectrum is None and generate(req).state == "unavailable" and rep.reasons


def test_wave_no_lookahead_and_hold_limit(obs):
    req, rep = offshore_waves_to_surrogate(obs, datetime(2026, 11, 5, 15, 0, tzinfo=UTC), 1, allow_period_proxy=True)
    assert req.spectrum is None and "no look-ahead" in rep.reasons[0]
    req, rep = offshore_waves_to_surrogate(obs, AT + timedelta(hours=6), 1, allow_period_proxy=True)
    assert req.spectrum is None and "hold limit" in rep.reasons[0]
