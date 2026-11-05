"""A7 narration preserves immutable modeling evidence and never computes hazard decisions."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app as modeling_app
from mooring.core import access
from mooring.core.envelopes import RESULTS, new_id
from mooring.core.schemas.prediction import PredictionResponse
from mooring_agents.api import security
from mooring_agents.api.main import app, get_client
from mooring_agents.physics.client import ModelingClient, ModelingError
from mooring_agents.physics.toolkit import PhysicsToolkit
from mooring_agents.prediction.brief import explain


@pytest.fixture
def prediction():
    path = Path(__file__).resolve().parents[2] / "contract/examples/modeling/predict_trajectory_response.json"
    data = json.loads(path.read_text())
    data["result_id"] = new_id("res")
    return PredictionResponse.model_validate(data)


def test_brief_preserves_model_evidence_and_saved_age(prediction):
    before = prediction.model_dump(mode="json")
    brief = explain(prediction)
    assert brief.cites == [prediction.result_id]
    assert brief.validity == prediction.validity
    assert brief.manifest == prediction.manifest
    assert brief.warnings == prediction.warnings
    assert brief.assumptions == prediction.assumptions
    assert brief.input_age_s == prediction.result.input_age_s
    assert "saved assessment" in brief.summary
    assert "shoal/under-keel clearance" in brief.hazards_unavailable
    for alternative, described in zip(prediction.result.alternatives, brief.alternatives, strict=True):
        assert described.final_tick == alternative.ticks[-1]
        assert described.first_breach == alternative.first_breach
        assert described.closest_approach == alternative.closest_approach
        assert described.cites == brief.cites
        assert "calibrated" in described.uncertainty_note
    assert prediction.model_dump(mode="json") == before
    assert explain(prediction) == brief


def test_missing_hazards_and_corridor_stay_unknown(prediction):
    prediction.result.hazards_checked = []
    for alternative in prediction.result.alternatives:
        alternative.corridor = None
        alternative.first_breach = None
        alternative.closest_approach = None
    brief = explain(prediction)
    assert set(brief.hazards_unavailable) == {"pier", "fender", "coastline", "vessel", "shoal/under-keel clearance"}
    assert all("clearance is unknown" in alternative.explanation for alternative in brief.alternatives)
    assert all(not alternative.corridor_available and "unavailable" in alternative.uncertainty_note
               for alternative in brief.alternatives)


@pytest.mark.parametrize("validity", [None, {"state": "unknown", "reasons": []},
    {"state": "invalid", "reasons": [{"code": "UNSUPPORTED_INPUT", "message": "Unsupported inputs"}]}])
def test_unusable_results_do_not_narrate_clearance_or_trajectory(prediction, validity):
    data = prediction.model_dump(mode="json")
    data["status"] = "RED"
    data["validity"] = validity
    brief = explain(PredictionResponse.model_validate(data))
    for alternative in brief.alternatives:
        assert alternative.final_tick is None
        assert alternative.first_breach is None
        assert alternative.closest_approach is None
        assert not alternative.corridor_available
        assert "unavailable" in alternative.explanation


def test_zero_time_breach_and_zero_clearance_are_preserved(prediction):
    data = prediction.model_dump(mode="json")
    alternative = data["result"]["alternatives"][0]
    alternative["first_breach"] = {
        "t_s": 0, "kind": "pier", "element_id": "pier_contact", "clearance_ft": 0,
        "position": alternative["ticks"][0]["position"], "probability": None,
    }
    brief = explain(PredictionResponse.model_validate(data))
    described = brief.alternatives[0]
    assert described.first_breach.t_s == 0
    assert described.first_breach.clearance_ft == 0
    assert described.first_breach.probability is None
    assert "clearance-threshold breach at 0.0 s" in described.explanation


@pytest.mark.parametrize("sample_share", [0.0, 0.5, 1.0])
def test_sample_exceedance_is_not_hidden_by_a_clear_central_trajectory(prediction, sample_share):
    alternative = prediction.result.alternatives[0]
    assert alternative.closest_approach is not None
    assert alternative.corridor
    alternative.first_breach = None
    alternative.closest_approach.probability = sample_share
    before = prediction.model_dump(mode="json")
    described = explain(prediction).alternatives[0]
    assert "No clearance-threshold breach is reported on the central prediction" in described.explanation
    assert f"sample breach share of {sample_share} across checked hazards and sampled times" in described.explanation
    assert "uncalibrated sample share, not a collision probability" in described.explanation
    assert "not an all-clear indication" in described.explanation
    assert described.first_breach is None
    assert described.closest_approach.probability == sample_share
    assert described.cites == [prediction.result_id]
    assert prediction.model_dump(mode="json") == before


def test_endpoint_only_reads_saved_result_and_keeps_citation(monkeypatch, prediction):
    requests = []
    def respond(req):
        requests.append(req)
        return httpx.Response(200, json=prediction.model_dump(mode="json"))
    client = ModelingClient(transport=httpx.MockTransport(respond))
    monkeypatch.setitem(app.dependency_overrides, get_client, lambda: client)
    api = TestClient(app)
    path = f"/api/v1/predictions/{prediction.result_id}/brief"
    first, second = api.get(path), api.get(path)
    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    assert first.json()["cites"] == [prediction.result_id]
    assert all(req.method == "GET" and req.url.path == f"/api/v1/results/{prediction.result_id}" for req in requests)
    assert len(requests) == 2


@pytest.mark.parametrize("change", [{"result_id": "res_wrong"}, {"model": "different.model"}])
def test_wrong_prediction_identity_is_rejected_and_logged(prediction, change):
    data = {**prediction.model_dump(mode="json"), **change}
    tk = PhysicsToolkit(ModelingClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data))), "prediction")
    with pytest.raises(ModelingError) as error:
        asyncio.run(tk.prediction(prediction.result_id))
    assert error.value.status == 502
    assert tk.last_call.error == error.value.detail


def test_brief_uses_modeling_owner_auth_and_never_leaks_other_results(monkeypatch, prediction):
    keys = json.dumps({"alice": "a" * 32, "bob": "b" * 32})
    monkeypatch.setenv("MOORING_API_KEYS", keys)
    monkeypatch.setenv("AGENTS_API_KEYS", keys)
    monkeypatch.setenv("AGENTS_RATE_PER_MINUTE", "0")
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE", "0")
    token = access.principal.set("alice")
    try:
        RESULTS[prediction.result_id] = prediction.model_dump(mode="json")
    finally:
        access.principal.reset(token)
    monkeypatch.setitem(app.dependency_overrides, get_client, lambda: ModelingClient(
        base_url="http://modeling/api/v1", transport=httpx.ASGITransport(app=modeling_app),
        authorization=security.credential.get()))
    client = TestClient(app)
    path = f"/api/v1/predictions/{prediction.result_id}/brief"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer " + "b" * 32}).status_code == 404
    response = client.get(path, headers={"Authorization": "Bearer " + "a" * 32})
    assert response.status_code == 200, response.text
    assert response.json()["prediction_result_id"] == prediction.result_id
