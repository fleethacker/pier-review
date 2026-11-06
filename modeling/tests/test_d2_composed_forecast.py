"""D2 fixture-driven public/scenario forecast composition; no test reaches a network."""

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
import xarray as xr
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring import environment
from mooring.core.schemas import ComposedForecast, ComposedForecastRequest, EnvScenarioCreate
from mooring.core.schemas.forecast_planning import ForecastDockingRequest
from mooring.demo_cases import docking_cases
from mooring.environment import composed_forecast
from mooring.environment.composed_forecast import ForecastComposer
from mooring.environment.cbofs import M_TO_FT
from mooring.environment.cbofs_artifact import decode_artifact
from mooring.environment.coops import Fetcher
from mooring.environment.errors import ProviderError
from mooring.environment.forecast_hashing import component_content_sha256, manifest_revision
from mooring.environment.nws import WindForecast
from mooring.moored.forecast_planning import assess

AS_OF = datetime(2026, 11, 5, 5, tzinfo=UTC)
START = AS_OF + timedelta(hours=24)
END = START + timedelta(hours=4)
BERTH = "NAVSTA-NORFOLK-P12-N"


class FixtureNWS:
    def __init__(self, *, missing_gust_at=None, drop_at=None, failure=None):
        self.missing_gust_at = missing_gust_at
        self.drop_at = drop_at
        self.failure = failure

    def forecast(self, latitude, longitude, *, as_of, hours):
        if self.failure:
            raise ProviderError("unavailable", self.failure)
        rows, at = [], as_of
        while at < as_of + timedelta(hours=hours):
            if at == self.drop_at:
                at += timedelta(hours=1)
                continue
            rows.append(WindForecast(
                valid_from_utc=at,
                valid_to_utc=at + timedelta(hours=1),
                issued_at_utc=as_of - timedelta(hours=1),
                speed_kt=10,
                gust_kt=None if at == self.missing_gust_at else 15,
                from_true_deg=200,
                source="NWS AKQ/88,56 fixture",
                original={"wind_speed_km_h": 18.52, "wind_direction_deg": 200.0,
                          "wind_gust_km_h": "missing" if at == self.missing_gust_at else 27.78},
            ))
            at += timedelta(hours=1)
        return rows


def prediction_transport(*, depth_ft=21.0, fail=None):
    def transport(url, params, timeout):
        product = params["product"]
        if product == fail:
            raise TimeoutError(f"{product} down")
        begin = datetime.strptime(params["begin_date"], "%Y%m%d %H:%M").replace(tzinfo=UTC)
        end = datetime.strptime(params["end_date"], "%Y%m%d %H:%M").replace(tzinfo=UTC)
        times, at = [], begin
        while at <= end:
            times.append(at)
            at += timedelta(hours=1)
        if product == "currents_predictions":
            body = {"current_predictions": {"units": "feet, knots", "cp": [
                {"Speed": "0.30", "Bin": params["bin"], "Time": at.strftime("%Y-%m-%d %H:%M"),
                 "Direction": 10, "Depth": str(depth_ft)} for at in times
            ]}}
        elif product == "predictions":
            body = {"predictions": [
                {"t": at.strftime("%Y-%m-%d %H:%M"), "v": "1.50"} for at in times
            ]}
        else:
            raise AssertionError(f"unexpected product {product}")
        return 200, json.dumps(body)
    return transport


def request(**changes):
    values = {
        "berth_id": BERTH,
        "source": {"mode": "public"},
        "as_of_utc": AS_OF,
        "horizon_start_utc": START,
        "horizon_end_utc": END,
        "step_min": 60,
        "current_depth_ft": 21.0,
        "current_bin": "4",
    }
    return ComposedForecastRequest(**(values | changes))


def composer(*, nws=None, depth_ft=21.0, fail=None, clock=AS_OF):
    fetcher = Fetcher(
        prediction_transport(depth_ft=depth_ft, fail=fail),
        clock=lambda: clock,
        sleep=lambda _: None,
        retries=0,
        min_interval_s=0,
    )
    return ForecastComposer(nws=nws or FixtureNWS(), coops_fetcher=fetcher, clock=lambda: clock)


