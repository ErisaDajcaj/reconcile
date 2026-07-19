import json

from reconcile.core import reconcile_files
from reconcile.evaluation import evaluate, EvalMetrics

PAYOUTS = "tests/fixtures/payout_basic.csv"
ORDERS = "tests/fixtures/orders_basic.csv"
TRUTH = "tests/fixtures/labeled_matches.json"


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
