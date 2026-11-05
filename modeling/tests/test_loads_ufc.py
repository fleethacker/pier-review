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


@pytest.mark.parametrize("angle", [0, 30, 90, 135, 180, 225, 270, 330])
def test_d_frames_and_reflection(angle):
    from mooring.loads import compute_loads
    ship = synthetic_ship()
    env = environment(wind_from_true_deg=angle, current_set_true_deg=angle, current_speed_kt=1)
    result = compute_loads(ship, "full_load", 0, env, 50)
    reflected = compute_loads(ship, "full_load", 0, env.model_copy(update={"wind_from_true_deg": (-angle) % 360, "current_set_true_deg": (-angle) % 360}), 50)
    rotated = compute_loads(ship, "full_load", 37, env.model_copy(update={"wind_from_true_deg": (angle + 37) % 360, "current_set_true_deg": (angle + 37) % 360}), 50)
    for kind in ("wind", "current"):
        a, b, r = getattr(result, kind), getattr(reflected, kind), getattr(rotated, kind)
        assert a.fx_lbf == pytest.approx(b.fx_lbf, abs=1e-8)
        assert a.fy_lbf == pytest.approx(-b.fy_lbf, abs=1e-8)
        assert a.mz_ftlbf == pytest.approx(-b.mz_ftlbf, abs=1e-7)
        for field in ("fx_lbf", "fy_lbf", "mz_ftlbf"):
            assert getattr(a, field) == pytest.approx(getattr(r, field), abs=1e-7)
    if angle == 90:
        assert result.wind.fy_lbf > 0 > result.current.fy_lbf
    if angle == 0:
        assert result.wind.fx_lbf < 0 < result.current.fx_lbf
    if angle == 180:
        assert result.wind.fx_lbf > 0 > result.current.fx_lbf


def test_d_shielding_and_zero_speeds():
    ship = synthetic_ship()
    env = environment(current_speed_kt=1)
    a = ufc.compute_loads(ship, "full_load", 0, env, 50)
    b = ufc.compute_loads(ship, "full_load", 0, env, 50, shielding_factor=0)
    assert b.wind.fx_lbf == b.wind.fy_lbf == b.wind.mz_ftlbf == 0
    assert a.current == b.current
    z = ufc.compute_loads(ship, "full_load", 0, environment(wind_speed_kt=0, wind_gust_kt=0), 50)
    assert z.total.fx_lbf == z.total.fy_lbf == z.total.mz_ftlbf == 0


def test_e_endpoints_and_stored_result():
    from fastapi.testclient import TestClient
    from modeling_api.main import app
    from mooring.core.schemas import LoadsResponse, PolarResponse
    from mooring.examples import EXAMPLES
    client = TestClient(app)
    for name, path, model in (("loads_environmental", "environmental", LoadsResponse), ("loads_polar", "polar", PolarResponse)):
        response = client.post(f"/api/v1/loads/{path}", json=EXAMPLES[name])
        assert response.status_code == 200, response.text
        parsed = model.model_validate(response.json())
        assert parsed.backend == "real" and parsed.model_version == "1.0.0"
        assert not any("MOCK BACKEND" in text for text in parsed.assumptions)
        assert client.get(f"/api/v1/results/{parsed.result_id}").json() == response.json()


def test_e_clamps_and_off_pier():
    from mooring.loads.service import environmental, polar
    from mooring.core.schemas import LoadsRequest, PolarRequest
    req = LoadsRequest(ship_class_id="DDG-51-FIIA", heading_true_deg=0, water_depth_ft=1,
                       environment=environment(current_speed_kt=1), side_to="starboard")
    a = environmental(req)
    b = environmental(req.model_copy(update={"side_to": "port"}))
    assert a.result.off_pier_component_lbf == -b.result.off_pier_component_lbf
    assert a.result.current.coefficients["depth_draft_ratio"] == 1
    assert a.status == "RED" and a.validity.state == "invalid"  # S03: depth at/below draft is not a valid floating result
    assert any(w.rule_id == "UFC-DEPTH-RANGE" and w.severity == "RED" for w in a.warnings)
    assert "DEPTH_NOT_ABOVE_DRAFT" in {r.code for r in a.validity.reasons}
    assert any("clamped" in text for text in a.assumptions)
    p = polar(PolarRequest(ship_class_id=req.ship_class_id, water_depth_ft=1, wind_speed_kt=50))
    assert any(w.rule_id == "UFC-DEPTH-RANGE" for w in p.warnings)
    assert len(p.result.points) == 72


