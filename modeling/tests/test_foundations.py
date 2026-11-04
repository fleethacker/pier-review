"""S00a: validity, diagnostics, input semantics, environment metadata, manifest and legacy compatibility.

Deterministic: no clock, network or randomness beyond fixed fixtures.
"""

import copy
import json
import math
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from modeling_api.main import app
from mooring.core.envelopes import (
    envelope, inputs_hash, resolved_inputs_hash, status_with_validity, validity_state,
)
from mooring.core.schemas import (
    AnalyzeRequest, AnalyzeResponse, EnvironmentMetadata, EnvironmentSnapshot, EnvScenarioCreate,
    LoadsResponse, MooringLine, ResultManifest, SolverDiagnostics, SolverResidual, Validity, ValidityReason,
)
from mooring.core.schemas.common import Envelope
from mooring.examples import EXAMPLES

P = "/api/v1"
client = TestClient(app)
T = datetime(2026, 11, 4, 15, 48, tzinfo=UTC)
REASON = ValidityReason(code="MISSING_FITTING_RATING", message="No rating for P12N-B16", affected_components=["P12N-B16"])


def body() -> dict:
    return copy.deepcopy(EXAMPLES["mooring_analyze"])


# ---------- Validity and envelope invariants ----------

def test_limited_and_invalid_need_reasons():
    with pytest.raises(ValidationError, match="needs at least one reason"):
        Validity(state="invalid")
    with pytest.raises(ValidationError, match="needs at least one reason"):
        Validity(state="limited")
    assert Validity(state="valid").reasons == [] and Validity(state="unknown").reasons == []


def test_reason_code_format_is_enforced():
    with pytest.raises(ValidationError):
        ValidityReason(code="not snake", message="x")


def envelope_dict(**extra) -> dict:
    return {"result_id": "res_1", "model": "m", "model_version": "1", "backend": "real", "inputs_hash": "sha256:0",
            "computed_at_utc": T.isoformat(), "status": "GREEN", "result": {}, **extra}


@pytest.mark.parametrize("state,status,ok", [
    ("invalid", "GREEN", False), ("invalid", "AMBER", False), ("invalid", "RED", True),
    ("limited", "GREEN", False), ("limited", "AMBER", True), ("limited", "RED", True),
    ("valid", "GREEN", True), ("unknown", "GREEN", True),
])
def test_status_must_agree_with_validity(state, status, ok):
    validity = {"state": state, "reasons": [REASON.model_dump()] if state in ("limited", "invalid") else []}
    payload = envelope_dict(status=status, validity=validity)
    if ok:
        assert Envelope[dict].model_validate(payload).validity.state == state
    else:
        with pytest.raises(ValidationError):
            Envelope[dict].model_validate(payload)


def test_status_with_validity_lifts_status_without_lowering_it():
    inv = Validity(state="invalid", reasons=[REASON])
    lim = Validity(state="limited", reasons=[REASON])
    assert status_with_validity("GREEN", inv) == "RED"
    assert status_with_validity("GREEN", lim) == "AMBER"
    assert status_with_validity("RED", lim) == "RED"
    assert status_with_validity("GREEN", Validity(state="valid")) == "GREEN"
    assert status_with_validity("GREEN", None) == "GREEN"


def test_envelope_helper_lifts_status_and_stores_validity():
    env = envelope(AnalyzeResponse, model="t", request=None, result=_analyze_result(), status="GREEN",
                   validity=Validity(state="invalid", reasons=[REASON]))
    assert env.status == "RED" and env.validity.reasons[0].code == "MISSING_FITTING_RATING"


def _analyze_result():
    return AnalyzeResponse.model_validate(client.post(f"{P}/mooring/analyze", json=body()).json()).result


