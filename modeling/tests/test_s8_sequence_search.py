"""S8 / R7: bounded constraint-based line sequence proposals."""

import copy

from mooring.berthing import sequence as sq
from mooring.core.schemas.sequence_search import SequenceSearchRequest
from mooring.examples import EXAMPLES

CALM = {**EXAMPLES["mooring_sequence"]["environment"], "wind_speed_kt": 3, "wind_gust_kt": 4, "current_speed_kt": 0.1}


def req(**kw):
    b = copy.deepcopy(EXAMPLES["mooring_sequence"])
    b["environment"] = copy.deepcopy(CALM)
    b.update(kw)
    return SequenceSearchRequest(**b)


def test_default_order_unchanged_and_reported():
    r = req()
    lines = {l.line_number: l for l in r.config.lines}
    expected = [n for n in (2, 5, 3, 4, 1, 6) if n in lines] + sorted(n for n in lines if n > 6)
    assert sq.default_order(lines) == expected
    assert sq.propose_sequences(req(max_candidates=1)).default_order == expected


def test_search_is_bounded_deterministic_and_reports_truncation():
    r = req(max_candidates=3)
    a, b = sq.propose_sequences(r), sq.propose_sequences(r)
    assert a.model_dump() == b.model_dump()
    assert a.bounds.evaluated == 3 and a.bounds.max_candidates == 3
    assert a.bounds.truncated is (a.bounds.candidate_space > 3)
    assert a.review_status == "draft_unreviewed"
    assert all(p.review_status == "draft_unreviewed" and p.validity_state in ("limited", "invalid") for p in a.proposals)
    assert a.tie_breaks and any("M11" in x for x in a.limitations)


def test_proposals_report_order_states_constraints_and_are_ranked():
    res = sq.propose_sequences(req(max_candidates=4, must_precede=[(2, 5)], first_line=2))
    assert res.proposals
    rank = {"feasible_static": 0, "indeterminate": 1, "infeasible": 2}
    assert [rank[p.outcome] for p in res.proposals] == sorted(rank[p.outcome] for p in res.proposals)
    for p in res.proposals:
        assert p.line_order[0] == 2 and p.line_order.index(2) < p.line_order.index(5)
        codes = {c.code: c.satisfied for c in p.constraints}
        assert codes["MUST_PRECEDE"] is True and codes["FIRST_LINE"] is True
        assert p.intermediate_states_evaluated + p.intermediate_states_indeterminate > 0
        clean = not any(i.severity == "RED" or i.code == "PARTIAL_RESTRAINT" for i in p.issues)
        assert (p.outcome == "feasible_static") == clean
        assert [s.step for s in p.steps] == sorted(s.step for s in p.steps)


def test_unsatisfiable_constraints_evaluate_nothing_and_are_not_feasible():
    res = sq.propose_sequences(req(must_precede=[(2, 5), (5, 2)]))
    assert res.proposals == [] and res.bounds.evaluated == 0 and res.outcome != "feasible_found"


def test_unknown_line_constraint_is_unsupported():
    res = sq.propose_sequences(req(first_line=99))
    assert res.outcome == "unsupported" and res.proposals == [] and res.bounds.evaluated == 0


def test_severe_environment_never_yields_a_feasible_proposal():
    res = sq.propose_sequences(req(environment={**CALM, "wind_speed_kt": 22, "wind_gust_kt": 30}, max_candidates=3))
    assert res.outcome != "feasible_found" and all(p.outcome != "feasible_static" for p in res.proposals)
    assert res.default_order_outcome in ("infeasible", "indeterminate")


def test_crew_shortage_blocks_all_proposals():
    res = sq.propose_sequences(req(line_handling_crews=2, max_candidates=2))
    assert res.outcome != "feasible_found"
    assert all(any(i.code == "INSUFFICIENT_CREWS" and i.severity == "RED" for i in p.issues) for p in res.proposals)