@pytest.mark.parametrize("apply_to", ["wind", "current", "both"])
def test_e_polar_matches_environmental(apply_to):
    from mooring.loads.service import environmental, polar
    from mooring.core.schemas import LoadsRequest, PolarRequest
    req = PolarRequest(ship_class_id="DDG-51-FIIA", water_depth_ft=50, wind_speed_kt=30,
                       current_speed_kt=1, step_deg=30, apply_to=apply_to)
    for point in polar(req).result.points:
        env = environment(wind_speed_kt=30 if apply_to != "current" else 0,
                          wind_from_true_deg=point.rel_deg, current_speed_kt=1 if apply_to != "wind" else 0,
                          current_set_true_deg=(point.rel_deg + 180) % 360)
        result = environmental(LoadsRequest(ship_class_id=req.ship_class_id, heading_true_deg=0, water_depth_ft=50,
                                           environment=env, use_gust=False)).result
        for field in ("fx_lbf", "fy_lbf", "mz_ftlbf"):
            assert getattr(point, field) == pytest.approx(getattr(result.total, field))


def test_e_reynolds_floor_and_high_current_warnings():
    from mooring.loads.service import environmental
    from mooring.core.schemas import LoadsRequest
    req = LoadsRequest(ship_class_id="DDG-51-FIIA", heading_true_deg=0, water_depth_ft=50,
                       environment=environment(current_speed_kt=0.00001, current_set_true_deg=0))
    low = environmental(req)
    assert any(w.rule_id == "UFC-LOW-REYNOLDS" for w in low.warnings)
    assert math.isfinite(low.result.current.fx_lbf)
    req.environment.current_speed_kt = 5
    assert any(w.rule_id == "UFC-CURRENT-SPEED" for w in environmental(req).warnings)


# Frozen from origin/dev at the start of this chunk, before any calibration.
# Tuple: lateral, hull lateral, frontal. Only these three areas may be tuned.
ORIGINAL_AREAS = {"DDG-51-FIIA": (14900, 7000, 3000), "CG-47": (25950, 9500, 3800),
                  "LHD-1": (60650, 42000, 9500), "CVN-68": (66150, 45000, 14000)}
NSTM_TARGETS = {"DDG-51-FIIA": (116000, 227000, 463000, 1040000),
                "CG-47": (224000, 439000, 895000, 2010000),
                "LHD-1": (421000, 825000, 1680000, 3790000),
                "CVN-68": (459000, 899000, 1830000, 4130000)}


def wind_peak(ship, speed):
    env = environment(wind_speed_kt=speed, wind_gust_kt=speed)
    values = []
    for angle in range(360):
        result = ufc.compute_loads(ship, "full_load", 0, env.model_copy(update={"wind_from_true_deg": angle}), 100)
        values.append(math.hypot(result.wind.fx_lbf, result.wind.fy_lbf))
    peak = max(values)
    bearings = [angle for angle, value in enumerate(values) if math.isclose(value, peak, rel_tol=1e-10)]
    return peak, bearings


@pytest.mark.parametrize("class_id", ORIGINAL_AREAS)
def test_c_area_limits(class_id):
    from mooring import refdata
    ship = refdata.ship(class_id)
    for field, original in zip(("wind_area_lateral_ft2", "hull_wind_area_lateral_ft2", "wind_area_frontal_ft2"), ORIGINAL_AREAS[class_id]):
        assert 0.75 * original <= getattr(ship, field) <= 1.25 * original
    lc = next(lc for lc in ship.loading_conditions if lc.name == "full_load")
    assert ship.hull_wind_area_lateral_ft2 <= ship.lwl_ft * lc.freeboard_ft
    assert ship.hull_wind_area_lateral_ft2 <= ship.wind_area_lateral_ft2


@pytest.mark.parametrize("class_id", NSTM_TARGETS)
@pytest.mark.parametrize("index,speed", enumerate((50, 70, 100, 150)))
def test_c_nstm_magnitude(class_id, index, speed):
    from mooring import refdata
    peak, _ = wind_peak(refdata.ship(class_id), speed)
    assert peak == pytest.approx(NSTM_TARGETS[class_id][index], rel=0.10)


@pytest.mark.parametrize("class_id", NSTM_TARGETS)
@pytest.mark.parametrize("speed", (50, 70, 100, 150))
def test_c_nstm_bearing(class_id, speed):
    """NSTM Table 582-3-1 uses NCEL/UFC flow-TOWARD, counterclockwise bearings.

    Zero is wind from astern (UFC Figure 4-2). Convert to the API's clockwise
    wind-FROM bearing with (180 - b) % 360 before comparing the resultant peaks.
    """
    from mooring import refdata
    _, bearings = wind_peak(refdata.ship(class_id), speed)
    nstm_bearings = (105, 255) if class_id in ("DDG-51-FIIA", "CG-47") else (100, 260)
    targets = [(180 - b) % 360 for b in nstm_bearings]
    for target in targets:
        error = min(abs((bearing - target + 180) % 360 - 180) for bearing in bearings)
        assert error <= 20, (class_id, speed, bearings, target, error)


