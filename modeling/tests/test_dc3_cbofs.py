from datetime import UTC, datetime

import numpy as np
import pytest
import xarray as xr

from mooring.environment.cbofs import CBOFSSampler
from mooring.environment.errors import ProviderError


def fixture():
    ds = xr.Dataset(
        data_vars={
            "Latitude": (("ny", "nx"), [[36.95, 36.95], [36.96, 36.96]]),
            "Longitude": (("ny", "nx"), [[-76.34, -76.33], [-76.34, -76.33]]),
            "mask": (("ny", "nx"), [[0, 1], [1, 1]]),
            "zetatomllw": (("time", "ny", "nx"), [[[0, .30], [.4, .5]], [[0, .31], [.41, .51]]]),
            "u_eastward": (("time", "Depth", "ny", "nx"), np.full((2, 2, 2, 2), 0.3)),
            "v_northward": (("time", "Depth", "ny", "nx"), np.full((2, 2, 2, 2), 0.4)),
        },
        coords={"Depth": [1.0, 6.0], "time": np.array(["2026-11-05T01:00", "2026-11-05T02:00"], dtype="datetime64[m]")},
    )

    for name, units in {"Latitude": "degrees_north", "Longitude": "degrees_east", "Depth": "m",
                        "zetatomllw": "meters", "u_eastward": "meters second-1", "v_northward": "meters second-1"}.items():
        ds[name].attrs["units"] = units
    ds.Depth.attrs["positive"] = "down"
    return ds


def test_samples_nearest_wet_cell_layer_mllw_and_toward_vector():
    issued = datetime(2026, 11, 5, tzinfo=UTC)
    rows = CBOFSSampler().sample(fixture(), 36.9501, -76.3399, depth_m=5, issued_at=issued, as_of=issued)
    assert rows[0].grid_longitude == -76.33
    assert rows[0].depth_m == 6
    assert rows[0].current_speed_kt == pytest.approx(0.5 * 1.9438444924406)
    assert rows[0].current_toward_true_deg == pytest.approx(36.8698976)
    assert rows[0].water_level_mllw_ft == pytest.approx(.30 * 3.2808398950131)


def test_replay_rejects_future_cycle():
    with pytest.raises(ProviderError, match="issued after replay time"):
        CBOFSSampler().sample(fixture(), 36.95, -76.33, depth_m=1,
                              issued_at=datetime(2026, 11, 5, 6, tzinfo=UTC), as_of=datetime(2026, 11, 5, tzinfo=UTC))


def test_missing_declared_datum_variable_is_rejected():
    with pytest.raises(ProviderError, match="zetatomllw"):
        CBOFSSampler().sample(fixture().drop_vars("zetatomllw"), 36.95, -76.33, depth_m=1,
                              issued_at=datetime(2026, 11, 5, tzinfo=UTC), as_of=datetime(2026, 11, 5, tzinfo=UTC))


@pytest.mark.parametrize("latitude,longitude,depth", [(91, -76.3, 1), (36.9, -181, 1), (36.9, -76.3, -1)])
def test_invalid_sampling_location_or_depth_is_rejected(latitude, longitude, depth):
    with pytest.raises(ValueError, match="outside its valid range"):
        CBOFSSampler().sample(fixture(), latitude, longitude, depth_m=depth,
                              issued_at=datetime(2026, 11, 5, tzinfo=UTC), as_of=datetime(2026, 11, 5, tzinfo=UTC))



def sample(ds, **kwargs):
    issued = datetime(2026, 11, 5, tzinfo=UTC)
    return CBOFSSampler().sample(ds, kwargs.pop("latitude", 36.95), kwargs.pop("longitude", -76.33),
                                depth_m=kwargs.pop("depth_m", 5), issued_at=issued, as_of=issued, **kwargs)


@pytest.mark.parametrize("name,units", [("u_eastward", "knots"), ("v_northward", "mph"),
    ("zetatomllw", "feet"), ("Depth", "feet"), ("Latitude", "radians"), ("Longitude", None)])
def test_units_are_required_and_never_silently_assumed(name, units):
    ds = fixture()
    ds[name].attrs["units"] = units
    with pytest.raises(ProviderError, match="units"):
        sample(ds)


@pytest.mark.parametrize("lat,lon,depth", [(40, -76.33, 5), (36.95, -70, 5), (36.95, -76.33, 20)])
def test_no_extrapolation_outside_domain_or_layers(lat, lon, depth):
    with pytest.raises(ProviderError, match="outside"):
        sample(fixture(), latitude=lat, longitude=lon, depth_m=depth)


