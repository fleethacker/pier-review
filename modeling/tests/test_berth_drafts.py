"""Image geometry is deterministic and never certifies capacity or saves itself."""
import pytest
from mooring import refdata
from mooring.core.schemas.berth_drafts import BerthDraftRequest
from mooring.refdata.drafts import build

BERTH='NAVSTA-NORFOLK-P12-N'


def test_catalog_draft_is_unsaved_and_every_fitting_requires_confirmation():
    original=refdata.berth(BERTH)
    response=build(BerthDraftRequest(source_berth_id=BERTH))
    draft=response.result.draft_berth
    assert draft.berth_id != original.berth_id and draft.fittings == original.fittings
    assert set(response.result.needs_confirmation)=={f.fitting_id for f in draft.fittings}
    assert response.validity.state=='limited' and draft.provenance.confidence=='estimated'
    with pytest.raises(refdata.NotFound):refdata.berth(draft.berth_id)
    assert refdata.berth(BERTH)==original


def test_projection_uses_user_scale_and_snaps_to_face_without_invented_capacity():
    original=refdata.berth(BERTH)
    kind=original.fittings[0].kind
    response=build(BerthDraftRequest(source_berth_id=BERTH,scale_ft_per_px=2,
        pier_face_start_px=(10,20),pier_face_end_px=(110,20),
        image_fittings=[dict(item_id='image-1',kind=kind,center_px=(35,30),confidence=.95)]))
    fitting=response.result.draft_berth.fittings[0]
    assert fitting.x_ft==50 and fitting.y_ft==0 and fitting.condition=='suspect'
    assert fitting.capacity_nominal_lbf==min(f.capacity_nominal_lbf for f in original.fittings if f.kind==kind)
    assert response.result.needs_confirmation==['image-1']


def test_invalid_anchor_scale_kind_or_outside_face_never_yields_plausible_geometry():
    with pytest.raises(ValueError):BerthDraftRequest(source_berth_id=BERTH,pier_face_start_px=(1,1),pier_face_end_px=(1,1))
    with pytest.raises(ValueError):BerthDraftRequest(source_berth_id=BERTH,image_fittings=[dict(item_id='i',kind='bollard',center_px=(1,1),confidence=.5)])
    req=BerthDraftRequest(source_berth_id=BERTH,scale_ft_per_px=1,pier_face_start_px=(0,0),pier_face_end_px=(100,0),
        image_fittings=[dict(item_id='i',kind='invented_capacity_kind',center_px=(10,0),confidence=.99)])
    with pytest.raises(refdata.InvalidReference,match='No sourced'):build(req)
    req.image_fittings[0].kind=refdata.berth(BERTH).fittings[0].kind
    req.image_fittings[0].center_px=(200,0)
    with pytest.raises(refdata.InvalidReference,match='outside'):build(req)
