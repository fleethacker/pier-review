import pytest
from shapely.geometry import box

from mooring.approach.enc import DepthArea, ENCError, _metadata, evaluate_corridor


def test_chart_identity_and_datums_are_mandatory():
    parsed = _metadata("US5VA12M", {"EDTN": "8", "UPDN": "12", "ISDT": "20261104"}, {"HDAT": 2, "VDAT": 12})
    assert (parsed.edition, parsed.update_number, parsed.vertical_datum) == ("8", "12", "12")
    with pytest.raises(ENCError, match="vertical datum"):
        _metadata("US5VA12M", {"EDTN": "8", "UPDN": "12", "ISDT": "20261104"}, {"HDAT": 2})


def test_shallow_patch_between_deep_endpoints_controls_corridor():
    areas = [DepthArea(box(0, 0, 4, 2), 12), DepthArea(box(4, 0, 6, 2), 4), DepthArea(box(6, 0, 10, 2), 12)]
    result = evaluate_corridor(box(0, 0, 10, 2), areas)
    assert result.covered and result.minimum_depth_m == 4


def test_swept_width_obstruction_controls_even_when_centerline_is_deep():
    areas = [DepthArea(box(0, 0, 10, 3), 12), DepthArea(box(0, 3, 10, 4), 2)]
    assert evaluate_corridor(box(0, 0, 10, 4), areas).minimum_depth_m == 2


def test_missing_coverage_is_not_assumed_deep():
    result = evaluate_corridor(box(0, 0, 10, 2), [DepthArea(box(0, 0, 9, 2), 12)])
    assert not result.covered and result.minimum_depth_m is None


def test_invalid_corridor_rejected():
    with pytest.raises(ENCError):
        evaluate_corridor(box(0, 0, 0, 0), [])
