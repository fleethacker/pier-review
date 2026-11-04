"""The LLM schema and its validator stay aligned with the modeling contract."""

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from mooring_agents.physics.tools import TOOLS, input_errors, input_schema, tool_definitions

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
EXAMPLES = {
    "compute_loads": "loads_environmental",
    "analyze_mooring": "mooring_analyze",
    "limit_envelope": "mooring_envelope",
    "risk_exceedance": "risk_exceedance",
    "recommend_config": "mooring_recommend",
    "plan_tugs": "tugs_berthing_plan",
    "hold_tugs": "tugs_hold_plan",
    "berthing_windows": "windows_berthing",
    "generate_sequence": "mooring_sequence",
}


def example(name):
    return json.loads((CONTRACT / "examples" / "modeling" / f"{EXAMPLES[name]}.json").read_text())


@pytest.fixture(scope="module")
def contract():
    return yaml.safe_load((CONTRACT / "modeling.openapi.yaml").read_text())


@pytest.mark.parametrize("spec", TOOLS, ids=lambda spec: spec.name)
def test_catalog_matches_contract(spec, contract):
    operation = contract["paths"][f"/api/v1{spec.path}"][spec.method.lower()]
    if spec.method == "POST":
        assert operation["requestBody"]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{spec.request_schema}"
        }


def test_definitions_cover_every_tool_with_standalone_schemas():
    definitions = tool_definitions()
    assert [item["name"] for item in definitions] == [spec.name for spec in TOOLS]
    for spec, definition in zip(TOOLS, definitions, strict=True):
        assert set(definition) == {"name", "description", "input_schema"}
        assert definition["description"] == spec.description
        assert '"$ref"' not in json.dumps(definition["input_schema"])
        Draft202012Validator.check_schema(definition["input_schema"])


@pytest.mark.parametrize("spec", [spec for spec in TOOLS if spec.method == "POST"], ids=lambda spec: spec.name)
def test_post_schemas_validate_matching_contract_example(spec):
    request = example(spec.name)
    Draft202012Validator(input_schema(spec.name), format_checker=FormatChecker()).validate(request)
    assert input_errors(spec.name, request) == []


@pytest.mark.parametrize(("name", "payload"), [
    ("get_scenario", {"scenario_id": "scn_example"}),
    ("get_environment", {"berth_id": "NAVSTA-NORFOLK-P12-N", "heading_true_deg": 105,
                         "env_scenario_id": None}),
    ("get_forecast", {"berth_id": "NAVSTA-NORFOLK-P12-N", "hours": 48, "step_min": 30}),
    ("get_ship", {"class_id": "DDG-51-FIIA"}),
    ("get_berth", {"berth_id": "NAVSTA-NORFOLK-P12-N"}),
])
def test_get_schemas_validate_path_and_query_inputs(name, payload):
    assert input_errors(name, payload) == []


@pytest.mark.parametrize(("payload", "path"), [
    ({}, "$.berth_id"),
    ({"berth_id": "berth", "hours": 121}, "$.hours"),
    ({"berth_id": "berth", "step_min": 5}, "$.step_min"),
    ({"berth_id": "berth", "hours": "24"}, "$.hours"),
    ({"berth_id": "berth", "hours": True}, "$.hours"),
    ({"berth_id": "berth", "extra": "ignored by HTTP"}, "$"),
])
def test_get_validation_enforces_parameters_without_coercing(payload, path):
    errors = input_errors("get_forecast", payload)
    assert errors and errors[0]["path"] == path and errors[0]["message"]


def test_validation_reports_nested_field_paths_and_datetime_formats():
    request = example("analyze_mooring")
    request["config"]["lines"][0]["parts"] = 4
    request["environment"]["valid_at_utc"] = "yesterday"
    errors = input_errors("analyze_mooring", request)
    assert [item["path"] for item in errors] == [
        "$.config.lines[0].parts", "$.environment.valid_at_utc"
    ]
    assert input_errors("analyze_mooring", request) == errors


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), object()])
def test_validation_rejects_non_json_values_with_field_paths(value):
    errors = input_errors("get_environment", {"berth_id": "berth", "heading_true_deg": value})
    assert len(errors) == 1 and errors[0]["path"] == "$.heading_true_deg"


def test_validation_rejects_circular_input():
    request = {"berth_id": "berth"}
    request["loop"] = request
    assert input_errors("get_environment", request)[0]["path"] == "$.loop"


def test_schema_adaptation_cannot_mutate_the_validator():
    schema = input_schema("get_forecast")
    schema["properties"]["hours"]["maximum"] = 1000
    assert input_errors("get_forecast", {"berth_id": "berth", "hours": 1000})
    definitions = tool_definitions()
    definitions[0]["input_schema"].clear()
    assert input_errors(definitions[0]["name"], {})
