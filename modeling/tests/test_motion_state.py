"""Offline state-import contract, provenance and frame-conversion evidence."""

import math
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from mooring.berthing.motion_state import MotionStateRejected, prepare_state_reseed, to_legacy_ship_state
from mooring.core.schemas.motion_state import MotionStateInput, MotionStatePolicy, MotionStateSnapshot
from mooring.core.units import KT_TO_FPS

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def observation(**changes):
    data = dict(entity="ship", entity_id="ownship", frame="berth", berth_id="SYN-PIER",
        source="synthetic", source_name="Explicit synthetic test", observed_at_utc=NOW-timedelta(seconds=2),
        sequence=1, x_ft=400, y_ft=70, heading_true_deg=102, surge_fps=-2.5,
        sway_fps=.75, yaw_degps=-.2)
    data.update(changes)
    return MotionStateInput.model_validate(data)


def accept(req=None, **changes):
    context = dict(session_id="session", run_id="run", simulation_time_s=12.3,
        expected_entity="ship", expected_entity_id="ownship", expected_berth_id="SYN-PIER",
        face_bearing_true_deg=90, side_to="starboard", paused=True, previous_by_entity={}, now_utc=NOW)
    context.update(changes)
    return prepare_state_reseed(req or observation(), **context)


def rejects(code, req=None, **context):
    with pytest.raises(MotionStateRejected) as caught:
        accept(req, **context)
    assert caught.value.code == code


def test_complete_planar_state_and_timestamp_are_preserved_without_extrapolation():
    r = accept()
    assert r.as_integrator_state() == pytest.approx((400, 70, math.radians(-12), -2.5, .75, math.radians(-.2)))
    assert r.input.observed_at_utc == NOW-timedelta(seconds=2)
    assert r.accepted_at_utc == NOW and r.age_s == 2 and r.simulation_time_s == 12.3
    assert r.input.measured_acceleration is None
    assert r.state.x_ft == 400 and r.state.y_ft == 70  # not extrapolated by the two-second age
    assert r.run_id != r.previous_run_id and r.previous_run_id == "run"
    assert r.qualification == "unqualified"
    assert MotionStateSnapshot.model_validate_json(r.model_dump_json()) == r


@pytest.mark.parametrize("side,heading,yaw,legacy_sign", [
    ("starboard", 90, 0, -1), ("port", 270, -180, 1),
    ("starboard", 359, 91, -1), ("port", 1, 89, 1),
])
def test_heading_body_velocity_and_legacy_side_sign_are_distinct(side, heading, yaw, legacy_sign):
    req = observation(heading_true_deg=heading)
    r = accept(req, side_to=side)
    assert r.state.yaw_rad == pytest.approx(math.radians(yaw))
    assert r.state.surge_fps == -2.5 and r.state.sway_fps == .75
    legacy = to_legacy_ship_state(r, side_to=side)
    assert legacy.heading_true_deg == heading
    assert legacy.u_kt == pytest.approx(-2.5/KT_TO_FPS)
    assert legacy.v_kt == pytest.approx(legacy_sign*.75/KT_TO_FPS)
    assert legacy.r_degps == pytest.approx(-.2)


def test_tug_uses_its_own_body_axes_and_cannot_be_projected_as_legacy_ship():
    req = observation(entity="tug", entity_id="T1", heading_true_deg=180, sway_fps=-1.5)
    r = accept(req, expected_entity="tug", expected_entity_id="T1")
    assert r.as_integrator_state() == pytest.approx((400, 70, -math.pi/2, -2.5, -1.5, math.radians(-.2)))
    with pytest.raises(MotionStateRejected, match="only defined for the ship"):
        to_legacy_ship_state(r, side_to="starboard")


@pytest.mark.parametrize("accel", [None, {}, {"surge_fps2": None, "sway_fps2": None, "yaw_degps2": None},
                                     {"surge_fps2": 0}, {"sway_fps2": 1.25, "yaw_degps2": -.5}])
def test_optional_acceleration_preserves_unknowns_and_never_becomes_state_or_force(accel):
    r = accept(observation(measured_acceleration=accel))
    assert r.as_integrator_state() == accept().as_integrator_state()
    assert len(r.as_integrator_state()) == 6
    measured = r.input.measured_acceleration
    if accel is None:
        assert measured is None
    else:
        for key in ("surge_fps2", "sway_fps2", "yaw_degps2"):
            assert getattr(measured, key) == accel.get(key)
    assert any("evidence only" in line for line in r.limitations)


def test_acceleration_and_source_change_input_identity_without_inventing_motion():
    a = accept()
    b = accept(observation(measured_acceleration={"surge_fps2": .5}))
    c = accept(observation(source="sensor", source_name="Caller-supplied sensor file"))
    assert len({a.input_hash, b.input_hash, c.input_hash}) == 3
    assert a.as_integrator_state() == b.as_integrator_state() == c.as_integrator_state()
    assert all(len(r.input_hash) == 64 for r in (a, b, c))
    assert any("does not establish a hardware connection" in line for line in c.limitations)


