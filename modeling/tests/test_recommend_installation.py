"""Assignment candidates also expose the exact assessed installation for later rechecks."""
import pytest

from mooring.core.schemas import RecommendRequest
from mooring.demo_cases import docking_cases
from mooring.moored import search, solver


@pytest.mark.parametrize('recheck_level', [-2.0, 4.0])
def test_resolved_candidate_reproduces_fixed_installation_at_another_tide(recheck_level):
    original = docking_cases()[0].analysis_request
    request = RecommendRequest(
        ship_class_id=original.ship_class_id, loading=original.loading, berth_id=original.berth_id,
        side_to=original.config.side_to, ship_x_ft=original.config.ship_x_ft,
        design_basis='forecast_only', forecast_env=[original.environment], tide_levels_ft=[0, 4],
        neighbors_per_line=1, max_evaluations=10, max_candidates=1,
    )
    candidate, = search.recommend(request).result.candidates
    resolved = candidate.resolved_config
    assert resolved is not None
    assert all(line.paid_out_unstretched_length_ft > 0 and line.condition == 'wet' for line in resolved.lines)
    # Assignment-only config remains available for separately planned arrival installations.
    assert all(line.paid_out_unstretched_length_ft is None for line in candidate.config.lines)
    environment = original.environment.model_copy(update={'water_level_mllw_ft': recheck_level})
    expected = solver.analyze(original.model_copy(update={
        'config': candidate.config, 'environment': environment,
        'installed_at_water_level_mllw_ft': request.tide_levels_ft[0], 'tugs': candidate.tugs,
    }))
    reproduced = solver.analyze(original.model_copy(update={
        'config': resolved, 'environment': environment, 'installed_at_water_level_mllw_ft': None,
        'tugs': candidate.tugs,
    }))
    assert reproduced.status == expected.status
    assert reproduced.validity.state == expected.validity.state
    assert [line.tension_lbf for line in reproduced.result.lines] == pytest.approx(
        [line.tension_lbf for line in expected.result.lines], rel=1e-9, abs=1e-9)