def cbofs_cache(tmp_path, *, latitude=36.957533, longitude=-76.331655):
    times = np.array([(START + timedelta(hours=index)).replace(tzinfo=None) for index in range(5)], dtype="datetime64[s]")
    dataset = xr.Dataset(
        data_vars={
            "Latitude": (("ny", "nx"), [[latitude]]),
            "Longitude": (("ny", "nx"), [[longitude]]),
            "mask": (("ny", "nx"), [[1]]),
            "zetatomllw": (("time", "ny", "nx"), np.full((5, 1, 1), 0.45)),
            "u_eastward": (("time", "Depth", "ny", "nx"), np.full((5, 1, 1, 1), 0.3)),
            "v_northward": (("time", "Depth", "ny", "nx"), np.full((5, 1, 1, 1), 0.4)),
        },
        coords={"Depth": [6.0], "time": times},
    )
    for name, units in {
        "Latitude": "degrees_north", "Longitude": "degrees_east", "Depth": "m",
        "zetatomllw": "meters", "u_eastward": "meters second-1", "v_northward": "meters second-1",
    }.items():
        dataset[name].attrs["units"] = units
    dataset.Depth.attrs["positive"] = "down"
    source = tmp_path / "cbofs.nc"
    dataset.to_netcdf(source, engine="netcdf4")
    payload = decode_artifact(
        str(source),
        latitude=latitude,
        longitude=longitude,
        depth_m=6.0,
        layer_id="6m",
        issued_at_utc=AS_OF - timedelta(hours=1),
        retrieved_at_utc=AS_OF,
        publication_evidence="fixture: publication manifest",
    )
    cache = tmp_path / "cbofs.json"
    cache.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return cache


@pytest.fixture(autouse=True)
def reset_composer():
    yield
    composed_forecast.configure(None)


def test_complete_public_forecast_covers_plus_24_hour_operation_and_is_content_addressed():
    response = composer().compose(request())
    assert response.manifest.status == "complete"
    assert response.snapshots[0].valid_at_utc == START
    assert response.snapshots[-1].valid_at_utc == END
    assert len(response.snapshots) == 5
    assert all(snapshot.source == "forecast" and snapshot.metadata.basis == "prediction"
               for snapshot in response.snapshots)
    assert all({item.component for item in snapshot.metadata.components} == {"wind", "current", "water_level"}
               for snapshot in response.snapshots)
    assert response.manifest.revision == manifest_revision(response.manifest)
    assert all(item.content_sha256 == component_content_sha256(item) for item in response.manifest.components)


def test_compose_http_endpoint_returns_the_same_frozen_revision():
    fixture_composer = composer()
    expected = fixture_composer.compose(request())
    composed_forecast.configure(fixture_composer)
    with TestClient(app) as client:
        result = client.post(
            "/api/v1/env/forecast/compose",
            json=request().model_dump(mode="json"),
        )
    assert result.status_code == 200, result.text
    assert result.json()["manifest"]["revision"] == expected.manifest.revision
    assert result.json() == expected.model_dump(mode="json")


def test_cached_revision_and_snapshot_hash_do_not_depend_on_parsing_latency():
    from mooring.moored.forecast_resolver import resolve_forecast

    class Clock:
        value = AS_OF - timedelta(minutes=1)

        def now(self):
            return self.value

    clock = Clock()

    class DelayedFetcher(Fetcher):
        latency_ms = 1

        def get(self, params):
            result = super().get(params)
            # Different parsing/dispatch delays must not revise a cached acquisition.
            clock.value += timedelta(milliseconds=self.latency_ms)
            self.latency_ms += 1
            return result

    fetcher = DelayedFetcher(prediction_transport(), clock=clock.now, sleep=lambda _: None,
                             retries=0, min_interval_s=0)
    service = ForecastComposer(nws=FixtureNWS(), coops_fetcher=fetcher, clock=clock.now)
    first = service.compose(request())
    second = service.compose(request())
    assert fetcher.calls == 2
    assert first == second
    first_binding = resolve_forecast(first.snapshots, as_of_utc=AS_OF, from_utc=START, to_utc=END)
    second_binding = resolve_forecast(second.snapshots, as_of_utc=AS_OF, from_utc=START, to_utc=END)
    assert first_binding.content_hash == second_binding.content_hash
    assert first_binding.binding_hash == second_binding.binding_hash


def test_unrecorded_retrieval_is_unavailable_without_backdating_it_from_cache_age():
    from mooring.environment.coops import Fetched

    class LegacyFetcher:
        def get(self, params):
            _, body = prediction_transport()("unused", params, 10)
            return Fetched(json.loads(body), False, 0)

    response = ForecastComposer(nws=FixtureNWS(), coops_fetcher=LegacyFetcher(), clock=lambda: AS_OF).compose(request())
    by_component = {item.availability.component: item for item in response.manifest.components}
    assert response.manifest.status == "partial"
    assert by_component["wind"].availability.state == "prediction"
    for name in ("current", "water_level"):
        assert "no recorded retrieval" in by_component[name].availability.reason


