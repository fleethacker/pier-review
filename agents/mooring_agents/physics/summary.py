"""Compact, deterministic tool summaries using only values supplied by modeling.

Governing elements and worst conditions must already be identified in the response. We do not rank
elements, count findings, convert probabilities to percentages, or round the supplied numbers.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return value if isinstance(value, Mapping) else {}


def _first(value: Any) -> Mapping[str, Any]:
    return _mapping(value[0]) if isinstance(value, list) and value else {}


def _text(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _fields(data: Mapping[str, Any], *fields: tuple[str, str, str]) -> list[str]:
    parts = []
    for key, label, unit in fields:
        value = _text(data.get(key))
        if value is not None:
            parts.append(f"{label}{value}{unit}")
    return parts


def summarize(tool_name: str, output: Any) -> str:
    """Summarize a modeling response or toolkit error without deriving any new values.

    Both decoded JSON and typed response models are accepted. Missing fields are omitted. For a list
    without a modeling-selected best item, only its first item is shown and explicitly labeled as first.
    """
    envelope = _mapping(output)
    header = tool_name
    result_id = _text(envelope.get("result_id"))
    if result_id is not None:
        header += f" {result_id}"

    error = envelope.get("error")
    if error is not None:
        details = _fields(_mapping(error), ("code", "", ""), ("message", "", ""))
        if not details and _text(error) is not None:
            details.append(_text(error))
        return f"{header}: error" + ("; " + "; ".join(details) if details else "")

    parts = _fields(envelope, ("status", "", ""), ("backend", "backend ", ""))
    result = _mapping(envelope.get("result")) if "result" in envelope else envelope

    if tool_name == "analyze_mooring":
        margin = _mapping(result.get("min_margin"))
        element = _text(margin.get("element_id"))
        utilization = _text(margin.get("pct_wll"))
        if element is not None and utilization is not None:
            parts.append(f"{element} governs at {utilization}% WLL")
        else:
            parts += _fields(margin, ("element_id", "governing element ", ""),
                             ("pct_wll", "highest utilization ", "% WLL"))
        finding = _first(result.get("findings"))
        finding_parts = _fields(finding, ("severity", "", ""), ("rule_id", "", ""))
        if finding_parts:
            parts.append("first finding " + " ".join(finding_parts))
    elif tool_name == "compute_loads":
        parts += _fields(_mapping(result.get("total")), ("fx_lbf", "total longitudinal force ", " lbf"),
                         ("fy_lbf", "total lateral force ", " lbf"))
        parts += _fields(result, ("off_pier_component_lbf", "off-pier force ", " lbf"))
    elif tool_name == "limit_envelope":
        parts += _fields(_mapping(result.get("worst")),
                         ("first_failure_element", "governing element ", ""),
                         ("limit_wind_kt", "worst wind limit ", " kt"),
                         ("wind_rel_deg", "relative wind direction ", " deg"),
                         ("failure_mode", "failure mode ", ""))
    elif tool_name == "risk_exceedance":
        parts += _fields(result, ("governing_element", "governing element ", ""),
                         ("p_any_exceeds_wll", "WLL exceedance probability ", ""),
                         ("p_any_exceeds_mbs", "breaking-strength exceedance probability ", ""))
    elif tool_name == "recommend_config":
        candidate = _first(result.get("candidates"))
        parts += _fields(candidate, ("analysis_result_id", "first candidate analysis ", ""),
                         ("min_margin_pct_wll", "first candidate highest utilization ", "% WLL"),
                         ("line_count", "first candidate lines ", ""),
                         ("limit_wind_kt_worst", "first candidate worst wind limit ", " kt"))
    elif tool_name in ("plan_tugs", "hold_tugs"):
        parts += _fields(result, ("feasible", "feasible ", ""),
                         ("recommended_tug_count", "recommended tugs ", ""),
                         ("total_bollard_pull_lbf", "total bollard pull ", " lbf"),
                         ("total_power_hp", "total power ", " hp"))
    elif tool_name == "generate_sequence":
        parts += _fields(result, ("crews_required", "crews required ", ""))
        parts += _fields(_first(result.get("steps")), ("action", "first action ", ""),
                         ("station", "first station ", ""), ("line_number", "first line ", ""))
    elif tool_name == "berthing_windows":
        parts += _fields(_first(result.get("windows")), ("start_utc", "first window starts ", ""),
                         ("end_utc", "first window ends ", ""),
                         ("max_current_kt", "first window max current ", " kt"),
                         ("max_gust_kt", "first window max gust ", " kt"))
    elif tool_name in ("get_environment", "get_scenario_environment"):
        parts += _fields(result, ("wind_speed_kt", "wind ", " kt"), ("wind_gust_kt", "gust ", " kt"),
                         ("current_speed_kt", "current ", " kt"),
                         ("water_level_mllw_ft", "water level ", " ft MLLW"))
    elif tool_name == "get_forecast":
        parts += _fields(result, ("berth_id", "berth ", ""), ("step_min", "interval ", " min"))
        parts += _fields(_first(result.get("series")), ("valid_at_utc", "first forecast at ", ""),
                         ("wind_speed_kt", "first forecast wind ", " kt"),
                         ("wind_gust_kt", "first forecast gust ", " kt"))
    elif tool_name == "get_scenario":
        parts += _fields(result, ("scenario_id", "scenario ", ""), ("ship_class_id", "ship ", ""),
                         ("berth_id", "berth ", ""), ("side_to", "side ", ""))
    elif tool_name == "get_ship":
        parts += _fields(result, ("class_id", "", ""), ("name", "", ""),
                         ("loa_ft", "length overall ", " ft"), ("beam_ft", "beam ", " ft"),
                         ("mst_class", "MST ", ""))
    elif tool_name == "get_berth":
        parts += _fields(result, ("berth_id", "", ""), ("name", "", ""),
                         ("face_length_ft", "face length ", " ft"),
                         ("face_bearing_true_deg", "face bearing ", " deg true"))

    return f"{header}: " + ("; ".join(parts) if parts else "no summary fields supplied")
