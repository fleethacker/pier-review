"""D1 contract-first tests: partial status never weakens the complete snapshot."""

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from modeling_api.main import openapi_schema
from modeling_api.routers.env import env_availability
from mooring.core.schemas import EnvironmentAvailability, EnvironmentComponentAvailability


FIXTURE = (
    Path(__file__).parents[1]
    / "mooring/environment/fixtures/env_availability_partial.json"
)


def test_partial_availability_fixture_validates_and_keeps_missing_current_non_numeric():
    raw = json.loads(FIXTURE.read_text())
    status = EnvironmentAvailability.model_validate(raw)
    current = next(item for item in status.components if item.component == "current")
    assert status.complete_snapshot_available is False
    assert current.state == "unavailable" and current.reason
    assert not any(name.endswith(("_kt", "_ft")) for name in current.model_fields_set)


def test_availability_requires_all_five_unique_rows_and_consistent_complete_flag():
    raw = json.loads(FIXTURE.read_text())
    raw["components"][-1] = raw["components"][0]
    with pytest.raises(ValidationError, match="exactly one row"):
        EnvironmentAvailability.model_validate(raw)
    raw = json.loads(FIXTURE.read_text())
    raw["complete_snapshot_available"] = True
    with pytest.raises(ValidationError, match="must match"):
        EnvironmentAvailability.model_validate(raw)


def test_unavailable_needs_reason_and_available_needs_provenance():
    with pytest.raises(ValidationError, match="needs a reason"):
        EnvironmentComponentAvailability(component="wind", state="unavailable")
    with pytest.raises(ValidationError, match="needs source and basis"):
        EnvironmentComponentAvailability(component="wind", state="live")


def test_additive_route_is_published_while_complete_snapshot_route_is_unchanged():
    schema = openapi_schema()
    availability = schema["paths"]["/api/v1/env/availability"]["get"]
    assert availability["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/EnvironmentAvailability"
    )
    now = schema["paths"]["/api/v1/env/now"]["get"]
    assert now["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/EnvironmentSnapshot"
    )


def test_contract_first_route_fails_explicitly_until_acquisition_implementation():
    with pytest.raises(HTTPException) as exc:
        env_availability("NAVSTA-NORFOLK-P12-N")
    assert exc.value.status_code == 503
    assert "not enabled yet" in exc.value.detail


def test_recorded_real_selector_cannot_fall_through_to_synthetic_before_implementation():
    from mooring import environment, refdata
    from mooring.core.schemas import EnvScenarioCreate

    request = EnvScenarioCreate(
        name="recorded real",
        kind="replay",
        replay_start_utc="2026-01-01T00:00:00Z",
        replay_end_utc="2026-01-01T00:30:00Z",
        replay_source="recorded_real",
    )
    with pytest.raises(refdata.InvalidReference, match="not installed yet"):
        environment.create_scenario(request)
