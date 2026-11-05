"""Stable demo identifiers and requests. No automatic mutation of saved scenarios."""
from copy import deepcopy

from mooring.core.schemas.demo import DockingDemoCase
from mooring.examples import EXAMPLES


def docking_cases() -> list[DockingDemoCase]:
    cases = []
    for key, name, wind, gust, current, water, explanation in (
        ("supported_limited", "DDG moderate weather — limited demonstration", 4, 5, .1, 1.8,
         "Real equilibrium within capacity, using unqualified seed data. AMBER/limited is expected, never unconditional GREEN."),
        ("overloaded", "DDG storm — overloaded", 75, 100, .6, 1.8,
         "Completed RED result with overloaded elements; not an HTTP failure."),
        ("invalid_data", "DDG inadequate depth — invalid", 4, 5, .1, -41,
         "Water depth is below draft. Do not interpret computed loads as an admissible mooring."),
        ("undetermined", "DDG incomplete line plan — undetermined", 4, 5, .1, 1.8,
         "Only one line is supplied. Equilibrium is not established and limiting-wind outcomes are undetermined, not zero or safe."),
    ):
        analysis = deepcopy(EXAMPLES["mooring_analyze"])
        analysis["environment"].update(wind_speed_kt=wind, wind_gust_kt=gust,
                                       current_speed_kt=current, water_level_mllw_ft=water)
        if key == "undetermined":
            analysis["config"]["lines"] = analysis["config"]["lines"][:1]
        env = {k: analysis["environment"][k] for k in (
            "wind_speed_kt", "wind_gust_kt", "wind_from_true_deg", "current_speed_kt",
            "current_set_true_deg", "water_level_mllw_ft")}
        scenario = {**deepcopy(EXAMPLES["scenario"]), "name": name, "config": analysis["config"],
                    "env_source": {"mode": "scenario", "env_scenario_id": "<id returned by POST /env/scenarios>"}}
        cases.append(DockingDemoCase(case_id=f"ddg-{key.replace('_', '-')}", name=name,
            expected_outcome=key, explanation=explanation,
            environment_request={"name": name, "kind": "steady", **env},
            scenario_request=scenario, analysis_request=analysis,
            envelope_request={**analysis, "step_deg": 90, "max_search_kt": 10} if key == "undetermined" else None))
    return cases
