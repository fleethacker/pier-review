"""Gap: S8 sequence search with the real static solver: default order not feasible while another order is, determinism, bounds.

Cases are found by scanning line subsets of the repo `mooring_sequence` example in a calm environment, so no solver
output is hard-coded except the structure asserted after a deterministic scan.
"""
import copy
import itertools

import pytest

from mooring.berthing import sequence as sq
from mooring.core.schemas.sequence_search import SequenceSearchRequest
from mooring.examples import EXAMPLES

CALM = {**EXAMPLES["mooring_sequence"]["environment"], "wind_speed_kt": 3, "wind_gust_kt": 4, "current_speed_kt": 0.1}


def req(lines=None, **kw):
    b = copy.deepcopy(EXAMPLES["mooring_sequence"])
    b["environment"] = copy.deepcopy(CALM)
    if lines is not None:
        b["config"]["lines"] = [ln for ln in b["config"]["lines"] if ln["line_number"] in lines]
    b.update(kw)
    return SequenceSearchRequest(**b)


def scan_pairs():
    nums = [ln["line_number"] for ln in EXAMPLES["mooring_sequence"]["config"]["lines"]]
    for pair in itertools.combinations(nums, 2):
        yield pair, sq.propose_sequences(req(pair, max_candidates=2, max_proposals=2))


@pytest.fixture(scope="module")
def pair_scan():
    return list(scan_pairs())


def test_scan_finds_case_where_default_is_not_feasible_but_another_order_is(pair_scan):
    hits = [(pair, r) for pair, r in pair_scan if r.default_order_outcome != "feasible_static"
            and any(p.outcome == "feasible_static" for p in r.proposals)]
    assert hits, "no repo-fixture pair of lines yields a non-default feasible order"
    for pair, r in hits:
        assert r.outcome == "feasible_found"
        best = r.proposals[0]
        assert best.outcome == "feasible_static" and best.rank == 1 and not best.is_default_order
        assert best.line_order != r.default_order and sorted(best.line_order) == sorted(pair)
        default = next(p for p in r.proposals if p.is_default_order)
        assert default.outcome == r.default_order_outcome != "feasible_static"
        assert not any(i.severity == "RED" or i.code == "PARTIAL_RESTRAINT" for i in best.issues)
        assert any(i.code == "PARTIAL_RESTRAINT" for i in default.issues) or any(i.severity == "RED" for i in default.issues)


def test_pinned_case_lines_2_and_4_default_indeterminate_reverse_feasible():
    r = sq.propose_sequences(req((2, 4), max_candidates=2))
    assert r.default_order == [2, 4] and r.default_order_outcome == "indeterminate"
    assert [(p.line_order, p.outcome) for p in r.proposals] == [([4, 2], "feasible_static"), ([2, 4], "indeterminate")]
    assert r.bounds.candidate_space == 2 and r.bounds.evaluated == 2 and r.bounds.truncated is False


def test_scan_outcome_classes_are_all_exercised(pair_scan):
    assert {r.outcome for _, r in pair_scan} >= {"feasible_found", "indeterminate_only", "no_feasible_order"}


def test_constraint_can_force_the_non_default_feasible_order():
    # Forcing line 4 first excludes the indeterminate default [2, 4] and only the feasible order remains.
    r = sq.propose_sequences(req((2, 4), first_line=4))
    assert r.outcome == "feasible_found" and [p.line_order for p in r.proposals] == [[4, 2]]
    assert r.default_order_outcome == "not_evaluated"


def test_same_request_twice_is_identical():
    a = sq.propose_sequences(req((2, 3, 4), max_candidates=4, max_proposals=4))
    b = sq.propose_sequences(req((2, 3, 4), max_candidates=4, max_proposals=4))
    assert a.model_dump() == b.model_dump()
    assert [p.rank for p in a.proposals] == list(range(1, len(a.proposals) + 1))


def test_max_candidates_bounds_evaluation_and_reports_truncation():
    full = sq.propose_sequences(req((2, 3, 4), max_candidates=6, max_proposals=10))
    assert full.bounds.candidate_space == 6 and full.bounds.evaluated == 6 and full.bounds.truncated is False
    assert len(full.proposals) == 6
    cut = sq.propose_sequences(req((2, 3, 4), max_candidates=2, max_proposals=10))
    assert cut.bounds.evaluated == 2 and cut.bounds.truncated is True and len(cut.proposals) == 2
    assert cut.bounds.admissible_candidates == 6
    # The first candidates are the default order and its reverse (documented deterministic enumeration).
    assert {tuple(p.line_order) for p in cut.proposals} == {tuple(cut.default_order), tuple(reversed(cut.default_order))}


def test_truncated_search_without_feasible_order_is_budget_limited_not_no_feasible():
    r = sq.propose_sequences(req((2, 3, 5), max_candidates=1))
    assert r.bounds.truncated and r.outcome == "budget_limited"
    assert all(p.outcome != "feasible_static" for p in r.proposals)


def test_max_proposals_caps_returned_list_but_not_evaluation():
    r = sq.propose_sequences(req((2, 3, 4), max_candidates=6, max_proposals=2))
    assert r.bounds.evaluated == 6 and len(r.proposals) == 2


def test_request_bounds_are_validated():
    from pydantic import ValidationError
    for kw in ({"max_candidates": 0}, {"max_candidates": 61}, {"max_proposals": 0}, {"max_proposals": 11}):
        with pytest.raises(ValidationError):
            req(**kw)