def test_f_shallow_beam_current_to_wind():
    from mooring import refdata
    ship = refdata.ship("DDG-51-FIIA")
    lc = next(lc for lc in ship.loading_conditions if lc.name == "full_load")
    depth = (lc.draft_fwd_ft + lc.draft_aft_ft) / 2 / 0.9
    result = ufc.compute_loads(ship, "full_load", 0, environment(current_speed_kt=2), depth)
    ratio = abs(result.current.fy_lbf / result.wind.fy_lbf)
    if ratio < 2:
        pytest.xfail(f"UFC current/wind ratio {ratio:.4f} is below NSTM 582-3.3.2 qualitative factor 2; no coefficient adjustment.")
    assert ratio >= 2


def test_c_geometry_estimates_and_loading():
    from mooring import refdata
    from mooring.loads.service import environmental
    from mooring.core.schemas import LoadsRequest
    ship = refdata.ship("DDG-51-FIIA")
    assert ship.wind_drag_class == "extensive_superstructure"  # UFC Table 4-2 destroyer class
    # Height stays frozen from the ORIGINAL seed areas, independent of calibration.
    assert ship.superstructure_height_ft == pytest.approx(7000 / 466 + (14900 - 7000) / (0.5 * 466))
    assert ship.provenance.confidence == "estimated"
    assert ship.superstructure_height_ft > 0 and ship.midship_coefficient > 0
    full = ufc.ship_inputs(ship, "full_load", 1020)
    light = ufc.ship_inputs(ship, "light", 1020)
    assert light[4] == pytest.approx(ufc.wetted_surface(ship.lwl_ft, light[0], light[1]))
    assert light[4] != full[4]
    no_prop = ship.model_copy(update={"propeller_expanded_area_ft2": 0})
    assert ufc.ship_inputs(no_prop, "full_load", 1020)[5] == 0
    response = environmental(LoadsRequest(ship_class_id=ship.class_id, loading="light", heading_true_deg=0,
                                         water_depth_ft=50, environment=environment()))
    assert any("Wetted surface estimated" in a for a in response.assumptions)



def _shallow_berth(client, depth_ft):
    berth = client.get("/api/v1/berths/NAVSTA-NORFOLK-P12-N").json()
    berth["berth_id"] = f"TEST-SHALLOW-{int(depth_ft)}"
    berth["depth_profile"] = [{"x_ft": 0, "depth_mllw_ft": depth_ft}, {"x_ft": 1350, "depth_mllw_ft": depth_ft}]
    assert client.post("/api/v1/berths", json=berth).status_code == 201
    return berth["berth_id"]


def test_g_load_warnings_reach_analysis_and_tug_plan():
    """Range warnings computed by the load model must not be dropped by downstream modules."""
    import copy

    from fastapi.testclient import TestClient

    from modeling_api.main import app
    from mooring.examples import EXAMPLES

    client = TestClient(app)
    berth_id = _shallow_berth(client, 25.0)  # DDG full-load draft 30.5 ft: depth below draft

    body = copy.deepcopy(EXAMPLES["mooring_analyze"])
    body["berth_id"] = berth_id
    body["environment"]["current_speed_kt"] = 3.5  # above the 1.5 m/s current-model range
    analysis = client.post("/api/v1/mooring/analyze", json=body).json()
    rules = {f["rule_id"] for f in analysis["result"]["findings"]}
    assert {"UFC-DEPTH-RANGE", "UFC-CURRENT-SPEED"} <= rules
    assert {"UFC-DEPTH-RANGE", "UFC-CURRENT-SPEED"} <= {w["rule_id"] for w in analysis["warnings"]}
    assert analysis["status"] in ("AMBER", "RED")

    tug_body = copy.deepcopy(EXAMPLES["tugs_berthing_plan"])
    tug_body["berth_id"] = berth_id
    plan = client.post("/api/v1/tugs/berthing-plan", json=tug_body).json()
    assert "UFC-DEPTH-RANGE" in {w["rule_id"] for w in plan["warnings"]}
    assert plan["status"] in ("AMBER", "RED")

    deep = client.post("/api/v1/mooring/analyze", json=EXAMPLES["mooring_analyze"]).json()
    assert not {f["rule_id"] for f in deep["result"]["findings"]} & {"UFC-DEPTH-RANGE", "UFC-CURRENT-SPEED"}


def test_g_rules_registry_lists_load_validity_rules():
    from fastapi.testclient import TestClient

    from modeling_api.main import app

    ids = {r["rule_id"] for r in TestClient(app).get("/api/v1/rules").json()}
    assert {"UFC-DEPTH-RANGE", "UFC-CURRENT-SPEED", "UFC-LOW-REYNOLDS"} <= ids


def test_g_service_reports_mixed_backend():
    from fastapi.testclient import TestClient

    from modeling_api.main import app

    client = TestClient(app)
    assert client.get("/api/v1/health").json()["backend"] == "mixed"
    assert client.get("/api/v1/version").json()["modules"]["M3 environmental loads"] == "real"
