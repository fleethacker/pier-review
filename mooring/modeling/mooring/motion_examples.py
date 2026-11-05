"""RM0 display fixtures: authored values, never outputs of a physics simulation.

The recording prescribes a constant planar translation for 60 seconds. Loads and
environment values are independent illustrations of the wire fields, not a force
balance, a vessel response, observed conditions, or a selected wave model. No
reference-data records, clocks, network services, or random generators are used.
"""

from datetime import UTC, datetime, timedelta

from mooring.core.schemas import SimFrame, SimLifecycle, SimRecording, SimScene
from mooring.core.units import KT_TO_FPS


T0 = datetime(2026, 11, 4, 15, 48, tzinfo=UTC)
SESSION_ID = "sim_rm0_fixture"
RUN_ID = "run_rm0_fixture"
SCENE_ID = "scene_rm0_fixture"
SCENE_REVISION = "1"


def _validity(component: str) -> dict:
    return {
        "state": "limited",
        "reasons": [{
            "code": "AUTHORED_DISPLAY_FIXTURE",
            "message": "Authored display value; no physical solution.",
            "affected_components": [component],
        }],
    }


def _provenance(*, detail: bool = False) -> dict:
    return {
        "kind": "mock",
        "source": "RM0 display fixture",
        "references": [],
        "notes": ["Prescribed planar translation; independent illustrative loads; no physics, force balance, or vessel qualification."]
                 if detail else [],
    }


def _component(component: str, availability: str = "available") -> dict:
    return {"availability": availability, "validity": _validity(component), "provenance": _provenance()}


def _position(x_ft: float, y_ft: float, z_mllw_ft: float | None = None) -> dict:
    return {"x_ft": x_ft, "y_ft": y_ft, "z_mllw_ft": z_mllw_ft}


def _ship_motion(t_s: float) -> dict:
    return {
        **_component("ship"),
        "pose": {"x_ft": 300, "y_ft": 80 - 0.25 * t_s, "yaw_deg": 0},
        "velocity": {"surge_fps": 0, "sway_fps": -0.25, "yaw_degps": 0},
        "acceleration": {"surge_fps2": 0, "sway_fps2": 0, "yaw_degps2": 0},
        "dofs": {
            "surge": "prescribed", "sway": "prescribed", "yaw": "prescribed",
            "heave": "not_simulated", "roll": "not_simulated", "pitch": "not_simulated",
        },
    }


def _tug(t_s: float) -> dict:
    return {
        **_component("tug-fixture"),
        "tug_id": "tug-fixture",
        "position": _position(300, 115 - 0.25 * t_s),
        "heading_true_deg": 180,
        "velocity": {"x_fps": 0, "y_fps": -0.25},
        "acceleration": {"x_fps2": 0, "y_fps2": 0},
        "commanded_force": {"x_lbf": 0, "y_lbf": -1500},
        "actual_force": {"x_lbf": 0, "y_lbf": -1000},
        "push_point_id": "push-port-midships",
        "contact_position": _position(300, 100 - 0.25 * t_s),
        "mode": "push",
        "contact_state": "contact",
        "capacity_utilization_pct": 10,
    }


def _environment(t_s: float) -> dict:
    metadata = {"basis": "scenario", "source": "RM0 authored display fixture", "vertical_datum": "MLLW"}
    return {
        "t_s": t_s,
        "valid_at_utc": T0 + timedelta(seconds=t_s),
        "wind": {**_component("wind"), "speed_kt": 12, "gust_kt": 15, "from_true_deg": 180,
                 "metadata": {**metadata, "wind_averaging_s": 60, "gust_duration_s": 3, "wind_reference_height_m": 10}},
        "current": {**_component("current"), "speed_kt": 0.2, "set_true_deg": 0,
                    "metadata": {**metadata, "current_depth_ft": 6}},
        "water": {**_component("water"), "level_mllw_ft": 2, "metadata": metadata},
        "waves": {
            name: {
                **_component(name, "unavailable"),
                "provenance": {**_provenance(), "notes": ["No wave source or wave model selected by this fixture."]},
                "validity": {"state": "unknown", "reasons": [{
                    "code": "WAVE_SOURCE_UNAVAILABLE", "message": "No wave source supplied; not a zero-wave claim.",
                    "affected_components": [name],
                }]},
            }
            for name in ("ocean_swell", "local_chop", "ship_wake", "tug_wake")
        },
    }