def test_source_offset_and_observation_time_survive_utc_clock_comparison():
    offset = timezone(timedelta(hours=5, minutes=30))
    t = (NOW-timedelta(seconds=2)).astimezone(offset)
    r = accept(observation(observed_at_utc=t))
    assert r.input.observed_at_utc.isoformat() == t.isoformat()
    assert r.age_s == 2 and r.accepted_at_utc.tzinfo == UTC


def test_identical_input_is_content_stable_but_a_new_run_context_changes_acceptance_identity():
    a, b = accept(), accept()
    c = accept(run_id="different-run")
    assert a == b and a.input_hash == c.input_hash
    assert a.snapshot_id != c.snapshot_id and a.run_id != c.run_id


@pytest.mark.parametrize("paused", [False, None, 1, "true"])
def test_reseed_is_only_prepared_for_an_explicitly_paused_session(paused):
    rejects("STATE_REQUIRES_PAUSED", paused=paused)


@pytest.mark.parametrize("update,context,code", [
    ({"entity": "tug"}, {}, "STATE_ENTITY_MISMATCH"),
    ({"entity_id": "another-ship"}, {}, "STATE_ENTITY_MISMATCH"),
    ({"berth_id": "different-pier"}, {}, "STATE_FRAME_MISMATCH"),
    ({}, {"expected_entity_id": "different-owned-ship"}, "STATE_ENTITY_MISMATCH"),
    ({}, {"expected_entity": "tug"}, "STATE_ENTITY_MISMATCH"),
])
def test_caller_owned_entity_and_berth_frame_are_binding(update, context, code):
    rejects(code, observation(**update), **context)


def test_timestamp_sequence_duplicate_and_ordering_rejections_are_independent():
    previous = accept(observation(sequence=10))
    history = {("ship", "ownship"): previous}
    rejects("STATE_DUPLICATE", observation(sequence=10, observed_at_utc=NOW), previous_by_entity=history)
    rejects("STATE_OUT_OF_ORDER", observation(sequence=9, observed_at_utc=NOW), previous_by_entity=history)
    rejects("STATE_TIME_NOT_INCREASING", observation(sequence=11), previous_by_entity=history)
    rejects("STATE_TIME_NOT_INCREASING", observation(sequence=11, observed_at_utc=NOW-timedelta(seconds=3)),
            previous_by_entity=history)
    newer = accept(observation(sequence=11, observed_at_utc=NOW-timedelta(seconds=1)), previous_by_entity=history)
    assert newer.input.sequence == 11 and history == {("ship", "ownship"): previous}


def test_changing_source_does_not_bypass_duplicate_rejection():
    previous = accept()
    rejects("STATE_DUPLICATE", observation(source="sensor"), previous_by_entity={("ship", "ownship"): previous})


def test_sequences_are_independent_per_entity_including_different_tugs():
    ship = accept(observation(sequence=900))
    tug = accept(observation(entity="tug", entity_id="T1", sequence=500),
                 expected_entity="tug", expected_entity_id="T1")
    history = {("ship", "ownship"): ship, ("tug", "T1"): tug}
    second_tug = accept(observation(entity="tug", entity_id="T2", sequence=0),
        expected_entity="tug", expected_entity_id="T2", previous_by_entity=history)
    assert second_tug.input.sequence == 0 and len(history) == 2
    rejects("STATE_OUT_OF_ORDER", observation(entity="tug", entity_id="T1", sequence=1),
        expected_entity="tug", expected_entity_id="T1", previous_by_entity=history)


@pytest.mark.parametrize("bad_history", [
    {"session_id": "another-session"},
    {"input": observation(entity_id="different")},
    {"input": observation(berth_id="different")},
])
def test_history_cannot_cross_session_entity_or_frame_boundaries(bad_history):
    previous = accept().model_copy(update=bad_history)
    rejects("STATE_HISTORY_MISMATCH", previous_by_entity={("ship", "ownship"): previous})


@pytest.mark.parametrize("age,accepted", [(0, True), (30, True), (30.000001, False), (-.000001, False)])
def test_default_age_and_future_boundaries_use_the_injected_clock(age, accepted):
    req = observation(observed_at_utc=NOW-timedelta(seconds=age))
    if accepted:
        assert accept(req).age_s == age
    else:
        rejects("STATE_STALE" if age > 0 else "STATE_FUTURE", req)


def test_explicit_clock_skew_tolerance_keeps_negative_age_visible():
    req = observation(observed_at_utc=NOW+timedelta(seconds=1))
    rejects("STATE_FUTURE", req)
    r = accept(req, policy=MotionStatePolicy(future_tolerance_s=1))
    assert r.age_s == -1 and r.input.observed_at_utc > r.accepted_at_utc
    assert r.policy.future_tolerance_s == 1 and r.policy.max_age_s == 30
    assert any("clock-skew allowance" in line for line in r.limitations)


