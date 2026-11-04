"""Tests for the real (non-mock) pieces: geometry, rules, seed data, contract freshness."""

import copy
import importlib.util
import math
from pathlib import Path

from mooring import refdata
from mooring.core.geometry import line_geometry, ship_heading_true, ship_to_berth
from mooring.core.schemas import AnalyzeRequest, MooringConfig
from mooring.examples import EXAMPLES
from mooring.moored.solver import analyze_full

ROOT = Path(__file__).resolve().parents[2]
DDG = refdata.ship("DDG-51-FIIA")
P12N = refdata.berth("NAVSTA-NORFOLK-P12-N")


def test_starboard_side_to_puts_starboard_side_at_the_pier():
    cfg = MooringConfig(side_to="starboard", ship_x_ft=650, lines=[])
    x, y = ship_to_berth(0, -DDG.beam_ft / 2, DDG, P12N, cfg)
    assert (x, y) == (650, 12.0)  # starboard side sits at the camel standoff
    assert ship_heading_true(P12N, "starboard") == P12N.face_bearing_true_deg


def test_port_side_to_reverses_bow():
    cfg = MooringConfig(side_to="port", ship_x_ft=650, lines=[])
    bow_x, _ = ship_to_berth(DDG.loa_ft / 2, 0, DDG, P12N, cfg)
    assert bow_x < 650


def test_breast_efficiency_is_cos_of_lead():
    cfg = MooringConfig(**EXAMPLES["mooring_analyze"]["config"])
    for ln in cfg.lines:
        g = line_geometry(ln, DDG, P12N, cfg, 0.0)
        assert math.isclose(g.breast_efficiency, math.cos(math.radians(g.horiz_angle_deg)))


def test_wind_load_scales_with_speed_squared():
    from mooring.loads import compute_loads

    base = AnalyzeRequest(**EXAMPLES["mooring_analyze"]).environment
    f1 = compute_loads(DDG, "full_load", 105, base.model_copy(update={"wind_gust_kt": 20, "current_speed_kt": 0}), 45)
    f2 = compute_loads(DDG, "full_load", 105, base.model_copy(update={"wind_gust_kt": 40, "current_speed_kt": 0}), 45)
    assert math.isclose(f2.wind.fy_lbf / f1.wind.fy_lbf, 4.0, rel_tol=1e-9)


def test_seed_wind_areas_match_nstm_table_at_50kt():
    """NSTM Table 582-3-1 50-kt loads; calibrated UFC beam loads stay within 10%."""
    from mooring.core.schemas import EnvironmentSnapshot
    from mooring.loads import compute_loads

    targets = {"DDG-51-FIIA": 116_000, "CG-47": 224_000, "LHD-1": 421_000, "CVN-68": 459_000}
    env = EnvironmentSnapshot(wind_speed_kt=50, wind_gust_kt=50, wind_from_true_deg=90, current_speed_kt=0,
                              current_set_true_deg=0, water_level_mllw_ft=0)
    for cid, target in targets.items():
        f = compute_loads(refdata.ship(cid), "full_load", 0, env, 50).wind.fy_lbf
        assert abs(f - target) / target < 0.10, (cid, f)


def test_min_lines_rule_fires_without_springs():
    body = copy.deepcopy(EXAMPLES["mooring_analyze"])
    body["config"]["lines"] = [ln for ln in body["config"]["lines"] if ln["role"] in ("breast",)]
    findings = analyze_full(AnalyzeRequest(**body))[0].findings
    assert any(f.rule_id == "MIN-LINES" and f.severity == "RED" for f in findings)


def test_one_per_fitting_allows_opposing_springs_only():
    body = copy.deepcopy(EXAMPLES["mooring_analyze"])
    lines = body["config"]["lines"]
    lines[2]["pier_fitting_id"] = lines[3]["pier_fitting_id"]  # two breasts on one bollard
    findings = analyze_full(AnalyzeRequest(**body))[0].findings
    assert any(f.rule_id == "ONE-PER-FITTING" for f in findings)


def test_contract_is_up_to_date():
    spec = importlib.util.spec_from_file_location("export_contract", ROOT / "scripts" / "export_contract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stale = [str(p.relative_to(ROOT)) for p, text in mod.render().items() if not p.exists() or p.read_text() != text]
    assert not stale, f"Run `make contract`; stale: {stale}"