@pytest.mark.parametrize("product,body,component", [
    ("predictions", {"predictions": [None]}, "water_level"),
    ("predictions", {"predictions": "bad rows"}, "water_level"),
    ("currents_predictions", {"current_predictions": {"cp": [None]}}, "current"),
    ("currents_predictions", {"current_predictions": [1]}, "current"),
])
def test_malformed_coops_rows_only_disable_the_affected_component(product, body, component):
    normal = prediction_transport()

    def transport(url, params, timeout):
        return (200, json.dumps(body)) if params["product"] == product else normal(url, params, timeout)

    fetcher = Fetcher(transport, clock=lambda: AS_OF, sleep=lambda _: None, retries=0, min_interval_s=0)
    response = ForecastComposer(nws=FixtureNWS(), coops_fetcher=fetcher, clock=lambda: AS_OF).compose(request())
    by_component = {item.availability.component: item for item in response.manifest.components}
    assert response.manifest.status == "partial" and response.snapshots == []
    assert by_component[component].availability.state == "unavailable"
    assert "malformed" in by_component[component].availability.reason
    assert all(item.availability.state == "prediction" for name, item in by_component.items() if name != component)


def test_plus_24_forecast_runs_through_complete_docking_and_holding_window():
    forecast = composer().compose(request()).snapshots
    base = docking_cases()[0].analysis_request
    planning = ForecastDockingRequest(
        ship_class_id=base.ship_class_id,
        berth_id=base.berth_id,
        config=base.config,
        as_of_utc=AS_OF,
        arrival_from_utc=START,
        arrival_to_utc=START,
        operation_hours=2,
        holding_hours=2,
        forecast=forecast,
    )
    result = assess(planning)
    assert result.result.windows[0].holding_end_utc == END
    assert result.result.windows[0].outcome != "unavailable"
    assert result.result.evaluations == 5


def test_nws_outage_returns_coops_only_partial_without_mock_or_numeric_wind():
    response = composer(nws=FixtureNWS(failure="fixture outage")).compose(request())
    by_component = {item.availability.component: item for item in response.manifest.components}
    assert response.manifest.status == "partial" and response.snapshots == []
    assert by_component["wind"].availability.state == "unavailable"
    assert by_component["wind"].points == []
    assert by_component["current"].availability.state == "prediction"
    assert by_component["water_level"].availability.state == "prediction"


def test_nearby_current_depth_is_unavailable_and_never_substituted():
    response = composer(depth_ft=20.6).compose(request())
    current = next(item for item in response.manifest.components if item.availability.component == "current")
    assert response.manifest.status == "partial" and response.snapshots == []
    assert current.availability.state == "unavailable"
    assert "no nearby layer" in current.availability.reason


def test_missing_nws_gust_stays_explicit_and_breaks_complete_snapshot_coverage():
    response = composer(nws=FixtureNWS(missing_gust_at=START + timedelta(hours=1))).compose(request())
    wind = next(item for item in response.manifest.components if item.availability.component == "wind")
    assert any(point.wind_gust_kt is None for point in wind.points)
    assert response.manifest.status == "partial"
    assert all(snapshot.valid_at_utc != START + timedelta(hours=1) for snapshot in response.snapshots)


def test_nws_interval_gap_remains_partial_even_when_snapshot_gap_is_under_requested_maximum():
    response = composer(nws=FixtureNWS(drop_at=START + timedelta(hours=1))).compose(request(step_min=180))
    assert response.manifest.status == "partial"
    boundary = next(snapshot for snapshot in response.snapshots if snapshot.valid_at_utc == START + timedelta(hours=1))
    wind = next(item for item in boundary.metadata.components if item.component == "wind")
    assert wind.valid_to_utc == START + timedelta(hours=1)


def test_prediction_retrieved_after_as_of_is_unavailable_not_backdated():
    response = composer(clock=AS_OF + timedelta(minutes=1)).compose(request())
    by_component = {item.availability.component: item for item in response.manifest.components}
    assert by_component["current"].availability.state == "unavailable"
    assert by_component["water_level"].availability.state == "unavailable"
    assert "after as_of_utc" in by_component["current"].availability.reason
    for name in ("current", "water_level"):
        assert by_component[name].availability.retrieved_at_utc == AS_OF + timedelta(minutes=1)
        assert by_component[name].points == []


