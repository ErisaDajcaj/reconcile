import json
from pathlib import Path

from reconcile.core import reconcile_files
from reconcile.evaluation import evaluate, candidate_recall, EvalMetrics
from reconcile.llm import FakeLLMClient

PAYOUTS = "tests/fixtures/payout_basic.csv"
ORDERS = "tests/fixtures/orders_basic.csv"
TRUTH = "tests/fixtures/labeled_matches.json"

FIXTURES = Path(__file__).parent / "fixtures"


def _truth():
    with open(TRUTH, encoding="utf-8") as fh:
        return json.load(fh)


def test_evaluate_computes_metrics():
    report = reconcile_files(PAYOUTS, ORDERS)
    m = evaluate(report, _truth())
    assert isinstance(m, EvalMetrics)
    # deterministic pass finds all 3 true matches, proposes nothing wrong
    assert m.precision == 1.0
    assert m.recall == 1.0
    assert m.false_match_rate == 0.0


def test_ci_gate_thresholds():
    """The gate later plans must never regress: no false matches, perfect precision."""
    report = reconcile_files(PAYOUTS, ORDERS)
    m = evaluate(report, _truth())
    assert m.false_match_rate == 0.0, "fail-closed: deterministic pass must never mis-match"
    assert m.precision == 1.0


FUZZY_PAYOUTS = FIXTURES / "payout_fuzzy.csv"
FUZZY_ORDERS = FIXTURES / "orders_fuzzy.csv"
FUZZY_TRUTH = FIXTURES / "labeled_fuzzy.json"

# Residual order matches file order: orders ord_fee/ord_refund/ord_round/ord_alone
# are indices 0-3, payouts py_1..py_4 are indices 0-3.
ALL_THREE = {
    "proposals": [
        {"order_index": 0, "payout_index": 0, "confidence": 0.94,
         "rationale": "order records the net, payout the gross", "kind": "fee_offset"},
        {"order_index": 1, "payout_index": 1, "confidence": 0.81,
         "rationale": "payout is smaller by a plausible partial refund", "kind": "partial_refund"},
        {"order_index": 2, "payout_index": 2, "confidence": 0.88,
         "rationale": "amounts differ by one rounding step", "kind": "currency_rounding"},
    ]
}


def _fuzzy_truth():
    with open(FUZZY_TRUTH, encoding="utf-8") as fh:
        return json.load(fh)


def test_no_fuzzy_proposal_is_ever_auto_confirmed():
    """The CI gate's core promise: only the deterministic pass confirms anything."""
    report = reconcile_files(FUZZY_PAYOUTS, FUZZY_ORDERS, client=FakeLLMClient([ALL_THREE]))
    assert report.matched == []
    assert len(report.needs_review) == 3
    m = evaluate(report, [])
    assert m.false_match_rate == 0.0
    assert m.precision == 1.0


def test_candidate_recall_counts_surfaced_fuzzy_pairs():
    report = reconcile_files(FUZZY_PAYOUTS, FUZZY_ORDERS, client=FakeLLMClient([ALL_THREE]))
    assert candidate_recall(report, _fuzzy_truth()) == 1.0


def test_candidate_recall_is_zero_when_nothing_is_proposed():
    empty = {"proposals": []}
    report = reconcile_files(FUZZY_PAYOUTS, FUZZY_ORDERS, client=FakeLLMClient([empty]))
    assert candidate_recall(report, _fuzzy_truth()) == 0.0


def test_candidate_recall_ignores_proposals_outside_the_ground_truth():
    """Surfacing the distractor pair must not inflate recall."""
    distractor = {
        "proposals": [
            {"order_index": 3, "payout_index": 3, "confidence": 0.55,
             "rationale": "no relation found", "kind": "other"}
        ]
    }
    report = reconcile_files(FUZZY_PAYOUTS, FUZZY_ORDERS, client=FakeLLMClient([distractor]))
    assert len(report.needs_review) == 1
    assert candidate_recall(report, _fuzzy_truth()) == 0.0