def test_diagnostics_hold_residuals_and_reject_impossible_rank():
    d = SolverDiagnostics(converged=True, iterations=7, degrees_of_freedom=3, rank=3, active_constraints=["fender-1"],
                          residuals=[SolverResidual(name="surge_force", value=12.0, unit="lbf", tolerance=50.0),
                                     SolverResidual(name="yaw_moment", value=-2e3, unit="ftlbf", tolerance=1e3)])
    assert [r.within_tolerance for r in d.residuals] == [True, False]
    assert SolverDiagnostics().converged is None  # unknown, not False
    with pytest.raises(ValidationError, match="rank cannot exceed"):
        SolverDiagnostics(rank=4, degrees_of_freedom=3)
    with pytest.raises(ValidationError):
        SolverResidual(name="x", value=1, unit="lbf", tolerance=0)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nan_and_infinity_are_rejected_everywhere(bad):
    with pytest.raises(ValidationError):
        SolverResidual(name="x", value=bad, unit="lbf", tolerance=1)
    with pytest.raises(ValidationError):
        EnvironmentSnapshot(wind_speed_kt=bad, wind_gust_kt=1, wind_from_true_deg=0, current_speed_kt=0,
                            current_set_true_deg=0, water_level_mllw_ft=0)
    b = body()
    b["environment"]["water_level_mllw_ft"] = bad
    with pytest.raises(ValidationError):
        AnalyzeRequest(**b)


# ---------- Legacy compatibility: absence means unknown ----------

def test_current_responses_have_no_validity_and_read_as_unknown():
    r = client.post(f"{P}/mooring/analyze", json=body())
    assert r.status_code == 200
    j = r.json()
    assert j["validity"] is None and j["manifest"] is None
    assert validity_state(j) == "unknown"
    assert validity_state(AnalyzeResponse.model_validate(j)) == "unknown"
    stored = client.get(f"{P}/results/{j['result_id']}").json()
    assert validity_state(stored) == "unknown"


def test_real_loads_response_reports_validity_but_mock_analysis_stays_unknown():
    j = client.post(f"{P}/loads/environmental", json=EXAMPLES["loads_environmental"]).json()
    assert LoadsResponse.model_validate(j).validity is not None and validity_state(j) in ("valid", "limited")


def test_pre_s00a_payloads_still_parse():
    """A response recorded before validity/manifest/metadata existed must validate unchanged."""
    j = client.post(f"{P}/mooring/analyze", json=body()).json()
    legacy = {k: v for k, v in j.items() if k not in ("validity", "manifest")}
    assert "validity" not in legacy
    parsed = AnalyzeResponse.model_validate(legacy)
    assert parsed.validity is None and parsed.manifest is None and validity_state(parsed) == "unknown"
    # Legacy environment bodies (no metadata) round-trip too.
    assert "metadata" not in legacy["result"] and EnvironmentSnapshot(**EXAMPLES["loads_environmental"]["environment"]).metadata is None


def test_every_example_body_still_validates():
    for name in ("mooring_analyze", "mooring_envelope", "mooring_tide_sweep", "risk_exceedance", "risk_timeline",
                 "tugs_hold_plan", "scenario", "env_scenario", "loads_environmental"):
        r = client.post(f"{P}/{_PATH[name]}", json=EXAMPLES[name])
        assert r.status_code in (200, 201, 202), (name, r.text)


_PATH = {"mooring_analyze": "mooring/analyze", "mooring_envelope": "mooring/envelope",
         "mooring_tide_sweep": "mooring/tide-sweep", "risk_exceedance": "risk/exceedance",
         "risk_timeline": "risk/timeline", "tugs_hold_plan": "tugs/hold-plan", "scenario": "scenarios",
         "env_scenario": "env/scenarios", "loads_environmental": "loads/environmental"}


def test_adding_metadata_does_not_change_numbers():
    base = client.post(f"{P}/mooring/analyze", json=body()).json()["result"]
    b = body()
    b["environment"]["metadata"] = {"basis": "scenario", "source": "unit test", "wind_averaging_s": 60,
                                    "gust_duration_s": 3, "wind_reference_height_m": 10, "vertical_datum": "MLLW"}
    r = client.post(f"{P}/mooring/analyze", json=b)
    assert r.status_code == 200, r.text
    assert r.json()["result"] == base
    assert r.json()["inputs_hash"] != client.post(f"{P}/mooring/analyze", json=body()).json()["inputs_hash"]


# ---------- Hashes and manifest ----------

def test_inputs_hash_meaning_is_unchanged():
    # Golden values: the request-as-sent hash must not drift (agents' ledger and stored results depend on it).
    assert inputs_hash(None) == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert inputs_hash({"a": 1, "b": [2, 3]}) == "sha256:" + __import__("hashlib").sha256(b'{"a": 1, "b": [2, 3]}').hexdigest()


