"""Fender probabilities compare energy; the fields ending in _lbf must report reaction force."""
from types import SimpleNamespace

import pytest

from mooring.core.schemas import ExceedanceRequest
from mooring.demo_cases import docking_cases
from mooring.mechanics import Pose
from mooring.moored import risk


@pytest.mark.parametrize('energy,force,probability', [(2000,500,1), (500,2000,0)])
def test_fender_percentiles_are_force_while_exceedance_remains_energy_based(monkeypatch, energy, force, probability):
    # Fixed synthetic demands bracket a 1,500 ft·lbf rating. No physical curve is inferred.
    fender = SimpleNamespace(model=SimpleNamespace(fender_id='fixture-fender', rated_energy_ftlbf=1500,
                                                  energy=lambda compression: energy, force=lambda compression: force))
    system = SimpleNamespace(ship=SimpleNamespace(fittings=[]), berth=SimpleNamespace(fittings=[]),
        line_tensions=lambda pose: [], fender_loads=lambda pose: [(fender,1,None)])
    with monkeypatch.context() as patch:
        patch.setattr(risk.eq, 'solve', lambda system, warm: SimpleNamespace(converged=True, pose=Pose()))
        demand = risk._eval_env(system, Pose(), 5)
    monkeypatch.setattr(risk, '_eval_env', lambda *args: demand)
    baseline = docking_cases()[0].analysis_request
    response = risk.exceedance(ExceedanceRequest(**baseline.model_dump(), n_samples=10, seed=7))
    result = response.result.elements[0]
    assert result.element_id == 'fixture-fender'
    assert result.p_exceed_wll == probability
    assert result.p_exceed_mbs is None
    assert result.tension_p50_lbf == force
    assert result.tension_p95_lbf == force
