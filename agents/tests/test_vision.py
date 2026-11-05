"""Real metadata/draft pipeline with a fake image model and in-process modeling API."""
import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from modeling_api.main import app
from mooring import refdata
from mooring_agents.physics.client import ModelingClient, ModelingError
from mooring_agents.physics.toolkit import PhysicsToolkit, calls_for
from mooring_agents.shared import llm
from mooring_agents.vision.agent import analyze
from mooring_agents.vision.schemas import VisionMetadata

# Valid tiny PNG; only transport/guardrails are tested, not model perception quality.
PNG=(Path(__file__).parent/'fixtures'/'berth-draft.png').read_bytes()
BERTH='NAVSTA-NORFOLK-P12-N'


def run(meta=None):
    tk=PhysicsToolkit(ModelingClient(base_url='http://modeling/api/v1',transport=httpx.ASGITransport(app=app)), 'vision')
    tk.plan_id='vision-test-'+str(id(tk))
    result=asyncio.run(analyze(PNG,'pier.png',meta or VisionMetadata(image_kind='satellite',berth_id=BERTH),tk))
    return result,tk


def test_no_llm_uses_metadata_catalog_and_does_not_claim_image_positions(monkeypatch):
    monkeypatch.setenv('AGENTS_LLM_PROVIDER','none')
    response,tk=run()
    assert response.backend=='real' and response.validity.state=='limited'
    assert response.result.extraction_source=='deterministic'
    assert all(d.needs_confirmation and d.bbox_px is None and d.confidence==0 for d in response.result.detections)
    assert response.result.geometry_result_id in {c.result_id for c in calls_for(tk.plan_id)}
    with pytest.raises(refdata.NotFound):refdata.berth(response.result.draft_berth.berth_id)


def test_optional_image_proposal_is_projected_by_modeling_and_always_unconfirmed(monkeypatch):
    kind=refdata.berth(BERTH).fittings[0].kind
    class Fake:
        async def chat(self,messages,**kwargs):
            assert messages[-1].images and base64.b64decode(messages[-1].images[0].data_base64)==PNG
            return llm.Reply(text=json.dumps({'detections':[dict(item_id='F1',kind=kind,center_px=[50,25],confidence=.99)]}),stop_reason='completed')
    monkeypatch.setattr(llm,'get_llm',lambda:Fake())
    response,_=run(VisionMetadata(image_kind='satellite',berth_id=BERTH,georef={'scale_ft_per_px':2},
        pier_face_start_px=(0,0),pier_face_end_px=(100,0)))
    assert response.result.extraction_source=='llm'
    assert response.result.draft_berth.fittings[0].x_ft==100
    assert response.result.detections[0].needs_confirmation
    assert response.result.draft_berth.provenance.confidence=='estimated'


def test_model_cannot_invent_capacity_and_invalid_proposal_falls_back(monkeypatch):
    class Fake:
        async def chat(self,*args,**kwargs):
            return llm.Reply(text=json.dumps({'detections':[dict(item_id='F1',kind='bollard',center_px=[50,25],confidence=1,capacity_lbf=1e20)]}),stop_reason='completed')
    monkeypatch.setattr(llm,'get_llm',lambda:Fake())
    response,_=run(VisionMetadata(image_kind='satellite',berth_id=BERTH,georef={'scale_ft_per_px':2},
        pier_face_start_px=(0,0),pier_face_end_px=(100,0)))
    assert response.result.extraction_source=='deterministic'
    assert 'unavailable' in response.result.extraction_note
    assert response.result.draft_berth.fittings==refdata.berth(BERTH).fittings


def test_responses_image_transport_is_structured_not_base64_in_plain_text():
    def handler(request):
        body=json.loads(request.content)
        content=body['input'][0]['content']
        assert content[0]=={'type':'input_text','text':'Inspect'}
        assert content[1]['type']=='input_image' and content[1]['image_url'].startswith('data:image/png;base64,')
        return httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{}'}]}]})
    provider=llm.OpenAIResponsesLLM('configured','fake',transport=httpx.MockTransport(handler))
    reply=asyncio.run(provider.chat([llm.Message(role='user',content='Inspect',images=[llm.ImageInput(media_type='image/png',data_base64=base64.b64encode(PNG).decode())])]))
    assert reply.text=='{}'
