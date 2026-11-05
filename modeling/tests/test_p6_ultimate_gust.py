"""P6/R6: modeled ultimate-load gust threshold. Capacities here are SYNTHETIC test fixtures, never sourced data.

Independent oracle: tension and strain are computed by direct equilibrium solves at a chosen wind speed v0, the capacity
basis is set from that state, and the search must bracket v0.
"""

import dataclasses

import pytest

from mooring.core.schemas.ultimate import LineUltimateCapacity, UltimateCapacityBasis, UltimateGustRequest
from mooring.examples import EXAMPLES
from mooring.mechanics import equilibrium as eq
from mooring.moored import solver
from mooring.moored import ultimate as U

BODY = EXAMPLES["mooring_analyze"]
RATIO = BODY["environment"]["wind_gust_kt"] / BODY["environment"]["wind_speed_kt"]
LINES = [ln["line_number"] for ln in BODY["config"]["lines"]]
HUGE = 1e12


def basis(caps=None, strain=None, evidence="synthetic_test_fixture"):
    caps, strain = caps or {}, strain or {}
    return UltimateCapacityBasis(
        basis_id="SYNTHETIC-TEST", evidence_status=evidence, citation="synthetic test fixture, not a source", wind_basis="test: as supplied",
        lines=[LineUltimateCapacity(line_number=n, ultimate_capacity_lbf=caps.get(n, HUGE), material_law_max_strain=strain.get(n, 10.0), factors="none (test)") for n in LINES])


def request(b=None, **kw):
    return UltimateGustRequest(**BODY, capacity_basis=b, **kw)


def state_at(v, req=None):
    req = req or request()
    system, sol0, _ = solver.solve_request(req)
    env = system.env.model_copy(update={"wind_speed_kt": v, "wind_gust_kt": v * RATIO})
    s = dataclasses.replace(system, env=env)
    sol = eq.solve(s, sol0.pose)
    assert sol.converged
    return {r.ln.line_number: (t, r.model.strain(st.length_ft), r.model.mbs_eff_lbf) for r, st, t in s.line_tensions(sol.pose)}


def test_missing_basis_is_unavailable_never_a_number():
    r = U.ultimate_gust(request())
    assert r.result.outcome == "unavailable" and r.result.governing is None and r.result.directions == []
    assert r.validity.state == "unknown" and r.validity.reasons[0].code == "ULTIMATE_CAPACITY_BASIS_MISSING"
    assert r.result.validated_rupture_prediction is False


def test_incomplete_basis_is_unavailable():
    b = basis()
    b = b.model_copy(update={"lines": b.lines[:-1]})
    r = U.ultimate_gust(request(b))
    assert r.result.outcome == "unavailable" and r.validity.reasons[0].code == "ULTIMATE_CAPACITY_INCOMPLETE"


def test_threshold_brackets_independently_computed_ultimate_and_wll_crossed_first():
    v0 = 30.0
    t3, _, mbs3 = state_at(v0)[3]
    assert t3 > mbs3 / 3.0  # fixture sanity: line 3 is past WLL at v0
    r = U.ultimate_gust(request(basis(caps={3: t3}), step_deg=90, tolerance_kt=0.1))
    a = r.result.assessed
    assert a.outcome == "threshold_found" and a.governing_line == "line-3"
    lo, hi = a.bracket_kt
    assert hi - lo <= 0.1 + 1e-9 and lo - 0.05 <= v0 <= hi + 0.05
    assert a.threshold_wind_kt == lo and a.threshold_gust_kt == pytest.approx(lo * RATIO, abs=0.01)
    assert a.governing_utilization_of_ultimate >= 1.0
    # WLL crossing is a warning that precedes (and does not stop) the search before the ultimate threshold
    assert a.wll_crossing_bracket_kt[1] < lo
    assert r.result.assessed_gust_margin_kt == pytest.approx(a.threshold_gust_kt - BODY["environment"]["wind_gust_kt"], abs=0.01)
    assert r.validity.state == "limited" and "CAPACITY_BASIS_NOT_SOURCED" in {x.code for x in r.validity.reasons}
    assert r.result.basis_id == "SYNTHETIC-TEST" and r.result.citation


