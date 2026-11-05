"""Real metadata/draft pipeline with a fake image model and in-process modeling API."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import uuid

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


@pytest.fixture(autouse=True)
def offline_image_providers(monkeypatch):
    monkeypatch.setenv('AGENTS_LLM_PROVIDER', 'none')
    monkeypatch.delenv('BOLLARD_MODEL_PATH', raising=False)


def run(meta=None):
    tk=PhysicsToolkit(ModelingClient(base_url='http://modeling/api/v1',transport=httpx.ASGITransport(app=app)), 'vision')
    tk.plan_id='vision-test-'+uuid.uuid4().hex
    result=asyncio.run(analyze(PNG,'pier.png',meta or VisionMetadata(image_kind='satellite',berth_id=BERTH),tk))
    return result,tk


def test_no_llm_uses_metadata_catalog_and_does_not_claim_image_positions(monkeypatch):
    monkeypatch.setenv('AGENTS_LLM_PROVIDER','none')
    response,tk=run()
    assert response.backend=='real' and response.validity.state=='limited'
    assert response.result.extraction_source=='deterministic'
    assert 'no image features were extracted' in response.result.extraction_note
    assert response.result.image_sha256 == hashlib.sha256(PNG).hexdigest()
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


def test_trained_detector_proposals_are_projected_boxed_and_unconfirmed(monkeypatch):
    from mooring.core.schemas.berth_drafts import ImageFitting
    from mooring_agents.vision import detector
    kind=refdata.berth(BERTH).fittings[0].kind
    class FakeDet:
        version='fake.pt'
        async def detect_async(self,image):
            return [(ImageFitting(item_id='DET1',kind=kind,center_px=(50,25),confidence=.8),(40,15,20,20)),
                    (ImageFitting(item_id='DET2',kind='not-in-catalog',center_px=(10,10),confidence=.9),(0,0,5,5))]
    monkeypatch.setattr(detector,'get_detector',lambda:FakeDet())
    response,_=run(VisionMetadata(image_kind='satellite',berth_id=BERTH,georef={'scale_ft_per_px':2},
        pier_face_start_px=(0,0),pier_face_end_px=(100,0)))
    assert response.result.extraction_source=='detector'
    assert [d.bbox_px for d in response.result.detections]==[(40,15,20,20)]
    assert all(d.needs_confirmation for d in response.result.detections)
    assert response.result.draft_berth.fittings[0].x_ft==100


def test_detector_failure_falls_back_to_catalog(monkeypatch):
    from mooring_agents.vision import detector
    monkeypatch.setenv('AGENTS_LLM_PROVIDER','none')
    class Boom:
        version='x'
        async def detect_async(self,image): raise RuntimeError('boom')
    monkeypatch.setattr(detector,'get_detector',lambda:Boom())
    response,_=run(VisionMetadata(image_kind='satellite',berth_id=BERTH,georef={'scale_ft_per_px':2},
        pier_face_start_px=(0,0),pier_face_end_px=(100,0)))
    assert response.result.extraction_source=='deterministic'


@pytest.mark.parametrize('failure', ['duplicate_ids', 'empty', 'outside_image', 'incomplete', 'tool_call', 'provider_error'])
def test_unusable_image_proposals_keep_honest_catalog_geometry(monkeypatch, failure):
    kind = refdata.berth(BERTH).fittings[0].kind
    fitting = dict(item_id='F1', kind=kind, center_px=[50, 25], confidence=.99)
    proposals = [fitting, fitting] if failure == 'duplicate_ids' else [fitting]
    if failure == 'empty':
        proposals = []
    elif failure == 'outside_image':
        proposals[0]['center_px'] = [99999, 25]

    class Fake:
        async def chat(self, *args, **kwargs):
            if failure == 'provider_error':
                raise llm.LLMError('fixture provider failure')
            return llm.Reply(text=json.dumps({'detections': proposals}),
                stop_reason='max_tokens' if failure == 'incomplete' else 'completed',
                tool_uses=[llm.ToolUse(id='untrusted', name='save_berth', arguments={})]
                if failure == 'tool_call' else [])

    monkeypatch.setattr(llm, 'get_llm', lambda: Fake())
    response, tk = run(VisionMetadata(image_kind='satellite', berth_id=BERTH,
        georef={'scale_ft_per_px': 2}, pier_face_start_px=(0, 0), pier_face_end_px=(100, 0)))
    assert response.result.extraction_source == 'deterministic'
    assert 'retained catalog draft' in response.result.extraction_note
    assert response.result.draft_berth.fittings == refdata.berth(BERTH).fittings
    assert response.status == 'AMBER' and response.validity.state == 'limited'
    assert all(d.needs_confirmation and d.confidence == 0 and d.center_px is None
               and d.bbox_px is None for d in response.result.detections)
    assert {call.tool for call in calls_for(tk.plan_id)} == {'get_berth', 'draft_berth'}
    with pytest.raises(refdata.NotFound):
        refdata.berth(response.result.draft_berth.berth_id)


@pytest.mark.parametrize('failure', ['duplicate_ids', 'empty', 'too_many'])
def test_unusable_detector_proposals_fall_back_without_claiming_extraction(monkeypatch, failure):
    from mooring.core.schemas.berth_drafts import ImageFitting
    from mooring_agents.vision import detector
    kind = refdata.berth(BERTH).fittings[0].kind

    class FakeDet:
        version = 'fixture'
        async def detect_async(self, image):
            ids = ['duplicate', 'duplicate'] if failure == 'duplicate_ids' else (
                [f'F{i}' for i in range(101)] if failure == 'too_many' else [])
            return [(ImageFitting(item_id=item_id, kind=kind, center_px=(50, 25), confidence=.8),
                     (40, 15, 20, 20)) for item_id in ids]

    monkeypatch.setattr(detector, 'get_detector', lambda: FakeDet())
    response, _ = run(VisionMetadata(image_kind='satellite', berth_id=BERTH,
        georef={'scale_ft_per_px': 2}, pier_face_start_px=(0, 0), pier_face_end_px=(100, 0)))
    assert response.result.extraction_source == 'deterministic'
    assert response.result.draft_berth.fittings == refdata.berth(BERTH).fittings
    assert all(d.center_px is None and d.bbox_px is None and d.confidence == 0
               and d.needs_confirmation for d in response.result.detections)


def test_empty_detector_can_use_valid_llm_proposal(monkeypatch):
    from mooring_agents.vision import detector
    kind = refdata.berth(BERTH).fittings[0].kind

    class EmptyDetector:
        version = 'fixture'
        async def detect_async(self, image):
            return []

    class Fake:
        async def chat(self, *args, **kwargs):
            return llm.Reply(text=json.dumps({'detections': [dict(item_id='F1', kind=kind,
                center_px=[50, 25], confidence=.9)]}), stop_reason='completed')

    monkeypatch.setattr(detector, 'get_detector', lambda: EmptyDetector())
    monkeypatch.setattr(llm, 'get_llm', lambda: Fake())
    response, _ = run(VisionMetadata(image_kind='satellite', berth_id=BERTH,
        georef={'scale_ft_per_px': 2}, pier_face_start_px=(0, 0), pier_face_end_px=(100, 0)))
    assert response.result.extraction_source == 'llm'
    assert [d.item_id for d in response.result.detections] == ['F1']
    assert response.result.detections[0].needs_confirmation
