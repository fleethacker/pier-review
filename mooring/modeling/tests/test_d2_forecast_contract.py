"""D2 contract-first coverage for frozen complete and partial forecast responses."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from modeling_api.main import openapi_schema
from modeling_api.routers.env import env_forecast_compose
from mooring.core.schemas import (
    ComposedForecast,
    ComposedForecastManifest,
    ComposedForecastRequest,
    ForecastComponentSeries,
    ForecastSourceSelection,
    WindForecastPoint,
)
from mooring.environment.forecast_contract_examples import (
    compose_partial_response_example,
    compose_request_example,
)
from mooring.environment.forecast_hashing import component_content_sha256, manifest_revision

EXPORTED = Path(__file__).parents[2] / "contract/examples/modeling/env_forecast_compose_partial.json"


def test_partial_fallback_keeps_wind_unavailable_and_predictions_component_scoped():
    response = ComposedForecast.model_validate(compose_partial_response_example())
    assert response.manifest.status == "partial" and response.snapshots == []
    by_component = {item.availability.component: item for item in response.manifest.components}
    assert by_component["wind"].availability.state == "unavailable"
    assert by_component["wind"].points == [] and by_component["wind"].content_sha256 is None
    assert by_component["current"].availability.state == "prediction"
    assert by_component["water_level"].availability.vertical_datum == "MLLW"
    assert all(item.availability.basis == "prediction" for name, item in by_component.items() if name != "wind")


def test_example_revision_binds_the_request_component_content_and_policy():
    raw = compose_partial_response_example()
    manifest = ComposedForecastManifest.model_validate(raw["manifest"])
    assert manifest.revision == manifest_revision(manifest)
    changed = manifest.model_copy(update={"request": manifest.request.model_copy(update={"current_depth_ft": 20.0})})
    assert manifest.revision != manifest_revision(changed)
    for component in manifest.components:
        if component.availability.state != "unavailable":
            assert component.content_sha256 == component_content_sha256(component)


def test_exported_partial_response_is_generated_from_the_same_validated_example():
    assert json.loads(EXPORTED.read_text()) == compose_partial_response_example()
    ComposedForecast.model_validate_json(EXPORTED.read_text())


def test_source_and_horizon_are_explicit_and_bounded():
    request = ComposedForecastRequest.model_validate(compose_request_example())
    assert request.source.mode == "public" and request.current_depth_ft == 21.0 and request.current_bin == "4"
    with pytest.raises(ValidationError, match="needs env_scenario_id"):
        ForecastSourceSelection(mode="scenario")
    with pytest.raises(ValidationError, match="cannot include"):
        ForecastSourceSelection(mode="public", env_scenario_id="envsc-1")
    bad = compose_request_example()
    bad["horizon_end_utc"] = "2026-11-10T06:00:00Z"
    with pytest.raises(ValidationError, match="120 hours"):
        ComposedForecastRequest.model_validate(bad)


def test_component_series_rejects_values_on_unavailable_or_cross_labeled_rows():
    raw = compose_partial_response_example()["manifest"]["components"][1]
    raw["availability"]["state"] = "unavailable"
    raw["availability"]["reason"] = "down"
    with pytest.raises(ValidationError, match="cannot carry points"):
        ForecastComponentSeries.model_validate(raw)

    raw = compose_partial_response_example()["manifest"]["components"][1]
    raw["points"][0] = {
        "component": "water_level",
        "valid_at_utc": "2026-11-06T05:00:00Z",
        "water_level_mllw_ft": 1.5,
    }
    with pytest.raises(ValidationError, match="must match"):
        ForecastComponentSeries.model_validate(raw)


def test_manifest_rejects_nearby_current_depth_or_bin_substitution():
    raw = compose_partial_response_example()["manifest"]
    raw["components"][1]["availability"]["current_depth_ft"] = 20.6
    with pytest.raises(ValidationError, match="does not match"):
        ComposedForecastManifest.model_validate(raw)


def test_missing_gust_stays_null_and_cannot_be_called_a_complete_forecast():
    point = WindForecastPoint(
        valid_from_utc=datetime(2026, 11, 6, 5, tzinfo=UTC),
        valid_to_utc=datetime(2026, 11, 6, 6, tzinfo=UTC),
        wind_speed_kt=10,
        wind_gust_kt=None,
        wind_from_true_deg=90,
    )
    assert point.model_dump()["wind_gust_kt"] is None

    raw = compose_partial_response_example()["manifest"]
    raw["status"] = "complete"
    raw["components"][0] = {
        "availability": {
            "component": "wind", "state": "prediction", "source": "NWS AKQ/88,56",
            "basis": "prediction", "issued_at_utc": "2026-11-04T23:38:07Z",
        },
        "content_sha256": "0" * 64,
        "points": [point.model_dump(mode="json")],
    }
    with pytest.raises(ValidationError, match="missing wind gusts"):
        ComposedForecastManifest.model_validate(raw)


def test_contract_publishes_additive_compose_route_and_leaves_legacy_get_unchanged():
    paths = openapi_schema()["paths"]
    compose = paths["/api/v1/env/forecast/compose"]["post"]
    assert compose["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ComposedForecastRequest"
    )
    assert compose["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ComposedForecast"
    )
    legacy = paths["/api/v1/env/forecast"]["get"]
    assert legacy["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ForecastSeries"
    )


def test_implementation_route_dispatches_the_bound_request_without_rewriting_it(monkeypatch):
    request = ComposedForecastRequest.model_validate(compose_request_example())
    expected = ComposedForecast.model_validate(compose_partial_response_example())
    monkeypatch.setattr("modeling_api.routers.env.impl.compose_forecast", lambda value: expected if value == request else None)
    assert env_forecast_compose(request) == expected
