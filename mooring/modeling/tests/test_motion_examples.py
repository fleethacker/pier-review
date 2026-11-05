"""RM0 fixture integrity and public JSON Schema checks, independent of physics."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modeling_api.main import openapi_schema
from mooring.core.units import KT_TO_FPS
from mooring.motion_examples import MOTION_EXAMPLES, build


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SCHEMAS = {
    "sim_scene": "SimScene",
    "sim_frame": "SimFrame",
    "sim_recording_60s": "SimRecording",
    **{f"sim_lifecycle_{state}": "SimLifecycle"
       for state in ("created", "running", "paused", "reset", "ended", "error")},
}


@pytest.mark.parametrize("name,schema_name", EXAMPLE_SCHEMAS.items())
def test_published_motion_examples_validate_against_openapi(name, schema_name):
    contract = openapi_schema()
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": contract["components"]}
    validator = Draft202012Validator(schema)
    path = ROOT / "contract" / "examples" / "modeling" / f"{name}.json"
    published = json.loads(path.read_text())
    assert published == MOTION_EXAMPLES[name]
    validator.validate(published)


def test_examples_are_deterministic_and_independent_of_refdata(monkeypatch):
    from mooring import refdata

    def forbidden(*args, **kwargs):
        raise AssertionError("Motion display fixtures must not load or alter reference records")

    monkeypatch.setattr(refdata, "ship", forbidden)
    monkeypatch.setattr(refdata, "berth", forbidden)
    expected = json.dumps(MOTION_EXAMPLES, indent=2, allow_nan=False)
    first, second = build(), build()
    assert json.dumps(first, indent=2, allow_nan=False) == expected
    assert json.dumps(second, indent=2, allow_nan=False) == expected
    first["sim_frame"]["pose"]["x_ft"] = -999
    assert second == MOTION_EXAMPLES == build()


def test_recording_is_sixty_seconds_of_ordered_samples_with_one_static_scene():
    recording = MOTION_EXAMPLES["sim_recording_60s"]
    frames = recording["frames"]
    assert len(frames) == 61
    assert [frame["t_s"] for frame in frames] == list(range(61))
    assert frames[-1]["t_s"] - frames[0]["t_s"] == 60
    sequences = [frame["sequence"] for frame in frames]
    assert sequences == sorted(set(sequences))
    for frame in frames:
        assert frame["scene_id"] == MOTION_EXAMPLES["sim_scene"]["scene_id"]
        assert frame["scene_revision"] == MOTION_EXAMPLES["sim_scene"]["revision"]
        assert "scene" not in frame
        assert "berth_outline" not in frame and "ship_hull_outline" not in frame


def test_all_six_lifecycle_states_have_independent_examples():
    states = ("created", "running", "paused", "reset", "ended", "error")
    samples = [MOTION_EXAMPLES[f"sim_lifecycle_{state}"] for state in states]
    assert [sample["state"] for sample in samples] == list(states)
    assert samples[3]["run_id"] != samples[2]["run_id"]
    assert samples[3]["t_s"] == 0
    assert samples[-1]["message"]


def test_recorded_positions_match_static_fittings_and_prescribed_kinematics():
    scene = MOTION_EXAMPLES["sim_scene"]
    ship_fittings = {fitting["fitting_id"]: fitting for fitting in scene["ship_fittings"]}
    pier_fittings = {fitting["fitting_id"]: fitting for fitting in scene["pier_fittings"]}
    for frame in MOTION_EXAMPLES["sim_recording_60s"]["frames"]:
        pose, velocity = frame["motion"]["pose"], frame["motion"]["velocity"]
        assert pose["x_ft"] == 300 and pose["yaw_deg"] == 0
        assert pose["y_ft"] == 80 - 0.25 * frame["t_s"]
        assert frame["pose"]["heading_true_deg"] == scene["face_bearing_true_deg"]
        assert frame["pose"]["v_kt"] * KT_TO_FPS == pytest.approx(-velocity["sway_fps"])
        assert frame["pose"]["x_ft"] == pose["x_ft"] and frame["pose"]["y_ft"] == pose["y_ft"]
        for line in frame["line_states"]:
            local = ship_fittings[line["ship_fitting_id"]]["position"]
            assert line["ship_end"] == {
                "x_ft": pose["x_ft"] + local["x_ft"], "y_ft": pose["y_ft"] + local["y_ft"], "z_mllw_ft": None,
            }
            assert line["pier_end"] == pier_fittings[line["pier_fitting_id"]]["position"]
            assert line["polyline"] == [line["ship_end"], line["pier_end"]]
        tug = frame["tug_states"][0]
        push_point = ship_fittings[tug["push_point_id"]]["position"]
        assert tug["contact_position"]["x_ft"] == pose["x_ft"] + push_point["x_ft"]
        assert tug["contact_position"]["y_ft"] == pose["y_ft"] + push_point["y_ft"]
        assert tug["velocity"]["y_fps"] == velocity["sway_fps"]


def test_mock_and_unknown_components_are_never_presented_as_qualified_physics():
    for frame in MOTION_EXAMPLES["sim_recording_60s"]["frames"]:
        assert frame["provenance"]["kind"] == "mock"
        assert frame["validity"]["state"] == "limited"
        assert frame["structured_alerts"][0]["severity"] == "AMBER"
        motion = frame["motion"]
        assert all(motion["dofs"][axis] == "prescribed" for axis in ("surge", "sway", "yaw"))
        for axis, position, velocity, acceleration in (
            ("heave", "heave_mllw_ft", "heave_fps", "heave_fps2"),
            ("roll", "roll_deg", "roll_degps", "roll_degps2"),
            ("pitch", "pitch_deg", "pitch_degps", "pitch_degps2"),
        ):
            assert motion["dofs"][axis] == "not_simulated"
            assert motion["pose"][position] is None
            assert motion["velocity"][velocity] is None
            assert motion["acceleration"][acceleration] is None
        environment = frame["environment"]
        assert environment["t_s"] == frame["t_s"]
        for name in ("wind", "current", "water"):
            assert environment[name]["provenance"]["kind"] == "mock"
            assert environment[name]["validity"]["state"] == "limited"
        for name in ("ocean_swell", "local_chop", "ship_wake", "tug_wake"):
            wave = environment["waves"][name]
            assert wave["availability"] == "unavailable" and wave["validity"]["state"] == "unknown"
            assert wave["height_ft"] is None and wave["period_s"] is None and wave["from_true_deg"] is None
            assert frame["forces"]["waves"][name]["availability"] == "unavailable"
            assert frame["forces"]["waves"][name]["force"] is None
