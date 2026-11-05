"""Human-confirmed berth drafting through logged modeling tools; optional image proposals."""
import asyncio
import base64
import hashlib
import json
import struct
from importlib.resources import files

from pydantic import Field

from mooring.core.envelopes import envelope
from mooring.core.schemas import Model, Validity, ValidityReason
from mooring.core.schemas.berth_drafts import ImageFitting, BerthDraftRequest

from ..physics.client import ModelingError
from ..physics.toolkit import PhysicsToolkit
from ..shared import llm
from . import detector as bollard_detector
from .schemas import Detection, VisionMetadata, VisionResponse, VisionResult

DEMO_TEMPLATE = 'NAVSTA-NORFOLK-P12-N'
MAX_IMAGE_BYTES = 8_000_000


class ImageProposal(Model):
    detections: list[ImageFitting] = Field(max_length=100)


def image_type(image: bytes):
    if image.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if image.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if image[:4] == b'RIFF' and image[8:12] == b'WEBP': return 'image/webp'
    return None


async def analyze(image: bytes, filename: str, meta: VisionMetadata, tk: PhysicsToolkit) -> VisionResponse:
    if not image or len(image) > MAX_IMAGE_BYTES:
        raise ModelingError(422, 'Supply a nonempty image no larger than 8 MB')
    source = await tk.berth(meta.berth_id or DEMO_TEMPLATE)
    detections, mode = [], 'deterministic'
    note = 'Catalog geometry used; no image features were extracted.'
    anchors = (meta.pier_face_start_px is not None and meta.pier_face_end_px is not None
               and meta.georef is not None and meta.georef.scale_ft_per_px is not None)
    media_type = image_type(image)
    dimensions = struct.unpack('>II', image[16:24]) if media_type == 'image/png' and len(image) >= 24 else None
    if anchors and dimensions:
        if any(not 0 <= point[0] <= dimensions[0] or not 0 <= point[1] <= dimensions[1]
               for point in (meta.pier_face_start_px, meta.pier_face_end_px)):
            raise ModelingError(422, 'Pier-face anchors fall outside the image')
    boxes = {}
    try:
        det = bollard_detector.get_detector() if anchors and media_type else None
    except bollard_detector.DetectorUnavailable as exc:
        det, note = None, f'Trained bollard detector unavailable ({exc}); retained catalog draft.'
    if det is not None:
        try:
            found = [(f, b) for f, b in await det.detect_async(image) if f.kind in {s.kind for s in source.fittings}]
            if dimensions and any(not 0 <= f.center_px[0] <= dimensions[0] or not 0 <= f.center_px[1] <= dimensions[1] for f, _ in found):
                raise ValueError('Detected pixel center is outside the image')
            detections, boxes = [f for f, _ in found], {f.item_id: b for f, b in found}
            mode = 'detector'
            note = (f'Trained detector {det.version} proposed {len(detections)} bollards; projected with supplied anchors, '
                    'all require confirmation. Detector accuracy on berth imagery is not established.')
        except Exception:
            detections, boxes, mode, note = [], {}, 'deterministic', 'Bollard detector failed; retained catalog draft.'
    try:
        provider = llm.get_llm() if mode == 'deterministic' else None
    except llm.LLMNotConfigured:
        provider = None
    if provider is not None and anchors and media_type:
        try:
            reply = await asyncio.wait_for(provider.chat([
                llm.Message(role='system', content=files(__package__).joinpath('prompts/extract.txt').read_text()),
                llm.Message(role='user', content=json.dumps({
                    'allowed_kinds': sorted({f.kind for f in source.fittings}),
                    'response_schema': ImageProposal.model_json_schema(),
                    'metadata': meta.model_dump(mode='json'),
                }), images=[llm.ImageInput(media_type=media_type, data_base64=base64.b64encode(image).decode())]),
            ], max_tokens=4096), timeout=30)
            if reply.stop_reason not in ('completed', 'stop', 'end_turn') or reply.tool_uses:
                raise ValueError('Incomplete image proposal')
            detections = ImageProposal.model_validate_json(reply.text).detections
            if dimensions and any(not 0 <= d.center_px[0] <= dimensions[0] or not 0 <= d.center_px[1] <= dimensions[1] for d in detections):
                raise ValueError('Detected pixel center is outside the image')
            mode, note = 'llm', 'Unverified image proposals projected with supplied anchors; all require confirmation.'
        except Exception:
            detections, mode, note = [], 'deterministic', 'Image provider or proposal unavailable; retained catalog draft.'
    elif provider is not None:
        note = 'Image extraction unavailable without a supported image, scale and two pier-face anchors; retained catalog draft.'
    request = {'source_berth_id':source.berth_id, 'name':meta.berth_name or f'Draft from {filename}',
               'image_fittings':[d.model_dump(mode='json') for d in detections],
               'scale_ft_per_px':meta.georef.scale_ft_per_px if meta.georef else None,
               'pier_face_start_px':meta.pier_face_start_px, 'pier_face_end_px':meta.pier_face_end_px}
    request = BerthDraftRequest(**request).model_dump(mode="json")
    try:
        geometry = await tk.draft_berth(request)
    except ModelingError as exc:
        if not detections or exc.status != 422:
            raise
        request['image_fittings'] = []
        detections, boxes, mode, note = [], {}, 'deterministic', 'Image geometry rejected by modeling; retained catalog draft.'
        geometry = await tk.draft_berth(request)
    draft = geometry.result.draft_berth
    annotations = [Detection(item_id=d.item_id, kind=d.kind, bbox_px=boxes.get(d.item_id), center_px=d.center_px,
                             confidence=d.confidence, needs_confirmation=True) for d in detections]
    if not annotations:
        annotations = [Detection(item_id=f.fitting_id, kind=f.kind, bbox_px=None,
                                 confidence=0, needs_confirmation=True) for f in draft.fittings]
    questions = list(geometry.result.notes)
    if meta.berth_id is None:
        questions.insert(0, 'No berth id supplied: this is the Norfolk demo template, not the location inferred from the image. Select/confirm the actual berth.')
    recommended = None
    recommendation_id = None
    if meta.ship_class_id and not detections:
        recommendation = await tk.recommend({'ship_class_id':meta.ship_class_id, 'berth_id':source.berth_id,
            'side_to':meta.side_to or 'starboard', 'max_candidates':1})
        recommendation_id = recommendation.result_id
        recommended = recommendation.result.candidates[0].config if recommendation.result.candidates else None
        questions.append('Recommended line layout is a catalog preview, not an approved plan. Reanalyze the confirmed berth before use.')
    elif meta.ship_class_id:
        questions.append('Changed image geometry needs confirmation before line search; request recommendation after the berth is registered.')
    result = VisionResult(draft_berth=draft, detections=annotations, recommended_config=recommended,
        questions=questions, recommendation_result_id=recommendation_id, extraction_source=mode, extraction_note=note, geometry_result_id=geometry.result_id,
        image_sha256=hashlib.sha256(image).hexdigest())
    return envelope(VisionResponse, model='agents.berth_vision', model_version='1.0.0', backend='real',
        request={'metadata':meta.model_dump(mode='json'), 'image_sha256':result.image_sha256}, result=result, status='AMBER',
        assumptions=[note, *questions], validity=Validity(state='limited', reasons=[ValidityReason(
            code='BERTH_DRAFT_UNCONFIRMED', message='Draft geometry/ratings are unqualified and need explicit confirmation.',
            affected_components=['berth'])]))