def test_explicit_retrieval_cutoff_retry_reuses_acquisition_with_an_advancing_clock():
    clock = [AS_OF]
    calls = []
    transport = prediction_transport()

    class FixedNWS(FixtureNWS):
        def forecast(self, latitude, longitude, *, as_of, hours):
            # One provider publication has fixed periods; changing the caller's
            # cutoff must not shift the fixture's forecast issuance or grid.
            return super().forecast(latitude, longitude, as_of=AS_OF, hours=hours + 1)

    def delayed(url, params, timeout):
        calls.append(params["product"])
        clock[0] += timedelta(milliseconds=20)
        return transport(url, params, timeout)

    fetcher = Fetcher(delayed, clock=lambda: clock[0], sleep=lambda _: None, retries=0, min_interval_s=0)
    fixture = ForecastComposer(nws=FixedNWS(), coops_fetcher=fetcher, clock=lambda: clock[0])
    first = fixture.compose(request())
    assert first.manifest.status == "partial" and first.snapshots == []
    retrievals = [item.availability.retrieved_at_utc for item in first.manifest.components
                  if item.availability.retrieved_at_utc is not None]
    assert retrievals == [AS_OF + timedelta(milliseconds=20), AS_OF + timedelta(milliseconds=40)]
    # The caller explicitly adopts the actual acquisition cutoff. A request made
    # with the original cutoff must continue to reject those same cached values.
    clock[0] += timedelta(seconds=1)
    assert fixture.compose(request()).manifest.status == "partial"
    retry = fixture.compose(request(as_of_utc=max(retrievals)))
    assert retry.manifest.status == "complete" and len(calls) == 2
    again = fixture.compose(request(as_of_utc=max(retrievals)))
    assert again.model_dump(mode="json") == retry.model_dump(mode="json")
    assert len(calls) == 2


def test_exact_applicable_cbofs_cache_is_used_without_native_access_in_api_worker(tmp_path):
    cache = cbofs_cache(tmp_path)
    base = composer(fail="currents_predictions")
    base.cbofs_artifact_path = cache
    response = base.compose(request(current_depth_ft=6.0 * M_TO_FT, current_bin="6m"))
    by_component = {item.availability.component: item for item in response.manifest.components}
    assert response.manifest.status == "complete"
    assert by_component["current"].availability.source.startswith("NOAA CBOFS regular grid")
    assert by_component["current"].availability.current_depth_ft == pytest.approx(6.0 * M_TO_FT)
    assert by_component["water_level"].availability.vertical_datum == "MLLW"


def test_cbofs_cache_for_another_coordinate_is_not_silently_applied(tmp_path):
    cache = cbofs_cache(tmp_path, latitude=36.95)
    base = composer()
    base.cbofs_artifact_path = cache
    response = base.compose(request(current_depth_ft=6.0 * M_TO_FT, current_bin="6m"))
    current = next(item for item in response.manifest.components if item.availability.component == "current")
    assert current.availability.state == "unavailable"
    assert any("target does not match" in note for note in current.availability.limitations)


def test_explicit_ramp_scenario_is_sampled_over_time_not_repeated_from_now():
    scenario = environment.create_scenario(EnvScenarioCreate(
        name="D2 ramp",
        kind="ramp",
        wind_speed_kt=5,
        wind_gust_kt=7,
        wind_from_true_deg=180,
        current_speed_kt=0.2,
        current_set_true_deg=5,
        water_level_mllw_ft=1,
        ramp_to_wind_kt=25,
        ramp_minutes=30,
    ))
    scenario_request = request(
        source={"mode": "scenario", "env_scenario_id": scenario.env_scenario_id},
        as_of_utc=scenario.created_at_utc,
        horizon_start_utc=scenario.created_at_utc,
        horizon_end_utc=scenario.created_at_utc + timedelta(minutes=30),
        step_min=15,
    )
    response = composer().compose(scenario_request)
    assert response.manifest.status == "complete"
    assert [snapshot.wind_speed_kt for snapshot in response.snapshots] == pytest.approx([5, 15, 25])
    assert all(snapshot.source == "scenario" and snapshot.metadata.basis == "scenario"
               for snapshot in response.snapshots)


def test_recorded_observation_scenario_cannot_be_promoted_to_forecast():
    scenario = environment.create_scenario(EnvScenarioCreate(
        name="recorded observations",
        kind="replay",
        replay_start_utc="2026-01-01T00:00:00Z",
        replay_end_utc="2026-01-01T00:30:00Z",
        replay_source="recorded_real",
    ))
    with pytest.raises(ProviderError, match="cannot be promoted"):
        composer().compose(request(source={"mode": "scenario", "env_scenario_id": scenario.env_scenario_id}))


