import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from reconcile.core import reconcile_files
from reconcile.evaluation import evaluate, candidate_recall, verified_metrics, EvalMetrics
from reconcile.llm import FakeLLMClient
from reconcile.matching import ReconcileReport
from reconcile.schema import OrderLine, PayoutLine, VerifiedMatch

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


def _vm(order_id, ref, kind="fee_offset"):
    order = OrderLine(order_id=order_id, amount=Decimal("1"), currency="EUR", order_date=date(2026, 7, 2))
    payout = PayoutLine(ref=ref, gross_amount=Decimal("1"), fee=Decimal("0"),
                        net_amount=Decimal("1"), currency="EUR", line_date=date(2026, 7, 2))
    return VerifiedMatch(order=order, payout=payout, kind=kind, matcher_confidence=0.9,
                         verifier_confidence=0.95, deterministic_check=kind, rationale="x")


def test_verified_metrics_all_correct_is_perfect():
    report = ReconcileReport(verified=[_vm("ord_fee", "py_1")])
    truth = [{"order_id": "ord_fee", "payout_ref": "py_1", "kind": "fee_offset"}]
    m = verified_metrics(report, truth)
    assert m == EvalMetrics(precision=1.0, recall=1.0, false_match_rate=0.0)


def test_verified_metrics_flags_a_wrong_promotion():
    report = ReconcileReport(verified=[_vm("ord_x", "py_wrong")])
    truth = [{"order_id": "ord_fee", "payout_ref": "py_1", "kind": "fee_offset"}]
    m = verified_metrics(report, truth)
    assert m.precision == 0.0
    assert m.false_match_rate == 1.0


def test_verified_metrics_empty_report_is_vacuously_clean():
    m = verified_metrics(ReconcileReport(), [])
    assert m.false_match_rate == 0.0
    assert m.precision == 1.0


FIX = Path(__file__).parent / "fixtures"


def _fuzzy_matcher_response():
    # order indices follow orders_fuzzy.csv row order (ord_fee=0, ord_refund=1,
    # ord_round=2, ord_alone=3); payout indices follow payout_fuzzy.csv
    # (py_1=0, py_2=1, py_3=2, py_4=3). Deterministic pass matches nothing here.
    return {"proposals": [
        {"order_index": 0, "payout_index": 0, "confidence": 0.9, "rationale": "net vs gross", "kind": "fee_offset"},
        {"order_index": 1, "payout_index": 1, "confidence": 0.9, "rationale": "refund shortfall", "kind": "partial_refund"},
        {"order_index": 2, "payout_index": 2, "confidence": 0.9, "rationale": "rounding step", "kind": "currency_rounding"},
    ]}


def test_verified_tier_has_zero_false_match_rate_on_fakes():
    truth = json.loads((FIX / "labeled_verified.json").read_text())
    matcher = FakeLLMClient([_fuzzy_matcher_response()])
    # one verdict per proposal, in proposal order
    verifier = FakeLLMClient([
        {"kind": "fee_offset", "confidence": 0.95},
        {"kind": "partial_refund", "confidence": 0.93},
        {"kind": "currency_rounding", "confidence": 0.94},
    ])
    report = reconcile_files(
        FIX / "payout_fuzzy.csv", FIX / "orders_fuzzy.csv", FIX / "refunds.csv",
        client=matcher, verifier_client=verifier,
    )
    m = verified_metrics(report, truth)
    # THE GATE: the promoted tier admits zero wrong matches.
    assert m.false_match_rate == 0.0
    assert m.precision == 1.0
    assert len(report.verified) == 3
    assert report.matched == []  # deterministic tier untouched


def test_adversarial_near_miss_never_promotes():
    # matcher claims fee_offset on a pair whose gross-fee != net.
    # Build the near-miss inline so the fixture stays self-describing.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "p.csv"
        p.write_text("ref,gross_amount,fee,net_amount,currency,date\n"
                     "py_x,100.00,3.00,97.10,EUR,2026-07-02\n", encoding="utf-8")
        o = Path(d) / "o.csv"
        o.write_text("order_id,amount,currency,date\n"
                     "ord_x,97.10,EUR,2026-07-02\n", encoding="utf-8")
        matcher = FakeLLMClient([{"proposals": [
            {"order_index": 0, "payout_index": 0, "confidence": 0.99,
             "rationale": "looks like a fee", "kind": "fee_offset"}]}])
        verifier = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.99}])
        report = reconcile_files(p, o, client=matcher, verifier_client=verifier)
        # arithmetic predicate is false (100.00 - 3.00 != 97.10) -> never promoted
        assert report.verified == []
        assert len(report.needs_review) == 1
