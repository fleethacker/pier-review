"""Tool catalog: each tool wraps exactly one modeling endpoint.

This is the only list of physics capabilities any agent may use. The Planner's LLM tool definitions are built
from it (input schemas come from contract/modeling.openapi.yaml). Served at GET /api/v1/tools.
"""

from copy import deepcopy
from functools import cache
from math import isfinite
from pathlib import Path
from typing import Any, Literal

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field

from mooring.core.schemas import Model


class ToolSpec(Model):
    name: str
    description: str
    method: Literal["GET", "POST"]
    path: str = Field(description="Modeling path under /api/v1. {placeholders} are filled from the input.")
    request_schema: str | None = Field(description="Component name in contract/modeling.openapi.yaml.")
    async_job: bool = Field(default=False, description="True when the endpoint returns a job the gateway polls.")


TOOLS: list[ToolSpec] = [
    ToolSpec(name="get_environment_scenario", description="Read the declared steady, ramp or replay source without inventing future samples.",
             method="GET", path="/env/scenarios/{env_scenario_id}", request_schema=None),
    ToolSpec(name="save_berth", description="Register explicitly human-confirmed berth geometry, preserving estimated provenance.",
             method="POST", path="/berths", request_schema="Berth"),
    ToolSpec(name="draft_berth", description="Build unsaved draft geometry using catalog data and optional image anchors.",
             method="POST", path="/berth-drafts", request_schema="BerthDraftRequest"),
    ToolSpec(name="get_scenario", description="Load the saved scenario: ship, berth, side, environment source, config.",
             method="GET", path="/scenarios/{scenario_id}", request_schema=None),
    ToolSpec(name="get_environment", description="Current wind, current and water level at the berth.",
             method="GET", path="/env/now", request_schema=None),
    ToolSpec(name="get_forecast", description="Forecast wind, current and water level at the berth.",
             method="GET", path="/env/forecast", request_schema=None),
    ToolSpec(name="get_ship", description="Ship class particulars, fittings and push points.",
             method="GET", path="/ships/{class_id}", request_schema=None),
    ToolSpec(name="get_berth", description="Berth geometry, pier fittings with capacities, fenders, depths.",
             method="GET", path="/berths/{berth_id}", request_schema=None),
    ToolSpec(name="compute_loads", description="Wind and current forces on the ship.",
             method="POST", path="/loads/environmental", request_schema="LoadsRequest"),
    ToolSpec(name="analyze_mooring", description="Line, fitting and fender loads plus NSTM 582 findings.",
             method="POST", path="/mooring/analyze", request_schema="AnalyzeRequest"),
    ToolSpec(name="limit_envelope", description="Wind speed that first overloads the plan, per direction.",
             method="POST", path="/mooring/envelope", request_schema="LimitEnvelopeRequest"),
    ToolSpec(name="risk_exceedance", description="Probability that gusts push any element past its limit.",
             method="POST", path="/risk/exceedance", request_schema="ExceedanceRequest", async_job=True),
    ToolSpec(name="recommend_config", description="Candidate line configurations scored at the MST design condition.",
             method="POST", path="/mooring/recommend", request_schema="RecommendRequest", async_job=True),
    ToolSpec(name="plan_tugs", description="Tug force, bollard pull and horsepower to land and hold the ship.",
             method="POST", path="/tugs/berthing-plan", request_schema="BerthingTugRequest"),
    ToolSpec(name="hold_tugs", description="Tugs needed to relieve overloaded lines on a moored ship.",
             method="POST", path="/tugs/hold-plan", request_schema="HoldTugRequest"),
    ToolSpec(name="berthing_windows", description="Times with low current and gusts for berthing.",
             method="POST", path="/windows/berthing", request_schema="BerthingWindowRequest"),
    ToolSpec(name="generate_sequence", description="Ordered line-handling steps for a configuration.",
             method="POST", path="/mooring/sequence", request_schema="SequenceRequest"),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}


@cache
def _contract() -> dict[str, Any]:
    """Read the checked-in contract, or the same file bundled in an installed wheel."""
    package = Path(__file__).resolve().parent
    bundled = package / "modeling.openapi.yaml"
    path = bundled if bundled.is_file() else package.parents[2] / "contract" / "modeling.openapi.yaml"
    with path.open(encoding="utf-8") as source:
        return yaml.safe_load(source)