@pytest.mark.parametrize("replay_source", ["synthetic", "recorded_fixture"])
def test_replay_composition_retimes_training_and_preserves_original_provenance(replay_source):
    archive_start = datetime(2026, 3, 1, 12, tzinfo=UTC)
    scenario = environment.create_scenario(EnvScenarioCreate(
        name="finite training replay", kind="replay", replay_source=replay_source,
        replay_start_utc=archive_start, replay_end_utc=archive_start + timedelta(hours=1),
    ))
    req = request(
        source={"mode": "scenario", "env_scenario_id": scenario.env_scenario_id},
        as_of_utc=scenario.created_at_utc, horizon_start_utc=scenario.created_at_utc,
        horizon_end_utc=scenario.created_at_utc + timedelta(hours=1), step_min=15,
    )
    composed_forecast.configure(composer())
    client = TestClient(app)
    response = client.post("/api/v1/env/forecast/compose", json=req.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    result = ComposedForecast.model_validate(response.json())
    assert result.manifest.status == "complete"
    assert len(result.snapshots) == 5
    for index, item in enumerate(result.snapshots):
        assert item.valid_at_utc == scenario.created_at_utc + timedelta(minutes=15 * index)
        assert item.source == "scenario" and item.metadata.basis == "scenario"
        original = json.loads(item.metadata.original["original_snapshot_json"])
        archive_time = archive_start + timedelta(minutes=15 * index)
        assert original["valid_at_utc"] == archive_time.isoformat().replace("+00:00", "Z")
        assert item.metadata.original["replay_source"] == replay_source
        if original.get("metadata") and original["metadata"]["valid_to_utc"]:
            old_end = datetime.fromisoformat(original["metadata"]["valid_to_utc"].replace("Z", "+00:00"))
            assert item.metadata.valid_to_utc <= old_end + (scenario.created_at_utc - archive_start)
    again = client.post("/api/v1/env/forecast/compose", json=req.model_dump(mode="json"))
    assert again.json() == response.json()
    canonical = client.post("/api/v1/mooring/forecast/resolve", json={
        "berth_id": BERTH, "as_of_utc": scenario.created_at_utc.isoformat(),
        "from_utc": req.horizon_start_utc.isoformat(), "to_utc": req.horizon_end_utc.isoformat(),
        "step_min": 15, "max_gap_min": 15,
        "forecast_binding": {"source": "scenario", "env_scenario_id": scenario.env_scenario_id},
    })
    assert canonical.status_code == 200, canonical.text
    canonical_samples = canonical.json()["result"]["series"]
    assert [item["valid_at_utc"] for item in canonical_samples] == [item["valid_at_utc"] for item in response.json()["snapshots"]]
    assert [item["metadata"]["original"]["original_snapshot_hash"] for item in canonical_samples] == [
        item.metadata.original["original_snapshot_hash"] for item in result.snapshots]
    exhausted = req.model_copy(update={"horizon_end_utc": req.horizon_end_utc + timedelta(minutes=15)})
    end = client.post("/api/v1/env/forecast/compose", json=exhausted.model_dump(mode="json"))
    assert end.status_code == 200, end.text
    assert end.json()["manifest"]["status"] == "unavailable" and end.json()["snapshots"] == []
    assert "exhausted" in end.json()["manifest"]["components"][0]["availability"]["reason"]


def test_composer_keeps_its_full_bounded_scenario_grid():
    scenario = environment.create_scenario(EnvScenarioCreate(name="full grid", kind="steady"))
    result = composer().compose(request(
        source={"mode": "scenario", "env_scenario_id": scenario.env_scenario_id},
        as_of_utc=scenario.created_at_utc, horizon_start_utc=scenario.created_at_utc,
        horizon_end_utc=scenario.created_at_utc + timedelta(hours=120), step_min=6,
    ))
    assert result.manifest.status == "complete" and len(result.snapshots) == 1201


def test_negative_ramp_target_is_rejected_before_storage_and_zero_is_sampleable():
    client = TestClient(app)
    payload = {"name": "ramp", "kind": "ramp", "wind_speed_kt": 10,
               "ramp_to_wind_kt": -1, "ramp_minutes": 30}
    rejected = client.post("/api/v1/env/scenarios", json=payload)
    assert rejected.status_code == 422
    assert any(error["loc"][-1] == "ramp_to_wind_kt" for error in rejected.json()["detail"])
    payload["ramp_to_wind_kt"] = 0
    accepted = client.post("/api/v1/env/scenarios", json=payload)
    assert accepted.status_code == 201
    scenario = environment.get_scenario(accepted.json()["env_scenario_id"])
    snapshots = [environment.scenario_snapshot(scenario.env_scenario_id, scenario.created_at_utc + timedelta(minutes=minutes))
                 for minutes in (0, 30, 60)]
    assert [item.wind_speed_kt for item in snapshots] == [10, 0, 0]
