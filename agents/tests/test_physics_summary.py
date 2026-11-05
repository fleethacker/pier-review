"""Summaries copy modeling's answers instead of deriving new physics or statistics."""

import re
from typing import Any

import pytest
from pydantic import BaseModel

from mooring_agents.physics.summary import summarize


def _number_tokens(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_number_tokens(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_number_tokens(item) for item in value))
    return set(re.findall(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", str(value)))


@pytest.mark.parametrize(("tool_name", "output", "expected"), [
    ("analyze_mooring", {"min_margin": {"element_id": "line-3", "pct_wll": 85.237}}, "85.237% WLL"),
    ("compute_loads", {"total": {"fx_lbf": -123.45, "fy_lbf": 678.9}}, "678.9 lbf"),
    ("limit_envelope", {"worst": {"first_failure_element": "line-4", "limit_wind_kt": 41.7,
                                  "wind_rel_deg": 75, "failure_mode": "WLL"}}, "41.7 kt"),
    ("risk_exceedance", {"governing_element": "line-6", "p_any_exceeds_wll": 0.17}, "probability 0.17"),
    ("recommend_config", {"candidates": [{"analysis_result_id": "res_candidate", "line_count": 9,
                                         "min_margin_pct_wll": 67.89}]}, "first candidate lines 9"),
    ("plan_tugs", {"recommended_tug_count": 3, "total_power_hp": 17200, "feasible": True}, "recommended tugs 3"),
    ("hold_tugs", {"recommended_tug_count": 2, "total_bollard_pull_lbf": 38000}, "38000 lbf"),
    ("generate_sequence", {"crews_required": 4, "steps": [{"action": "pass", "line_number": 7}]}, "first line 7"),
    ("berthing_windows", {"windows": [{"start_utc": "2026-11-04T12:30:00Z", "max_gust_kt": 31.25}]}, "31.25 kt"),
    ("get_environment", {"wind_speed_kt": 22.2, "wind_gust_kt": 37.45, "current_speed_kt": 0.31}, "gust 37.45 kt"),
    ("get_forecast", {"step_min": 24, "series": [{"wind_speed_kt": 13.4, "wind_gust_kt": 28.9}]}, "interval 24 min"),
    ("get_scenario", {"scenario_id": "scn_73", "ship_class_id": "DDG-51-FIIA", "side_to": "port"}, "scenario scn_73"),
    ("get_ship", {"class_id": "DDG-51-FIIA", "loa_ft": 509.5, "beam_ft": 66.2}, "length overall 509.5 ft"),
    ("get_berth", {"berth_id": "pier-12", "face_length_ft": 1100.8, "face_bearing_true_deg": 80.2}, "1100.8 ft"),
])
def test_summary_copies_values_without_new_numbers(tool_name, output, expected):
    envelope = {"result_id": "res_audit", "status": "AMBER", "backend": "mock", "result": output}
    summary = summarize(tool_name, envelope)
    assert summary == summarize(tool_name, envelope)
    assert expected in summary
    assert summary.startswith(f"{tool_name} res_audit: AMBER; backend mock;")
    assert _number_tokens(summary) <= _number_tokens(envelope)
    assert len(summary) < 400


def test_analysis_uses_modeling_governing_element_without_ranking_or_counting():
    result = {"min_margin": {"element_id": "line-3", "pct_wll": 85.237},
              "lines": [{"line_number": 99, "pct_wll": 9999.0}],
              "findings": [{"severity": "RED", "rule_id": "LINE-WLL"}]}
    summary = summarize("analyze_mooring", {"result": result})
    assert "line-3 governs at 85.237% WLL" in summary
    assert "first finding RED LINE-WLL" in summary
    assert "9999" not in summary and "line-99" not in summary
    assert _number_tokens(summary) <= _number_tokens(result)


def test_missing_values_are_not_derived_from_lines_or_findings():
    result = {"lines": [{"line_number": 3, "pct_wll": 85.237}], "findings": []}
    summary = summarize("analyze_mooring", result)
    assert "governs" not in summary and "WLL" not in summary
    assert not _number_tokens(summary)


def test_first_candidate_does_not_claim_to_be_best():
    result = {"candidates": [{"min_margin_pct_wll": 91.2}, {"min_margin_pct_wll": 50.1}]}
    summary = summarize("recommend_config", result)
    assert "first candidate highest utilization 91.2% WLL" in summary
    assert "best" not in summary and "50.1" not in summary


def test_typed_output_has_the_same_summary_as_json():
    class Response(BaseModel):
        result_id: str
        status: str
        result: dict

    output = Response(result_id="res_typed", status="GREEN",
                      result={"min_margin": {"element_id": "line-3", "pct_wll": 72.125}})
    assert summarize("analyze_mooring", output) == summarize("analyze_mooring", output.model_dump(mode="json"))


@pytest.mark.parametrize("output", [None, {}, {"result": None}, {"result": {"min_margin": None}}])
def test_missing_or_partial_output_is_safe(output):
    assert summarize("analyze_mooring", output) == "analyze_mooring: no summary fields supplied"


def test_structured_errors_are_reported_without_success_claims():
    error = {"error": {"code": "tool_budget_exceeded", "message": "Plan has reached its limit of 40 calls."}}
    summary = summarize("analyze_mooring", error)
    assert summary == "analyze_mooring: error; tool_budget_exceeded; Plan has reached its limit of 40 calls."
    assert _number_tokens(summary) <= _number_tokens(error)
