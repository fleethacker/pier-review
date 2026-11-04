"""Example request bodies for every modeling POST endpoint.

Single source for: Swagger "Try it out" examples, contract/examples/modeling/*.json (for the UI team) and the
contract tests. Scenario: DDG 51 starboard side to mock Pier 12 North, wind 22 kt gusting 30 from the pier side.
"""

from datetime import UTC, datetime

from mooring import refdata
from mooring.core.schemas import EnvironmentSnapshot

from .planning import END_LINES_DOUBLED, template_config

T0 = datetime(2026, 11, 4, 15, 48, tzinfo=UTC)
SHIP = "DDG-51-FIIA"
BERTH = "NAVSTA-NORFOLK-P12-N"


def _env() -> dict:
    return EnvironmentSnapshot(valid_at_utc=T0, source="scenario", wind_speed_kt=22, wind_gust_kt=30,
                               wind_from_true_deg=200, current_speed_kt=0.6, current_set_true_deg=10,
                               water_level_mllw_ft=1.8, tide_stage="ebb").model_dump(mode="json", exclude_none=True)


def _config() -> dict:
    cfg = template_config(refdata.ship(SHIP), refdata.berth(BERTH), "starboard", 650.0, "NYLON-DB-7IN", END_LINES_DOUBLED)
    return cfg.model_dump(mode="json", exclude_none=True)


def build() -> dict[str, dict]:
    env, cfg = _env(), _config()
    analyze = {"ship_class_id": SHIP, "loading": "full_load", "berth_id": BERTH, "config": cfg, "environment": env,
               "mst": "II", "lines_wet": True}
    return {
        "env_scenario": {"name": "MST II design condition", "kind": "steady", "wind_speed_kt": 64, "wind_gust_kt": 64,
                         "wind_from_true_deg": 195, "current_speed_kt": 2.0, "current_set_true_deg": 15,
                         "water_level_mllw_ft": 0.0},
        "scenario": {"name": "DDG at Pier 12 North", "ship_class_id": SHIP, "loading": "full_load", "berth_id": BERTH,
                     "side_to": "starboard", "env_source": {"mode": "mock"}, "config": cfg},
        "loads_environmental": {"ship_class_id": SHIP, "loading": "full_load", "heading_true_deg": 105.0,
                                "water_depth_ft": 46.8, "environment": env, "use_gust": True, "side_to": "starboard"},
        "loads_polar": {"ship_class_id": SHIP, "loading": "full_load", "water_depth_ft": 46.8, "wind_speed_kt": 50,
                        "current_speed_kt": 1.0, "apply_to": "both", "step_deg": 15},
        "mooring_analyze": analyze,
        "mooring_envelope": {**analyze, "step_deg": 15},
        "mooring_tide_sweep": {**analyze, "from_utc": "2026-11-04T16:00:00Z", "to_utc": "2026-11-05T04:00:00Z",
                               "step_min": 30},
        "risk_exceedance": {**analyze, "horizon_hours": 6, "n_samples": 200, "seed": 42},
        "risk_timeline": {**analyze, "forecast_hours": 24, "step_min": 60},
        "tugs_berthing_plan": {"ship_class_id": SHIP, "loading": "full_load", "berth_id": BERTH, "side_to": "starboard",
                               "environment": env, "margin": 0.25},
        "tugs_hold_plan": {**analyze, "margin": 0.25},
        "windows_berthing": {"berth_id": BERTH, "ship_class_id": SHIP, "side_to": "starboard",
                             "from_utc": "2026-11-04T12:00:00Z", "to_utc": "2026-11-05T12:00:00Z",
                             "max_current_kt": 0.5, "max_gust_kt": 25},
        "mooring_recommend": {"ship_class_id": SHIP, "loading": "full_load", "berth_id": BERTH, "side_to": "starboard",
                              "ship_x_ft": 650, "design_mst": "II", "max_candidates": 3},
        "mooring_sequence": {"ship_class_id": SHIP, "berth_id": BERTH, "config": cfg, "environment": env,
                             "line_handling_crews": 6},
        "berthing_simulate": {"scenario_id": "<scenario_id from POST /scenarios>",
                              "initial_state": {"x_ft": 650, "y_ft": 160, "heading_true_deg": 105.0, "v_kt": 0.0},
                              "tug_commands": [{"t_s": 0, "tug_id": "T1", "force_lbf": 40000, "direction_rel_deg": 90},
                                               {"t_s": 0, "tug_id": "T2", "force_lbf": 40000, "direction_rel_deg": 90},
                                               {"t_s": 120, "tug_id": "T1", "force_lbf": 0, "direction_rel_deg": 90},
                                               {"t_s": 120, "tug_id": "T2", "force_lbf": 0, "direction_rel_deg": 90}],
                              "duration_s": 600, "dt_s": 0.1, "env_mode": "steady"},
        "berthing_session": {"scenario_id": "<scenario_id from POST /scenarios>",
                             "initial_state": {"x_ft": 650, "y_ft": 160, "heading_true_deg": 105.0}},
        "approach_route": {"berth_id": BERTH, "ship_class_id": SHIP, "loading": "full_load"},
        "approach_ukc": {"ship_class_id": SHIP, "loading": "full_load",
                         "waypoints": [{"lat": 36.959, "lon": -76.045, "leg_name": "Thimble Shoal Channel entrance",
                                        "channel_depth_mllw_ft": 55, "width_ft": 1000},
                                       {"lat": 36.966, "lon": -76.16, "leg_name": "Thimble Shoal Channel",
                                        "channel_depth_mllw_ft": 55, "width_ft": 1000},
                                       {"lat": 36.964, "lon": -76.27, "leg_name": "Hampton Roads",
                                        "channel_depth_mllw_ft": 50, "width_ft": 1500}],
                         "eta_utc": "2026-11-04T18:00:00Z", "speed_profile_kt": [12, 10]},
        "approach_simulate": {"ship_class_id": SHIP, "loading": "full_load",
                              "waypoints": [{"lat": 36.964, "lon": -76.27, "leg_name": "Hampton Roads",
                                             "channel_depth_mllw_ft": 50, "width_ft": 1500},
                                            {"lat": 36.96, "lon": -76.315, "leg_name": "NAVSTA approach",
                                             "channel_depth_mllw_ft": 45, "width_ft": 800}],
                              "eta_utc": "2026-11-04T18:00:00Z", "speed_profile_kt": [8]},
        "telemetry_batch": {"records": [
            {"source": "ship_nmea", "t_utc": "2026-11-04T15:48:00Z", "sentence": "$WIMWV,045.0,R,18.5,N,A*1C"},
            {"source": "load_cell", "t_utc": "2026-11-04T15:48:00Z", "line_number": 2, "tension_lbf": 31000}]},
    }


EXAMPLES = build()


def ex(name: str, summary: str = "DDG 51 at mock Pier 12 North") -> dict:
    """openapi_examples value for FastAPI Body()."""
    return {"default": {"summary": summary, "value": EXAMPLES[name]}}