def test_recorded_history_needs_an_explicit_replay_clock_and_keeps_recorded_label():
    t = datetime(2020, 1, 1, tzinfo=UTC)
    req = observation(source="recorded", source_name="Historical test recording", observed_at_utc=t)
    rejects("STATE_STALE", req)
    r = accept(req, now_utc=t+timedelta(seconds=1))
    assert r.age_s == 1 and r.input.source == "recorded" and r.input.observed_at_utc == t
    assert any("not a live hardware stream" in line for line in r.limitations)


def test_quality_unknown_is_not_good_and_suspect_requires_explicit_policy():
    assert any("quality is unknown" in line for line in accept().limitations)
    rejects("STATE_QUALITY_INVALID", observation(quality="invalid"))
    rejects("STATE_QUALITY_SUSPECT", observation(quality="suspect"))
    accepted = accept(observation(quality="suspect"), policy=MotionStatePolicy(allow_suspect=True))
    assert accepted.input.quality == "suspect"
    assert any("Suspect quality" in line for line in accepted.limitations)


def test_nested_evidence_is_immutable_and_input_data_is_not_aliased():
    raw = observation(measured_acceleration={"surge_fps2": .5}).model_dump(mode="json")
    req = MotionStateInput.model_validate(raw)
    snapshot = accept(req)
    raw["measured_acceleration"]["surge_fps2"] = 99
    assert snapshot.input.measured_acceleration.surge_fps2 == .5
    assert snapshot.input is not req
    for obj, field, value in [(snapshot, "age_s", 9), (snapshot.input, "sequence", 9),
        (snapshot.state, "surge_fps", 9), (snapshot.input.measured_acceleration, "surge_fps2", 9)]:
        with pytest.raises(ValidationError, match="frozen"):
            setattr(obj, field, value)
    assert isinstance(snapshot.limitations, tuple)


@pytest.mark.parametrize("changes", [
    {"x_ft": float("nan")}, {"y_ft": float("inf")}, {"heading_true_deg": -1}, {"heading_true_deg": 360},
    {"surge_fps": None}, {"sway_fps": "1.2"}, {"surge_fps": True}, {"yaw_degps": 181}, {"surge_fps": 201},
    {"sequence": True}, {"sequence": "1"}, {"sequence": -1}, {"sequence": 2**53},
    {"x_ft": 1_000_001}, {"frame": "geographic"}, {"frame": "ship"}, {"source": "live"},
    {"entity_id": " "}, {"source_name": " "}, {"entity_id": "x"*121},
    {"observed_at_utc": NOW.replace(tzinfo=None)}, {"observed_at_utc": "2026-11-05T12:00:00"},
    {"observed_at_utc": 1_700_000_000}, {"observed_at_utc": None},
    {"measured_acceleration": {"surge_fps2": float("nan")}},
    {"measured_acceleration": {"surge_fps2": "1"}},
    {"measured_acceleration": {"surge_fps2": 101}},
    {"surge_kt": 1},
])
def test_input_rejects_unknown_nonfinite_unbounded_naive_and_ambiguous_values(changes):
    with pytest.raises(ValidationError):
        observation(**changes)


@pytest.mark.parametrize("field", ["frame", "berth_id", "entity_id", "observed_at_utc", "sequence",
                                   "x_ft", "y_ft", "heading_true_deg", "surge_fps", "sway_fps", "yaw_degps"])
def test_required_pose_velocity_and_identity_never_default_to_zero(field):
    raw = observation().model_dump()
    del raw[field]
    with pytest.raises(ValidationError):
        MotionStateInput.model_validate(raw)


@pytest.mark.parametrize("context", [
    {"face_bearing_true_deg": float("nan")}, {"face_bearing_true_deg": 360}, {"face_bearing_true_deg": True},
    {"simulation_time_s": float("inf")}, {"simulation_time_s": -.1}, {"simulation_time_s": 7201},
    {"simulation_time_s": True}, {"side_to": "unknown"}, {"session_id": " "}, {"run_id": ""},
])
def test_invalid_caller_context_fails_before_preparing_state(context):
    rejects("STATE_CONTEXT_INVALID", **context)


def test_injected_clock_must_be_aware():
    rejects("STATE_CLOCK_INVALID", now_utc=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("policy", [{"max_age_s": 0}, {"max_age_s": float("inf")}, {"max_age_s": 86401},
    {"future_tolerance_s": -1}, {"future_tolerance_s": 5.1}, {"allow_suspect": "yes"}])
def test_policy_is_explicit_finite_and_bounded(policy):
    with pytest.raises(ValidationError):
        MotionStatePolicy.model_validate(policy)


def test_model_copy_cannot_bypass_input_validation():
    bad = observation().model_copy(update={"surge_fps": float("nan")})
    with pytest.raises(ValidationError):
        accept(bad)