@pytest.mark.parametrize("fill", [-99999.0, 1e20, float("nan")])
def test_missing_values_omit_the_time_with_explicit_gap_provenance(fill):
    ds = fixture()
    ds.u_eastward.values[0, :, :, :] = fill
    ds.u_eastward.attrs["_FillValue"] = fill
    rows = sample(ds)
    assert len(rows) == 1 and rows[0].valid_at_utc.hour == 2
    assert rows[0].omitted_times_utc == (datetime(2026, 11, 5, 1, tzinfo=UTC),)
    assert any("caller-supplied" in text for text in rows[0].limitations)


def test_missing_selected_layer_never_moves_to_a_nearby_cell():
    ds = fixture()
    ds.u_eastward.values[:, 1, 0, 1] = -99999
    with pytest.raises(ProviderError, match="no available values"):
        sample(ds)


@pytest.mark.parametrize("times", [["2026-11-05T02:00", "2026-11-05T01:00"],
    ["2026-11-05T01:00", "2026-11-05T01:00"], ["NaT", "2026-11-05T01:00"]])
def test_times_must_be_valid_unique_and_ordered(times):
    ds = fixture().assign_coords(time=np.array(times, dtype="datetime64[m]"))
    with pytest.raises(ProviderError, match="time"):
        sample(ds)


def test_undecoded_numeric_time_is_not_interpreted_as_epoch_nanoseconds():
    with pytest.raises(ProviderError, match="decoded datetime"):
        sample(fixture().assign_coords(time=[1.0, 2.0]))


def test_invalid_dimensions_coordinates_or_depth_order_are_rejected():
    ds = fixture()
    ds["u_eastward"] = ds.u_eastward.transpose("Depth", "time", "ny", "nx")
    with pytest.raises(ProviderError, match="dimensions"):
        sample(ds)
    ds = fixture()
    ds.Latitude.values[0, 0] = float("nan")
    with pytest.raises(ProviderError, match="coordinates"):
        sample(ds)
    ds = fixture().isel(Depth=[1, 0])
    with pytest.raises(ProviderError, match="strictly increasing"):
        sample(ds)


def test_local_netcdf_roundtrip(tmp_path):
    from mooring.environment.cbofs import open_subset
    path = tmp_path / "synthetic.nc"
    fixture().to_netcdf(path, engine="netcdf4")
    with open_subset(str(path)) as dataset:
        assert sample(dataset) == sample(fixture())


@pytest.mark.parametrize("url", ["http://opendap.co-ops.nos.noaa.gov/thredds/dodsC/NOAA/CBOFS/x.nc",
    "https://example.org/file.nc", "https://user:secret@opendap.co-ops.nos.noaa.gov/thredds/dodsC/NOAA/CBOFS/x.nc"])
def test_remote_open_rejects_unapproved_sources_without_network(url, monkeypatch):
    from mooring.environment import cbofs
    monkeypatch.setattr(cbofs.xr, "open_dataset", lambda *a, **k: pytest.fail("must not open rejected URL"))
    with pytest.raises(ProviderError, match="NOAA HTTPS"):
        cbofs.open_subset(url)


def test_native_open_sets_timeout_and_wraps_transport_failure(monkeypatch):
    from mooring.environment import cbofs
    settings = []
    monkeypatch.setattr(cbofs.netCDF4, "rc_set", lambda key, value: settings.append((key, value)))
    def fail(*args, **kwargs):
        raise OSError("synthetic timeout")
    monkeypatch.setattr(cbofs.xr, "open_dataset", fail)
    with pytest.raises(ProviderError, match="could not be opened"):
        cbofs.open_subset("https://opendap.co-ops.nos.noaa.gov/thredds/dodsC/NOAA/CBOFS/x.nc")
    assert settings == [("HTTP.TIMEOUT", str(cbofs.HTTP_TIMEOUT_S))]


def test_native_access_is_not_allowed_from_api_worker_threads(monkeypatch):
    from mooring.environment import cbofs
    monkeypatch.setattr(cbofs, "current_thread", lambda: object())
    with pytest.raises(ProviderError, match="isolated main-thread worker"):
        cbofs.open_subset("synthetic.nc")


def test_lazy_native_read_failure_is_provider_unavailable():
    from mooring.environment import cbofs
    class FailedVariable:
        name = "u_eastward"
        def __array__(self, *args, **kwargs):
            raise OSError("synthetic read timeout")
    with pytest.raises(ProviderError, match="could not be read"):
        cbofs._read(FailedVariable())


def test_encoded_fill_value_and_depth_orientation_are_honored():
    ds = fixture()
    ds.u_eastward.values[0, :, :, :] = 1e20
    ds.u_eastward.encoding["missing_value"] = 1e20
    assert len(sample(ds)) == 1
    ds.Depth.attrs["positive"] = "up"
    with pytest.raises(ProviderError, match="positive down"):
        sample(ds)