def test_resolved_inputs_hash_is_canonical_and_separate():
    a, b = {"x": 1, "y": {"p": 2, "q": 3}}, {"y": {"q": 3, "p": 2}, "x": 1}
    assert resolved_inputs_hash(a) == resolved_inputs_hash(b)
    assert resolved_inputs_hash(a) != resolved_inputs_hash({**a, "x": 2})
    assert resolved_inputs_hash(a) != inputs_hash(a)
    with pytest.raises(ValueError):
        resolved_inputs_hash({"x": math.nan})


def test_manifest_round_trips_through_an_envelope():
    m = ResultManifest(resolved_inputs_hash=resolved_inputs_hash({"x": 1}), code_version="s00a",
                       records=[{"kind": "ship", "id": "DDG-51-FIIA", "revision": "abc"}],
                       numerical_settings={"tol_lbf": 50.0, "max_iter": 100}, rng_seed=42, rng_model_revision="r1")
    env = envelope(AnalyzeResponse, model="t", request=None, result=_analyze_result(), status="GREEN", manifest=m)
    again = AnalyzeResponse.model_validate(json.loads(env.model_dump_json()))
    assert again.manifest == m and validity_state(again) == "unknown"


# ---------- Environment metadata ----------

def meta(**kw) -> dict:
    return {"basis": "prediction", **kw}


@pytest.mark.parametrize("kw,msg", [
    (dict(valid_from_utc=T, valid_to_utc=datetime(2026, 11, 4, tzinfo=UTC)), "before valid_from"),
    (dict(wind_averaging_s=60, gust_duration_s=60), "shorter than"),
    (dict(basis="observation"), "needs age_s or issued_at_utc"),
    (dict(vertical_datum="NAVD88"), "relative to MLLW"),
])
def test_invalid_environment_metadata(kw, msg):
    with pytest.raises(ValidationError, match=msg):
        EnvironmentMetadata(**meta(**kw))


def test_valid_environment_metadata_keeps_originals():
    m = EnvironmentMetadata(basis="observation", source="NOAA CO-OPS 8638610", age_s=240, wind_averaging_s=60,
                            gust_duration_s=5, wind_reference_height_m=10, current_depth_ft=6.5, current_bin="3",
                            vertical_datum="MLLW", quality="good", original={"wind_speed_m_s": 11.3, "flags": "0,0,0"})
    assert m.original["wind_speed_m_s"] == 11.3


# ---------- Conflicting and invalid inputs ----------

def post(path, b):
    return client.post(f"{P}/{path}", json=b)


def test_conflicting_pretension_and_slack_rejected_with_422():
    b = body()
    b["config"]["lines"][0].update(pretension_lbf=5000, slack_ft=3)
    r = post("mooring/analyze", b)
    assert r.status_code == 422 and "pretension_lbf and slack_ft conflict" in r.text


def test_legacy_line_defaults_unchanged():
    ln = MooringLine(line_number=1, spec_id="NYLON-DB-7IN", ship_fitting_id="a", pier_fitting_id="b",
                     pretension_lbf=0, slack_ft=2)  # zero pretension on a slack line is consistent
    assert ln.condition is None and ln.paid_out_unstretched_length_ft is None
    with pytest.raises(ValidationError, match="both define line length"):
        MooringLine(line_number=1, spec_id="s", ship_fitting_id="a", pier_fitting_id="b",
                    paid_out_unstretched_length_ft=100, slack_ft=2)


def test_unmodelled_line_fields_are_labeled_not_silently_ignored():
    b = body()
    b["config"]["lines"][0].update(paid_out_unstretched_length_ft=120.0, condition="dry")
    j = post("mooring/analyze", b).json()
    text = " ".join(j["assumptions"])
    assert "paid_out_unstretched_length_ft is ignored" in text and "condition 'dry' is ignored" in text
    assert j["result"] == client.post(f"{P}/mooring/analyze", json=body()).json()["result"]


def test_unknown_scenario_id_is_422_not_404():
    b = body() | {"scenario_id": "scn_does_not_exist"}
    r = post("mooring/analyze", b)
    assert r.status_code == 422 and "does not exist" in r.text