def _scene() -> SimScene:
    return SimScene.model_validate({
        **_component("scene"), "scene_id": SCENE_ID, "revision": SCENE_REVISION,
        "berth_id": "MOCK-DISPLAY-BERTH", "ship_class_id": "MOCK-DISPLAY-HULL", "loading": "illustrative",
        "face_bearing_true_deg": 90, "deck_height_mllw_ft": 8,
        "berth_outline": [_position(x, y, 8) for x, y in ((0, -30), (600, -30), (600, 0), (0, 0))],
        "ship_hull_outline": [{"x_ft": x, "y_ft": y, "z_ft": 0}
                              for x, y in ((-100, -20), (80, -20), (100, 0), (80, 20), (-100, 20))],
        "ship_fittings": [
            {**_component(name), "fitting_id": name, "kind": "mooring_bitt", "capacity_lbf": 25000,
             "position": {"x_ft": x, "y_ft": -20, "z_ft": 8}}
            for name, x in (("ship-forward", 60), ("ship-aft", -60))
        ] + [{**_component("push-port-midships"), "fitting_id": "push-port-midships", "kind": "tug_push_point",
              "position": {"x_ft": 0, "y_ft": 20, "z_ft": 0}}],
        "pier_fittings": [
            {**_component(name), "fitting_id": name, "kind": "bollard", "capacity_lbf": 50000,
             "position": _position(x, 0, 8)}
            for name, x in (("pier-forward", 360), ("pier-aft", 240))
        ],
        "fenders": [{**_component("fender-fixture"), "fender_id": "fender-fixture",
                     "position": _position(300, 0, 4), "length_ft": 20, "standoff_ft": 2}],
        "depth_profile": [{**_component("depth"), "position": _position(x, 100), "depth_mllw_ft": 40}
                          for x in (0, 300, 600)],
    })


def _line(number: int, t_s: float) -> dict:
    name, x, tension, status = ("forward", 360, 12500, "taut") if number == 1 else ("aft", 240, 0, "slack")
    ship_end = _position(x, 60 - 0.25 * t_s)
    pier_end = _position(x, 0, 8)
    return {
        **_component(f"line-{number}"), "line_number": number, "tension_lbf": tension, "status": status,
        "ship_fitting_id": f"ship-{name}", "pier_fitting_id": f"pier-{name}",
        "ship_end": ship_end, "pier_end": pier_end, "polyline": [ship_end, pier_end],
    }


def _wrench(name: str, y_lbf: float, yaw_moment_ftlbf: float = 0) -> dict:
    return {**_component(name), "force": {"x_lbf": 0, "y_lbf": y_lbf}, "yaw_moment_ftlbf": yaw_moment_ftlbf}


