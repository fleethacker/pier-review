"""Impossible tug assistance cannot turn a computed static limit into an operational claim."""
import pytest

from mooring import refdata
from mooring.core import store
from mooring.core.schemas import AnalyzeRequest, LimitEnvelopeRequest, TugAssignment
from mooring.demo_cases import docking_cases
from mooring.moored import solver


def request(assignments):
    return docking_cases()[0].analysis_request.model_copy(update={'tugs': assignments})


def tug(**updates):
    return TugAssignment(**({'tug_id': 'T4', 'push_point_id': 'PP-FWD-P', 'mode': 'push', 'force_lbf': 100} | updates))


@pytest.mark.parametrize('assignments', [
    [tug(force_lbf=refdata.tug('T4').bollard_pull_ahead_lbf + 1)],
    [tug(mode='pull', force_lbf=refdata.tug('T4').bollard_pull_astern_lbf + 1)],
    [tug(tug_id='unknown')], [tug(), tug()],
    [tug(), tug(tug_id='T1')], [tug(), tug(push_point_id='PP-AFT-P')],
    [tug(mode='standby', force_lbf=100)],
])
def test_invalid_assistance_is_red_even_with_rules_disabled(assignments):
    req = request(assignments)
    response = solver.analyze(req)
    assert response.status == 'RED' and response.validity.state == 'invalid'
    assert any(r.code == 'TUG_ASSIGNMENT_INVALID' for r in response.validity.reasons)
    assert solver.analyze_full(req, run_rules=False)[2].state == 'invalid'
    envelope = solver.limit_envelope(LimitEnvelopeRequest(**req.model_dump(), step_deg=90))
    assert envelope.status == 'RED' and envelope.validity.state == 'invalid'
    assert all(p.outcome == 'invalid_inputs' and p.limit_wind_kt is None and p.limit_gust_kt is None
               for p in envelope.result.points)


def test_tug_catalog_is_captured_in_resolved_manifest_and_stays_unqualified():
    result = solver.analyze(request([tug()]))
    assert result.validity.state == 'limited'
    assert any(r.code == 'TUG_DATA_UNQUALIFIED' for r in result.validity.reasons)
    assert any(r.kind == 'tug' and r.id == 'T4' and r.revision for r in result.manifest.records)
    resolved = store.load_snapshot(result.manifest.resolved_inputs_hash)
    assert resolved['tug_specs']['T4']['bollard_pull_ahead_lbf'] == refdata.tug('T4').bollard_pull_ahead_lbf