def _resolve(value: Any, document: dict[str, Any], resolving: tuple[str, ...] = ()) -> Any:
    """Inline local JSON pointers so tool definitions need no external schema registry."""
    if isinstance(value, list):
        return [_resolve(item, document, resolving) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" not in value:
        return {key: _resolve(item, document, resolving) for key, item in value.items()}

    reference = value["$ref"]
    if not reference.startswith("#/"):
        raise ValueError(f"Tool schemas require local contract references: {reference}")
    if reference in resolving:
        raise ValueError(f"Cannot inline recursive tool schema: {reference}")
    target: Any = document
    for token in reference[2:].split("/"):
        target = target[token.replace("~1", "/").replace("~0", "~")]
    resolved = _resolve(target, document, (*resolving, reference))
    siblings = _resolve({key: item for key, item in value.items() if key != "$ref"}, document, resolving)
    # In JSON Schema, $ref siblings add constraints rather than overriding the target.
    return {"allOf": [resolved, siblings]} if siblings else resolved


@cache
def _input_schema(name: str) -> dict[str, Any]:
    spec = TOOLS_BY_NAME[name]
    document = _contract()
    path = document["paths"][f"/api/v1{spec.path}"]
    operation = path[spec.method.lower()]
    if spec.method == "POST":
        schema = _resolve({"$ref": f"#/components/schemas/{spec.request_schema}"}, document)
    else:
        # Operation parameters override parameters inherited from the path item.
        parameters = {}
        for parameter in [*path.get("parameters", []), *operation.get("parameters", [])]:
            parameter = _resolve(parameter, document)
            if parameter["in"] in ("path", "query"):
                parameters[parameter["in"], parameter["name"]] = parameter
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        required = []
        for parameter in parameters.values():
            field = parameter["schema"]
            if "description" in parameter:
                field.setdefault("description", parameter["description"])
            schema["properties"][parameter["name"]] = field
            if parameter.get("required") or parameter["in"] == "path":
                required.append(parameter["name"])
        if required:
            schema["required"] = required
    Draft202012Validator.check_schema(schema)
    return schema


def input_schema(name: str) -> dict[str, Any]:
    """Return a standalone input schema for a tool, safe for callers to adapt."""
    return deepcopy(_input_schema(name))


def tool_definitions() -> list[dict[str, Any]]:
    """Provider-neutral tools; provider adapters translate these into their own wire format."""
    return [
        {"name": spec.name, "description": spec.description, "input_schema": input_schema(spec.name)}
        for spec in TOOLS
    ]


@cache
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_input_schema(name), format_checker=FormatChecker())


def _field_path(parts: list[str | int]) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        elif part.isidentifier():
            path += f".{part}"
        else:
            path += f"[{part!r}]"
    return path


def _json_errors(value: Any, parts: list[str | int], parents: frozenset[int] = frozenset()) -> list[dict[str, str]]:
    """JSON Schema assumes JSON data; reject Python-only values at the same boundary."""
    message = None
    if isinstance(value, (dict, list)):
        if id(value) in parents:
            message = "Input must be JSON; circular references are not allowed."
        elif isinstance(value, dict) and any(not isinstance(key, str) for key in value):
            message = "JSON object keys must be strings."
        else:
            parents = parents | {id(value)}
            items = value.items() if isinstance(value, dict) else enumerate(value)
            return [issue for key, item in items for issue in _json_errors(item, [*parts, key], parents)]
    elif isinstance(value, float) and not isfinite(value):
        message = "Expected a finite JSON number."
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        message = f"Expected a JSON value, got {type(value).__name__}."
    return [{"path": _field_path(parts), "message": message}] if message else []


def input_errors(name: str, value: Any) -> list[dict[str, str]]:
    """Return deterministic field paths and correction messages without coercing input."""
    issues = _json_errors(value, [])
    if issues:
        return sorted(issues, key=lambda issue: (issue["path"], issue["message"]))
    for error in _validator(name).iter_errors(value):
        parts = list(error.absolute_path)
        if error.validator == "required":
            missing = next(field for field in error.validator_value
                           if error.message == f"{field!r} is a required property")
            parts.append(missing)
        issues.append({"path": _field_path(parts), "message": error.message})
    return sorted(issues, key=lambda issue: (issue["path"], issue["message"]))
