"""Independent UFC examples (A/B), integration (D/E), and seed calibration (C/F)."""

import math

import pytest

from mooring.core.schemas import EnvironmentSnapshot, ShipClass
from mooring.loads import ufc


def synthetic_ship():
    return ShipClass(
        class_id="SYNTHETIC", name="Fixed geometry", hull_type="DDG", loa_ft=529, lwl_ft=529,
        beam_ft=55, block_coefficient=0.5,
        loading_conditions=[dict(name="full_load", displacement_lt=7810, draft_fwd_ft=21,
                                 draft_aft_ft=21, freeboard_ft=22)],
        wind_area_lateral_ft2=24100, hull_wind_area_lateral_ft2=11152, wind_area_frontal_ft2=3000,
        wind_drag_class="extensive_superstructure", mst_class="II",
        provenance=dict(source="Synthetic test geometry, no seed data", confidence="estimated"),
    )


def environment(**changes):
    values = dict(wind_speed_kt=50, wind_gust_kt=50, wind_from_true_deg=90,
                  current_speed_kt=0, current_set_true_deg=90, water_level_mllw_ft=0)
    return EnvironmentSnapshot(**(values | changes))


def test_a_destroyer_wind_example():
    # UFC 2020 Figure 4-5, pp. 60–61, English inputs; no force/speed supplied for this example.
    assert 11152 / 529 == pytest.approx(21.1, rel=0.02)
    assert 24100 - 11152 == 12948
    cy = ufc.transverse_wind_coefficient(24100, 11152, 529, 78.4, "extensive_superstructure")
    assert cy / 1.02 == pytest.approx(0.940, rel=0.02)
    assert cy == pytest.approx(0.958, rel=0.02)
    # UFC p. 64: 40 degrees is a flow-TOWARD angle, thus stern loading.
    gamma = 90 / 70 * 40 + 90
    assert gamma == pytest.approx(141.4, rel=0.02)
    shape = ufc.longitudinal_wind_shape(40, 70, True)
    assert shape == pytest.approx(0.72, rel=0.02)
    assert ufc.longitudinal_wind_force(2, 1, 1, 40, "extensive_superstructure") == pytest.approx(0.57, rel=0.02)


@pytest.mark.parametrize("ratio,force_kip", [(0.096, 123), (0.288, 148), (0.576, 231), (0.72, 293), (0.96, 427)])
def test_a_ffg_current_example(ratio, force_kip):
    # UFC pp. 73–74, Table 4-6 / Figure 4-11; SI data converted to feet independently.
    lwl, beam, draft, volume = 124.36 / 0.3048, 11.58 / 0.3048, 4.389 / 0.3048, 3555.7 / 0.3048**3
    am = 0.78 * 11.58 * 4.389
    chi = 124.36**2 * am / (11.58 * 3555.7)
    assert am == pytest.approx(39.64, rel=0.02)
    assert chi == pytest.approx(14.89, rel=0.02)
    assert 0.22 * math.sqrt(chi) == pytest.approx(0.8489, rel=0.02)
    cy = ufc.transverse_current_coefficient(lwl, beam, draft, volume, 0.78, draft / ratio)
    force = ufc.transverse_current_force(1.9905, 1.5 / 0.3048, lwl, draft, cy, 90)
    assert force / 1000 == pytest.approx(force_kip, rel=0.02)


def test_a_destroyer_longitudinal_current_example():
    # UFC Tables 4-8 / 4-9, p. 77; 3 kt, salt water, bow-on flow TOWARD 180 degrees.
    surface = ufc.wetted_surface(529, 21, 7810 * 34.977)
    propeller = ufc.propeller_area(529, 55, "DDG")
    friction, reynolds = ufc.friction_coefficient(3 * 1.6878099, 529, 180)
    assert surface == pytest.approx(31897, rel=0.02)
    assert propeller == pytest.approx(347.2, rel=0.02)
    assert reynolds == pytest.approx(2.09e8, rel=0.02)
    assert friction == pytest.approx(0.00188, rel=0.02)
    forces = ufc.longitudinal_current_components(1.9905, 3 * 1.6878099, 55, 21, 529, surface, propeller, 180)
    for actual, expected in zip(forces, (-2950, -1530, -8870)):
        assert actual == pytest.approx(expected, rel=0.02)
    assert sum(forces) == pytest.approx(-13400, rel=0.02)
    for actual, expected in zip(forces, (0.22, 0.12, 0.66)):
        # Printed shares are approximate: UFC says 12%, while its force values give 11.46%.
        # Force and intermediate checks above retain the required 2% relative tolerance.
        assert actual / sum(forces) == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("angle", [0, 30, 60, 90, 105, 120, 150, 180, 210, 270, 330])
def test_b_transverse_shape(angle):
    # Independently evaluated 2016 Eq. (4), which matches 2020 Figure 4-4.
    theta = angle * math.pi / 180
    expected = (math.sin(theta) - 0.05 * math.sin(5 * theta)) / 0.95
    assert ufc.transverse_wind_shape(angle) == pytest.approx(expected, abs=1e-14)


@pytest.mark.parametrize("angle,expected", [(5, 0.069), (30, 0.500), (45, 0.782), (60, 0.957), (75, 1.003), (90, 1.000)])
def test_b_published_shape_values(angle, expected):
    # UFC 2020 Figure 4-4, p. 59, independent tabulated values.
    assert ufc.transverse_wind_shape(angle) == pytest.approx(expected, abs=0.0005)


def test_b_shape_signs_and_symmetry():
    for angle in range(1, 180):
        assert ufc.transverse_wind_shape(angle) > 0
        assert ufc.transverse_wind_shape(angle + 180) < 0
        assert ufc.longitudinal_wind_shape(angle, 70, True) == pytest.approx(ufc.longitudinal_wind_shape(360 - angle, 70, True))
    for angle in (0, 180, 360):
        assert abs(ufc.transverse_wind_shape(angle)) < 1e-14


@pytest.mark.parametrize("use_gust", [True, False])
def test_b_synthetic_speed_squared(use_gust):
    ship = synthetic_ship()
    a = ufc.compute_loads(ship, "full_load", 0, environment(), 50, use_gust)
    b = ufc.compute_loads(ship, "full_load", 0, environment(wind_speed_kt=100, wind_gust_kt=100), 50, use_gust)
    for field in ("fx_lbf", "fy_lbf", "mz_ftlbf"):
        assert getattr(b.wind, field) == pytest.approx(4 * getattr(a.wind, field), abs=1e-8)


def test_b_bow_stern_coefficients():
    assert ufc.longitudinal_wind_force(2, 1, 1, 180, "extensive_superstructure") == pytest.approx(-0.7)
    assert ufc.longitudinal_wind_force(2, 1, 1, 0, "extensive_superstructure") == pytest.approx(0.8)


def test_b_seelig_curve():
    # Fixed chi = 16 gives C0 = .88; Figure 4-9 / Eq. 4-10 with K=2 and C1=3.2.
    results = [ufc.transverse_current_coefficient(100, 20, 10, 5000, 0.8, 10 / r) for r in (0.25, 0.5, 0.75, 1)]
    assert results == pytest.approx([1.025, 1.46, 2.185, 3.2])
    assert results == sorted(results)
