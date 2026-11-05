import pytest
from shapely.geometry import box

from mooring.approach.enc import DepthArea, ENCError, _metadata, evaluate_corridor, read_metadata, read_depth_areas
from mooring.approach import enc


def test_chart_identity_and_datums_are_mandatory():
    parsed = _metadata("US5VA12M", {"EDTN": "8", "UPDN": "12", "ISDT": "20261104"}, {"HDAT": 2, "VDAT": 16, "SDAT": 12, "DUNI": 1})
    assert (parsed.edition, parsed.update_number, parsed.vertical_datum, parsed.sounding_datum) == ("8", "12", "16", "12")
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


# Minimal metadata observed with Fiona/GDAL from NOAA US5ORFCC base + updates 1..5,
# https://www.charts.noaa.gov/ENCs/US5ORFCC.zip, retrieved 2026-11-05 UTC.
# Raw chart files remain outside git; fixtures exercise the actual exposed field names.
DSID = {"DSID_DSNM": "US5ORFCC.000", "DSID_EDTN": "1", "DSID_UPDN": "5", "DSID_ISDT": "20260930",
        "DSPM_HDAT": 2, "DSPM_VDAT": 16, "DSPM_SDAT": 12, "DSPM_DUNI": 1}


def fake_reader(monkeypatch, metadata=None, depth=None, extra=None, epsg=4326):
    from types import SimpleNamespace
    from shapely.geometry import mapping
    data = {"DSID": [{"properties": DSID if metadata is None else metadata}],
            "DEPARE": [{"properties": {"DRVAL1": 3.5, "DRVAL2": 5.0}, "geometry": mapping(box(0, 0, 1, 1))}] if depth is None else depth,
            **(extra or {})}
    class Source:
        def __init__(self, rows):
            self.rows = rows
            self.crs = SimpleNamespace(to_epsg=lambda: epsg)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def __iter__(self):
            return iter(self.rows)
    monkeypatch.setattr(enc.fiona, "listlayers", lambda path: list(data))
    monkeypatch.setattr(enc.fiona, "open", lambda path, *, layer, **kwargs: Source(data[layer]))


def test_reader_uses_prefixed_combined_dsid_and_dataset_identity(monkeypatch):
    fake_reader(monkeypatch)
    metadata = read_metadata("renamed-local-copy.000")
    assert metadata.cell == "US5ORFCC" and metadata.update_number == "5"
    assert metadata.vertical_datum == "16" and metadata.sounding_datum == "12" and metadata.depth_units == "1"
    assert read_depth_areas("fixture.000")[0].minimum_depth_m == 3.5


@pytest.mark.parametrize("field,value", [("DSPM_HDAT", 0), ("DSPM_SDAT", 23), ("DSPM_DUNI", 2)])
def test_depth_reader_rejects_unsupported_datum_or_units(monkeypatch, field, value):
    fake_reader(monkeypatch, metadata={**DSID, field: value})
    with pytest.raises(ENCError, match="requires WGS84, metres and MLLW"):
        read_depth_areas("fixture.000")


@pytest.mark.parametrize("field", ["DSID_DSNM", "DSID_EDTN", "DSID_UPDN", "DSID_ISDT", "DSPM_HDAT", "DSPM_VDAT", "DSPM_SDAT", "DSPM_DUNI"])
def test_incomplete_metadata_is_not_inferred(monkeypatch, field):
    fake_reader(monkeypatch, metadata={k: v for k, v in DSID.items() if k != field})
    with pytest.raises(ENCError):
        read_metadata("fixture.000")


def test_local_sounding_datum_override_requires_explicit_handling(monkeypatch):
    fake_reader(monkeypatch, extra={"M_SDAT": [{"properties": {"VERDAT": 23}}]})
    with pytest.raises(ENCError, match="overrides"):
        read_depth_areas("fixture.000")


def test_depth_reader_requires_known_coordinate_reference(monkeypatch):
    fake_reader(monkeypatch, epsg=None)
    with pytest.raises(ENCError, match="EPSG:4326"):
        read_depth_areas("fixture.000")


@pytest.mark.parametrize("low,high", [(float("nan"), 10), (1, float("inf")), (10, 2)])
def test_nonfinite_or_reversed_depth_bounds_rejected(low, high):
    with pytest.raises(ENCError, match="bounds"):
        evaluate_corridor(box(0, 0, 1, 1), [DepthArea(box(0, 0, 1, 1), low, high)])


def test_unknown_depth_is_not_hidden_by_other_coverage(monkeypatch):
    from shapely.geometry import mapping
    fake_reader(monkeypatch, depth=[
        {"properties": {"DRVAL1": 10}, "geometry": mapping(box(0, 0, 1, 1))},
        {"properties": {"DRVAL1": None}, "geometry": mapping(box(0, 0, 1, 1))},
    ])
    with pytest.raises(ENCError, match="unknown minimum"):
        read_depth_areas("fixture.000")


def test_self_intersecting_corridor_rejected():
    from shapely.geometry import Polygon
    with pytest.raises(ENCError, match="valid non-empty"):
        evaluate_corridor(Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)]), [])