def _frame(t_s: float, sequence: int) -> SimFrame:
    return SimFrame.model_validate({
        "schema_version": "rm0-v1", "session_id": SESSION_ID, "run_id": RUN_ID,
        "scene_id": SCENE_ID, "scene_revision": SCENE_REVISION, "sequence": sequence, "t_s": t_s,
        "pose": {"x_ft": 300, "y_ft": 80 - 0.25 * t_s, "heading_true_deg": 90,
                 "u_kt": 0, "v_kt": 0.25 / KT_TO_FPS, "r_degps": 0},
        "tugs": [{"tug_id": "tug-fixture", "force_lbf": 1000, "direction_rel_deg": 90}],
        "lines": [{"line_number": 1, "tension_lbf": 12500}, {"line_number": 2, "tension_lbf": 0}],
        "fenders": [{"fender_id": "fender-fixture", "compression_ft": 0, "reaction_lbf": 0, "status": "AMBER"}],
        "alerts": ["MOCK display fixture; prescribed motion and independent illustrative loads."],
        "motion": _ship_motion(t_s), "tug_states": [_tug(t_s)], "environment": _environment(t_s),
        "line_states": [_line(1, t_s), _line(2, t_s)],
        "fitting_loads": [
            {**_component(f"{owner}-{end}"), "fitting_id": f"{owner}-{end}", "owner": owner,
             "load_lbf": load, "capacity_lbf": capacity, "utilization_pct": pct,
             "status": "AMBER"}
            for owner, end, load, capacity, pct in (
                ("ship", "forward", 12500, 25000, 50), ("pier", "forward", 12500, 50000, 25),
                ("ship", "aft", 0, 25000, 0), ("pier", "aft", 0, 50000, 0),
            )
        ],
        "fender_states": [{**_component("fender-fixture"), "fender_id": "fender-fixture",
                           "compression_ft": 0, "reaction_lbf": 0, "status": "AMBER"}],
        "forces": {
            "wind": _wrench("wind", 500), "current": _wrench("current", 250),
            "waves": {name: {
                **_component(name, "unavailable"),
                "validity": {"state": "unknown", "reasons": [{
                    "code": "WAVE_SOURCE_UNAVAILABLE", "message": "No wave forcing supplied; not a zero-force claim.",
                    "affected_components": [name],
                }]},
            } for name in ("ocean_swell", "local_chop", "ship_wake", "tug_wake")},
            "tugs": _wrench("tugs", -1000), "lines": _wrench("lines", -12500, -750000),
            "fenders": _wrench("fenders", 0),
        },
        "validity": _validity("frame"), "provenance": _provenance(detail=True),
        "structured_alerts": [{"code": "AUTHORED_DISPLAY_FIXTURE", "severity": "AMBER",
                               "message": "MOCK: prescribed trajectory; loads do not solve dynamics or force balance.",
                               "element_ids": ["ship"]}],
    })


def _lifecycle(state: str, sequence: int, t_s: float, run_id: str = RUN_ID) -> SimLifecycle:
    return SimLifecycle.model_validate({
        "session_id": SESSION_ID, "run_id": run_id, "sequence": sequence, "t_s": t_s, "state": state,
        "scene_id": SCENE_ID, "scene_revision": SCENE_REVISION,
        "message": "Illustrative session error; no runtime failure was produced." if state == "error"
                   else f"Authored {state} lifecycle example; no live session was run.",
        "validity": _validity("session"), "provenance": _provenance(),
    })


def build() -> dict[str, dict]:
    """Rebuild isolated, deterministic fixtures; static scene geometry is exported once."""
    frames = [_frame(t_s, t_s + 2) for t_s in range(61)]
    recording = SimRecording.model_validate({
        "recording_id": "recording_rm0_fixture", "duration_s": 60,
        "session_id": SESSION_ID, "scene_id": SCENE_ID, "scene_revision": SCENE_REVISION,
        "frames": frames,
        "lifecycle": [_lifecycle("created", 0, 0), _lifecycle("running", 1, 0), _lifecycle("ended", 63, 60)],
        "sampling": {"display_interval_s": 1, "max_pending_frames": 1},
        "validity": _validity("recording"), "provenance": _provenance(detail=True),
    })
    examples = {"sim_scene": _scene(), "sim_frame": frames[30], "sim_recording_60s": recording}
    # These show each state independently; they are not a second executed trajectory.
    for state, sequence, t_s, run_id in (
        ("created", 0, 0, RUN_ID), ("running", 1, 0, RUN_ID), ("paused", 63, 60, RUN_ID),
        ("reset", 64, 0, RUN_ID + "_reset"), ("ended", 65, 0, RUN_ID + "_reset"),
        ("error", 66, 0, RUN_ID + "_reset"),
    ):
        examples[f"sim_lifecycle_{state}"] = _lifecycle(state, sequence, t_s, run_id)
    return {name: example.model_dump(mode="json") for name, example in examples.items()}


# Kept separate from request examples so Swagger bodies retain their original shape.
MOTION_EXAMPLES = build()
