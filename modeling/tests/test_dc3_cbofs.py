from datetime import UTC, datetime

import numpy as np
import pytest
import xarray as xr

from mooring.environment.cbofs import CBOFSSampler
from mooring.environment.errors import ProviderError


def fixture():
    return xr.Dataset(
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
