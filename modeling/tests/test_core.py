"""Tests for the real (non-mock) pieces: geometry, rules, seed data, contract freshness."""

import copy
import importlib.util
import math
from pathlib import Path

import pytest

from mooring import refdata
from mooring.core.geometry import line_geometry, ship_heading_true, ship_to_berth
from mooring.core.schemas import AnalyzeRequest, MooringConfig
from mooring.mock.examples import EXAMPLES
from mooring.mock.mooring import solve
from mooring.mock.planning import template_config

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
    from mooring.mock.forces import crude_loads

    base = AnalyzeRequest(**EXAMPLES["mooring_analyze"]).environment
    f1 = crude_loads(DDG, "full_load", 105, base.model_copy(update={"wind_gust_kt": 20, "current_speed_kt": 0}), 45)
    f2 = crude_loads(DDG, "full_load", 105, base.model_copy(update={"wind_gust_kt": 40, "current_speed_kt": 0}), 45)
    assert math.isclose(f2.wind.fy_lbf / f1.wind.fy_lbf, 4.0, rel_tol=1e-9)


def test_seed_wind_areas_match_nstm_table_at_50kt():
    """NSTM Table 582-3-1 50-kt loads; mock drag model must be within 10% at the beam."""
    from mooring.core.schemas import EnvironmentSnapshot
    from mooring.mock.forces import crude_loads

    targets = {"DDG-51-FIIA": 116_000, "CG-47": 224_000, "LHD-1": 421_000, "CVN-68": 459_000}
    env = EnvironmentSnapshot(wind_speed_kt=50, wind_gust_kt=50, wind_from_true_deg=90, current_speed_kt=0,
                              current_set_true_deg=0, water_level_mllw_ft=0)
    for cid, target in targets.items():
        f = crude_loads(refdata.ship(cid), "full_load", 0, env, 50).wind.fy_lbf
        assert abs(f - target) / target < 0.10, (cid, f)


def test_min_lines_rule_fires_without_springs():
    body = copy.deepcopy(EXAMPLES["mooring_analyze"])
    body["config"]["lines"] = [ln for ln in body["config"]["lines"] if ln["role"] in ("bow", "stern")]
    s = solve(AnalyzeRequest(**body))
    assert any(f.rule_id == "MIN-LINES" and f.severity == "RED" for f in s.result.findings)


def test_one_per_fitting_allows_opposing_springs_only():
    body = copy.deepcopy(EXAMPLES["mooring_analyze"])
    lines = body["config"]["lines"]
    lines[2]["pier_fitting_id"] = lines[1]["pier_fitting_id"]  # opposing springs share a bollard: allowed
    s = solve(AnalyzeRequest(**body))
    assert not any(f.rule_id == "ONE-PER-FITTING" for f in s.result.findings)
    lines[3]["pier_fitting_id"] = lines[1]["pier_fitting_id"]  # a third line on it: not allowed
    s = solve(AnalyzeRequest(**body))
    assert any(f.rule_id == "ONE-PER-FITTING" for f in s.result.findings)


def test_contract_is_up_to_date():
    spec = importlib.util.spec_from_file_location("export_contract", ROOT / "scripts" / "export_contract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stale = [str(p.relative_to(ROOT)) for p, text in mod.render().items() if not p.exists() or p.read_text() != text]
    assert not stale, f"Run `make contract`; stale: {stale}"


@pytest.mark.parametrize("berth_id, side", [("NAVSTA-NORFOLK-P12-S", "starboard"), ("NAVSTA-NORFOLK-P12-N", "port")])
def test_template_layout_crossing_pairs_edge_bollards_and_end_lines(berth_id, side):
    ship, berth = refdata.ship("DDG-51-FIIA"), refdata.berth(berth_id)
    ship_x, bow = 650.0, (1 if side == "starboard" else -1)
    cfg = template_config(ship, berth, side, ship_x, "NYLON-DB-7IN")
    sf = {f.fitting_id: f for f in ship.fittings}
    pf = {f.fitting_id: f for f in berth.fittings}
    ends = {}
    for ln in cfg.lines:
        lead = sf[sf[ln.ship_fitting_id].paired_chock_id]
        p = pf[ln.pier_fitting_id]
        assert p.y_ft >= -20 and p.kind.startswith("bollard")  # pier edge row, never the set-back row
        ends[ln.line_number] = (lead.x_ft, bow * (p.x_ft - ship_x))
    assert [ln.role for ln in cfg.lines] == ["bow", "spring_aft", "spring_fwd", "spring_aft", "spring_fwd", "stern"]
    assert len({ln.pier_fitting_id for ln in cfg.lines}) == 6
    for fwd, aft in ((2, 3), (4, 5)):  # ends swap order along the ship, so the pair crosses
        assert ends[fwd][0] > ends[aft][0] and ends[fwd][1] < ends[aft][1]
    assert ends[1][1] > max(ends[2][1], ends[3][1])  # head line reaches beyond the forward pair
    assert ends[6][1] < min(ends[4][1], ends[5][1])  # storm line stays astern of the aft pair
