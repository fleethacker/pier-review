"""Deterministic image-to-face projection. No draft is saved before explicit confirmation."""
import math

from mooring import refdata
from mooring.core.envelopes import envelope, new_id
from mooring.core.schemas import Provenance, Validity, ValidityReason
from mooring.core.schemas.berth_drafts import BerthDraftRequest, BerthDraftResponse, BerthDraftResult


def build(req: BerthDraftRequest) -> BerthDraftResponse:
    source = refdata.berth(req.source_berth_id)
    notes = ['Geometry is a draft, not a survey. Confirm location, depth, fenders, fitting positions and ratings.',
             'Catalog capacities are estimated seed values citing NSTM Table 582-5-6, not image measurements or certified ratings.']
    fittings = source.fittings
    if req.image_fittings:
        a, b = req.pier_face_start_px, req.pier_face_end_px
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dy)
        templates = {}
        for fitting in source.fittings:
            if fitting.kind not in templates or fitting.capacity_nominal_lbf < templates[fitting.kind].capacity_nominal_lbf:
                templates[fitting.kind] = fitting
        fittings = []
        for found in req.image_fittings:
            if found.kind not in templates:
                raise refdata.InvalidReference(f'No sourced catalog capacity template for fitting kind {found.kind!r}')
            along = ((found.center_px[0]-a[0])*dx + (found.center_px[1]-a[1])*dy) / length
            x = along * req.scale_ft_per_px
            if along < 0 or along > length or x > source.face_length_ft:
                raise refdata.InvalidReference(f'Image fitting {found.item_id} projects outside the supplied pier face')
            fittings.append(templates[found.kind].model_copy(update={
                'fitting_id': found.item_id, 'x_ft': x, 'y_ft': 0.0, 'occupied_by': None,
                'condition': 'suspect',
            }))
        notes.append('Detected fittings projected onto the supplied straight pier-face anchors; setback is unresolved (y=0).')
        notes.append('Detected fittings are suspect until inspected; confirmation alone does not certify capacity.')
    draft = source.model_copy(deep=True, update={
        'berth_id': new_id('DRAFT').upper().replace('_','-'), 'name': req.name or f'Draft: {source.name}',
        'fittings': fittings,
        'provenance': Provenance(source=f'Human-confirmation draft from catalog {source.berth_id}', confidence='estimated',
                                 notes=' '.join(notes)),
    })
    result = BerthDraftResult(draft_berth=draft,
        geometry_source='image anchors plus catalog' if req.image_fittings else f'catalog:{source.berth_id}',
        needs_confirmation=[f.fitting_id for f in fittings], notes=notes)
    return envelope(BerthDraftResponse, model='mooring.berth_draft', model_version='1.0.0', backend='real',
        request=req, result=result, status='AMBER', assumptions=notes,
        validity=Validity(state='limited', reasons=[ValidityReason(code='BERTH_DRAFT_UNCONFIRMED',
            message='Draft geometry and estimated ratings require explicit human confirmation and engineering qualification.',
            affected_components=['berth'])]))
