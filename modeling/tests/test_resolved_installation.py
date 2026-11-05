"""Modeled unstretched spans survive JSON round trips and later-tide rechecks."""
import pytest

from mooring.core.schemas import AnalyzeRequest, AnalyzeResult, MooringConfig
from mooring.demo_cases import docking_cases
from mooring.moored.solver import analyze


@pytest.mark.parametrize('level', [-1.0, 1.0, 3.0])
def test_resolved_configuration_reproduces_fixed_installation_at_later_tides(level):
    req = docking_cases()[0].analysis_request.model_copy(deep=True)
    req.config.lines[0].condition = 'dry'
    req.installed_at_water_level_mllw_ft = req.environment.water_level_mllw_ft
    before = req.model_dump_json()
    original = analyze(req)
    config = MooringConfig.model_validate_json(original.result.resolved_config.model_dump_json())
    assert all(line.paid_out_unstretched_length_ft > 0 for line in config.lines)
    assert all(line.pretension_lbf is None and line.slack_ft is None for line in config.lines)
    assert config.lines[0].condition == 'dry' and config.lines[1].condition == 'wet'
    env = req.environment.model_copy(update={'water_level_mllw_ft':level})
    anchored = analyze(req.model_copy(update={'environment':env}))
    # No installation hint is necessary once the model's explicit spans are retained.
    explicit = analyze(AnalyzeRequest.model_validate(req.model_copy(update={
        'environment':env, 'config':config, 'installed_at_water_level_mllw_ft':None}).model_dump()))
    assert explicit.status == anchored.status and explicit.validity.state == anchored.validity.state
    assert [line.tension_lbf for line in explicit.result.lines] == pytest.approx(
        [line.tension_lbf for line in anchored.result.lines], abs=1)
    assert explicit.result.min_margin.pct_wll == pytest.approx(anchored.result.min_margin.pct_wll, abs=0.1)
    assert explicit.result.resolved_config.model_dump() == config.model_dump()
    assert req.model_dump_json() == before


def test_legacy_analyze_result_omits_inactive_resolved_configuration():
    result = analyze(docking_cases()[0].analysis_request).result.model_dump()
    result.pop('resolved_config')
    assert 'resolved_config' not in AnalyzeResult.model_validate(result).model_dump()
