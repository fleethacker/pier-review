"""Adversarial RM0 cases: identity, qualification and reset/element ambiguity."""
import copy

import pytest
from pydantic import ValidationError

from mooring.core.schemas import SimFrame, SimLifecycle, SimRecording, SimScene
from mooring.core.schemas.motion import MotionFenderState, MotionFittingLoad
from mooring.motion_examples import MOTION_EXAMPLES

INVALID = {"state": "invalid", "reasons": [{"code": "TEST_INVALID", "message": "Do not rely on this component."}]}
LIMITED = {"state": "limited", "reasons": [{"code": "TEST_LIMITED", "message": "Unqualified."}]}


@pytest.mark.parametrize("field", ["session_id", "run_id", "sequence", "scene_id", "scene_revision"])
@pytest.mark.parametrize("missing", [None, ""])
def test_opted_in_frames_need_complete_identity(field, missing):
    data = copy.deepcopy(MOTION_EXAMPLES["sim_frame"])
    data[field] = missing
    with pytest.raises(ValidationError):
        SimFrame.model_validate(data)


@pytest.mark.parametrize("field", ["tug_states", "line_states", "fitting_loads", "fender_states"])
def test_rich_frame_component_identifiers_cannot_repeat(field):
    data = copy.deepcopy(MOTION_EXAMPLES["sim_frame"])
    data[field].append(copy.deepcopy(data[field][0]))
    with pytest.raises(ValidationError, match="unique"):
        SimFrame.model_validate(data)


def test_fitting_identity_includes_ship_or_pier_owner():
    data = copy.deepcopy(MOTION_EXAMPLES["sim_frame"])
    data["fitting_loads"] = [data["fitting_loads"][0], {**data["fitting_loads"][0], "owner": "pier"}]
    assert len(SimFrame.model_validate(data).fitting_loads) == 2


@pytest.mark.parametrize("model,name,path", [
    (SimFrame, "sim_frame", ("forces", "wind")),
    (SimScene, "sim_scene", ("ship_fittings", 0)),
    (SimRecording, "sim_recording_60s", ("frames", 0)),
])
@pytest.mark.parametrize("parent_validity", [None, {"state": "unknown"}, LIMITED])
def test_parent_cannot_hide_invalid_descendant(model, name, path, parent_validity):
    data = copy.deepcopy(MOTION_EXAMPLES[name])
    data["validity"] = parent_validity
    child = data
    for key in path:
        child = child[key]
    child["validity"] = INVALID
    with pytest.raises(ValidationError, match="invalid"):
        model.model_validate(data)
    data["validity"] = INVALID
    assert model.model_validate(data).validity.state == "invalid"


@pytest.mark.parametrize("model,ids", [(MotionFenderState, {"fender_id": "f"}),
                                      (MotionFittingLoad, {"fitting_id": "b", "owner": "pier"})])
@pytest.mark.parametrize("validity,status", [(LIMITED, "GREEN"), (INVALID, "GREEN"), (INVALID, "AMBER")])
def test_motion_status_cannot_contradict_validity(model, ids, validity, status):
    with pytest.raises(ValidationError):
        model(**ids, validity=validity, status=status)
    assert model(**ids, validity=validity, status="RED").status == "RED"


@pytest.mark.parametrize("sequence", [True, 1.0, "1"])
def test_lifecycle_sequence_is_an_integer_without_coercion(sequence):
    data = copy.deepcopy(MOTION_EXAMPLES["sim_lifecycle_paused"])
    data["sequence"] = sequence
    with pytest.raises(ValidationError):
        SimLifecycle.model_validate(data)


def test_reset_must_start_at_zero_and_use_a_new_run():
    reset = copy.deepcopy(MOTION_EXAMPLES["sim_lifecycle_reset"])
    with pytest.raises(ValidationError):
        SimLifecycle.model_validate({**reset, "t_s": 1})
    data = copy.deepcopy(MOTION_EXAMPLES["sim_recording_60s"])
    # Existing frames begin at zero; a reset immediately before them still needs a new run.
    data["lifecycle"] = [{**reset, "run_id": data["frames"][0]["run_id"], "sequence": 1},
                         *[e for e in data["lifecycle"] if e["state"] == "ended"]]
    data["lifecycle"].insert(0, {**reset, "state": "created", "run_id": data["frames"][0]["run_id"], "sequence": 0})
    with pytest.raises(ValidationError, match="reset"):
        SimRecording.model_validate(data)


@pytest.mark.parametrize("field", ["sequence", "session_id", "run_id", "scene_id", "scene_revision"])
def test_public_json_schema_requires_rm0_identity_without_breaking_legacy(field):
    from jsonschema import Draft202012Validator, ValidationError as SchemaError
    validator = Draft202012Validator(SimFrame.model_json_schema())
    data = copy.deepcopy(MOTION_EXAMPLES["sim_frame"])
    del data[field]
    with pytest.raises(SchemaError):
        validator.validate(data)
    validator.validate({key: data[key] for key in ("t_s", "pose", "tugs", "lines", "fenders", "alerts")})
