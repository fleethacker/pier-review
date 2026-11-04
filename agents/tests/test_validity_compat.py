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


def test_legacy_modeling_response_is_recorded_as_unknown():
    tk = toolkit()

    class Stub:
        async def analyze(self, body):
            j = TestClient(modeling_app).post(f"{P}/mooring/analyze", json=body).json()
            j.pop("validity"), j.pop("manifest")  # a response recorded before S00a
            return AnalyzeResponse.model_validate(j)

    tk.client = Stub()
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
        async def analyze(self, body):
            j = TestClient(modeling_app).post(f"{P}/mooring/analyze", json=body).json()
            j["status"] = "RED"
            j["validity"] = {"state": "invalid", "reasons": [{"code": "NO_EQUILIBRIUM_FOUND", "message": "solver stalled"}]}
            return AnalyzeResponse.model_validate(j)

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