def test_scenario_id_conflicting_with_body_lists_every_conflict():
    sid = post("scenarios", EXAMPLES["scenario"]).json()["scenario_id"]
    b = body() | {"scenario_id": sid, "ship_class_id": "CG-47", "loading": "light"}
    r = post("mooring/analyze", b)
    assert r.status_code == 422
    assert "ship_class_id='CG-47'" in r.text and "loading='light'" in r.text and "berth_id" not in r.text


def test_matching_scenario_id_and_edited_config_are_accepted():
    sid = post("scenarios", EXAMPLES["scenario"]).json()["scenario_id"]
    b = body() | {"scenario_id": sid}
    b["config"]["lines"] = b["config"]["lines"][:-1]  # a canvas edit is not a conflict
    assert post("mooring/analyze", b).status_code == 200
    for path, ex in (("mooring/envelope", "mooring_envelope"), ("mooring/tide-sweep", "mooring_tide_sweep")):
        assert post(path, copy.deepcopy(EXAMPLES[ex]) | {"scenario_id": "scn_missing"}).status_code == 422


def test_scenario_side_to_conflict_with_its_config():
    s = copy.deepcopy(EXAMPLES["scenario"])
    s["side_to"] = "port"
    r = post("scenarios", s)
    assert r.status_code == 422 and "conflicts with config.side_to" in r.text


@pytest.mark.parametrize("src", [{"mode": "scenario"}, {"mode": "live", "env_scenario_id": "envsc_x"}])
def test_env_source_mode_and_id_must_agree(src):
    s = copy.deepcopy(EXAMPLES["scenario"]) | {"env_source": src}
    assert post("scenarios", s).status_code == 422


def test_relative_bearing_conflict_is_422_and_agreement_is_accepted():
    b = body()
    heading = client.get(f"{P}/berths/{b['berth_id']}").json()["face_bearing_true_deg"]  # starboard side to
    env = b["environment"]
    good = (env["wind_from_true_deg"] - heading) % 360
    b["environment"]["wind_rel_ship_deg"] = good
    assert post("mooring/analyze", b).status_code == 200
    b["environment"]["wind_rel_ship_deg"] = (good + 40) % 360
    r = post("mooring/analyze", b)
    assert r.status_code == 422 and "wind_rel_ship_deg" in r.text
    ld = copy.deepcopy(EXAMPLES["loads_environmental"])
    ld["environment"]["current_rel_ship_deg"] = (ld["environment"]["current_set_true_deg"] - ld["heading_true_deg"] + 90) % 360
    assert post("loads/environmental", ld).status_code == 422


def test_relative_bearing_wraparound_is_not_a_conflict():
    ld = copy.deepcopy(EXAMPLES["loads_environmental"])
    ld["environment"]["wind_from_true_deg"] = 359.9
    ld["heading_true_deg"] = 0.2
    ld["environment"]["wind_rel_ship_deg"] = 359.7
    assert post("loads/environmental", ld).status_code == 200


def _json(kw: dict) -> dict:
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in kw.items()}


@pytest.mark.parametrize("kw", [
    dict(kind="ramp"), dict(kind="steady", ramp_minutes=5), dict(kind="steady", replay_start_utc=T),
    dict(kind="replay"), dict(kind="replay", replay_start_utc=T, replay_end_utc=T),
    dict(kind="steady", wind_speed_kt=20, wind_gust_kt=10),
])
def test_env_scenario_inconsistent_fields_rejected(kw):
    with pytest.raises(ValidationError):
        EnvScenarioCreate(name="x", **kw)
    assert post("env/scenarios", {"name": "x", **_json(kw)}).status_code == 422


def test_env_scenario_consistent_forms_accepted():
    for kw in (dict(kind="ramp", wind_speed_kt=10, ramp_to_wind_kt=30, ramp_minutes=10),
               dict(kind="replay", replay_start_utc=T), dict(kind="steady", wind_speed_kt=10, wind_gust_kt=15)):
        assert post("env/scenarios", {"name": "x", **_json(kw)}).status_code == 201


def test_non_finite_json_in_a_request_is_422():
    r = client.post(f"{P}/mooring/analyze", content=json.dumps(body()).replace('"water_level_mllw_ft": 1.8', '"water_level_mllw_ft": Infinity'),
                    headers={"content-type": "application/json"})
    assert r.status_code == 422

