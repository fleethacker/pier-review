"""S00a: agents must treat a modeling response without validity as unknown, and carry reported validity forward."""

import asyncio

import httpx
from fastapi.testclient import TestClient

from modeling_api.main import app as modeling_app
from mooring.core.schemas import AnalyzeResponse
from mooring.examples import EXAMPLES
from mooring_agents.physics.client import ModelingClient
from mooring_agents.physics.toolkit import PhysicsToolkit

P = "/api/v1"


def toolkit() -> PhysicsToolkit:
    return PhysicsToolkit(ModelingClient(base_url="http://modeling/api/v1", transport=httpx.ASGITransport(app=modeling_app)),
                          caller="test")


def _legacy_client():
    class Stub:
        """Gateway client returning an analysis recorded before S00a (no validity, no manifest)."""

        async def request(self, method, path, **kw):
            j = TestClient(modeling_app).post(f"{P}{path}", json=kw["json"]).json()
            j.pop("validity"), j.pop("manifest")
            return AnalyzeResponse.model_validate(j).model_dump(mode="json")

    return Stub()


def test_legacy_modeling_response_is_recorded_as_unknown():
    tk = toolkit()

    tk.client = _legacy_client()
    out = asyncio.run(tk.analyze(EXAMPLES["mooring_analyze"]))
    assert out.validity is None
    assert tk.last_call.validity_state == "unknown" and tk.last_call.status in ("GREEN", "AMBER", "RED")


def test_new_modeling_response_validity_is_recorded():
    tk = toolkit()
    out = asyncio.run(tk.analyze(EXAMPLES["mooring_analyze"]))
    assert out.validity.state == "limited" and tk.last_call.validity_state == "limited"


def test_reported_invalid_validity_reaches_the_ledger():
    tk = toolkit()

    class Stub:
        """Modeling client whose responses report invalid validity (the gateway calls the generic request())."""

        async def request(self, method, path, **kw):
            j = TestClient(modeling_app).post(f"{P}{path}", json=kw["json"]).json()
            j["status"] = "RED"
            j["validity"] = {"state": "invalid", "reasons": [{"code": "NO_EQUILIBRIUM_FOUND", "message": "solver stalled"}]}
            return AnalyzeResponse.model_validate(j).model_dump(mode="json")

    tk.client = Stub()
    out = asyncio.run(tk.analyze(EXAMPLES["mooring_analyze"]))
    assert out.validity.state == "invalid" and tk.last_call.validity_state == "invalid"


def test_modeling_422_on_conflicting_inputs_surfaces_as_error():
    tk = toolkit()
    body = EXAMPLES["mooring_analyze"] | {"scenario_id": "scn_missing"}
    try:
        asyncio.run(tk.analyze(body))
    except Exception as e:  # ModelingError
        assert getattr(e, "status", None) == 422
    else:
        raise AssertionError("expected a 422")
    assert tk.last_call.error and tk.last_call.validity_state == "unknown"


def test_sequence_review_status_reaches_the_safety_sheet():
    from mooring_agents.safety.sheet import render_html
    from mooring.core.schemas import SequenceResult
    from mooring_agents.safety import schemas as S
    seq = SequenceResult(steps=[], crews_required=4, review_status="draft_unreviewed", limitations=["Static check only."])
    assert seq.review_status == "draft_unreviewed"
    assert "sequence_review_status" in S.SafetySheet.model_fields and "sequence_limitations" in S.SafetySheet.model_fields


def test_unknown_ledger_validity_is_omitted_for_legacy_clients():
    from pydantic import ConfigDict, create_model
    from mooring_agents.physics.schemas import ToolCall

    LegacyCall = create_model("LegacyCall", __config__=ConfigDict(extra="forbid"),
                              **{name: (field.annotation, field) for name, field in ToolCall.model_fields.items()
                                 if name != "validity_state"})
    tk = toolkit()
    tk.client = _legacy_client()
    asyncio.run(tk.analyze(EXAMPLES["mooring_analyze"]))
    wire = tk.last_call.model_dump(mode="json")
    assert "validity_state" not in wire
    LegacyCall.model_validate(wire)
    assert ToolCall.model_validate(wire).validity_state == "unknown"
    tk.last_call.validity_state = "invalid"
    assert tk.last_call.model_dump(mode="json")["validity_state"] == "invalid"