def test_below_threshold_all_lines_within_capacity_above_one_line_exceeds():
    caps = {3: state_at(30.0)[3][0]}
    a = U.ultimate_gust(request(basis(caps=caps), step_deg=90)).result.assessed
    lo, hi = a.bracket_kt
    assert state_at(lo)[3][0] < caps[3] <= state_at(hi)[3][0] * (1 + 1e-6)


def test_governing_line_changes_with_capacities():
    t = state_at(30.0)
    r3 = U.ultimate_gust(request(basis(caps={3: t[3][0]}), step_deg=90)).result.assessed
    r4 = U.ultimate_gust(request(basis(caps={4: t[4][0]}), step_deg=90)).result.assessed
    assert r3.governing_line == "line-3" and r4.governing_line == "line-4"
    assert r4.threshold_wind_kt == pytest.approx(30.0, abs=0.5)  # line 4 is the only finite one: it is reached at 30 kt


def test_governing_direction_is_the_lowest_found_and_complete_flag_is_honest():
    caps = {n: state_at(30.0)[n][0] * 1.5 for n in LINES}
    res = U.ultimate_gust(request(basis(caps=caps), step_deg=90)).result
    found = [d for d in res.directions + [res.assessed] if d.threshold_wind_kt is not None]
    assert found and res.governing.threshold_wind_kt == min(d.threshold_wind_kt for d in found)
    assert res.complete == (len(found) == len(res.directions) + 1)
    if not res.complete:
        assert any("lowest found" in x for x in res.reasons)


def test_ultimate_at_zero_wind():
    t0 = state_at(0.0)[3][0]
    a = U.ultimate_gust(request(basis(caps={3: t0 * 0.9}), step_deg=90)).result.assessed
    assert a.outcome == "ultimate_at_zero_wind" and a.threshold_wind_kt == 0.0 and a.governing_line == "line-3"


def test_unsupported_material_range_is_indeterminate_and_not_extended():
    v0 = 20.0
    strain = state_at(v0)[3][1]
    r = U.ultimate_gust(request(basis(strain={3: strain}), step_deg=90)).result.assessed
    assert r.outcome == "indeterminate_material_range" and r.threshold_wind_kt is None and "line-3" in r.stop_elements
    assert r.bracket_kt[0] - 0.3 <= v0 <= r.bracket_kt[1] + 0.3


def test_other_component_failing_first_is_indeterminate():
    res = U.ultimate_gust(request(basis(), step_deg=90)).result   # capacities far above everything else
    assert res.outcome == "indeterminate" and res.governing is None
    fails = [d for d in res.directions if d.outcome == "indeterminate_component_failed_first"]
    assert fails and all(d.stop_elements and d.threshold_wind_kt is None for d in fails)


def test_search_ceiling_is_indeterminate_not_unlimited():
    r = U.ultimate_gust(request(basis(), step_deg=90, max_search_kt=10.0)).result
    ceiling = [d for d in r.directions if d.outcome == "indeterminate_search_ceiling"]
    assert ceiling and all(d.threshold_wind_kt is None and d.stop_kt == 10.0 for d in ceiling)


def test_nonconvergence_is_indeterminate(monkeypatch):
    real = eq.solve

    def flaky(system, start=None, **kw):
        sol = real(system, start, **kw) if start is not None else real(system, **kw)
        if system.env.wind_speed_kt >= 10.0:
            return dataclasses.replace(sol, converged=False)
        return sol
    monkeypatch.setattr(U.eq, "solve", flaky)
    r = U.ultimate_gust(request(basis(caps={3: 69_938.0}), step_deg=90))
    a = r.result.assessed
    assert a.outcome == "indeterminate_nonconvergence" and a.threshold_wind_kt is None and a.stop_kt == 10.0
    assert "INDETERMINATE_NONCONVERGENCE" in {x.code for x in r.validity.reasons}


def test_request_without_capacity_does_not_change_wll_envelope():
    from mooring.core.schemas import LimitEnvelopeRequest
    from mooring.moored.envelopes_real import limit_envelope
    before = limit_envelope(LimitEnvelopeRequest(**BODY, step_deg=90)).result.worst.limit_wind_kt
    U.ultimate_gust(request(basis(caps={3: 70_000.0}), step_deg=90))
    assert limit_envelope(LimitEnvelopeRequest(**BODY, step_deg=90)).result.worst.limit_wind_kt == before
