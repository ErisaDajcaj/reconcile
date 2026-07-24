from decimal import Decimal
from datetime import date

from reconcile.schema import PayoutLine, OrderLine
from reconcile.matching import deterministic_match, ReconcileReport


def _order(oid, amt):
    return OrderLine(oid, Decimal(amt), "EUR", date(2026, 7, 1))


def _payout(ref, gross):
    g = Decimal(gross)
    return PayoutLine(ref, g, Decimal("0.50"), g - Decimal("0.50"), "EUR", date(2026, 7, 1))


def test_exact_matches_pair_up():
    orders = [_order("ord_1", "10.00"), _order("ord_2", "25.00")]
    payouts = [_payout("ord_1", "10.00"), _payout("ord_2", "25.00")]
    report = deterministic_match(orders, payouts)
    assert len(report.matched) == 2
    assert report.unmatched_orders == []
    assert report.unmatched_payouts == []


def test_amount_mismatch_is_not_matched():
    orders = [_order("ord_1", "10.00")]
    payouts = [_payout("ord_1", "9.00")]  # same ref, different amount
    report = deterministic_match(orders, payouts)
    assert report.matched == []
    assert report.unmatched_orders == orders
    assert report.unmatched_payouts == payouts


def test_residual_lines_are_reported_unmatched():
    orders = [_order("ord_1", "10.00"), _order("ord_missing", "12.00")]
    payouts = [_payout("ord_1", "10.00"), _payout("ord_ghost", "5.00")]
    report = deterministic_match(orders, payouts)
    assert len(report.matched) == 1
    assert [o.order_id for o in report.unmatched_orders] == ["ord_missing"]
    assert [p.ref for p in report.unmatched_payouts] == ["ord_ghost"]


def test_each_payout_consumed_at_most_once_idempotent():
    orders = [_order("ord_1", "10.00"), _order("ord_1", "10.00")]  # duplicate order id
    payouts = [_payout("ord_1", "10.00")]  # only one payout
    report = deterministic_match(orders, payouts)
    assert len(report.matched) == 1                      # not double-matched
    assert len(report.unmatched_orders) == 1
    # re-running yields identical counts (idempotent)
    again = deterministic_match(orders, payouts)
    assert (len(again.matched), len(again.unmatched_orders), len(again.unmatched_payouts)) == \
           (len(report.matched), len(report.unmatched_orders), len(report.unmatched_payouts))


def test_report_starts_with_an_empty_review_queue():
    from reconcile.matching import ReconcileReport

    report = ReconcileReport()
    assert report.needs_review == []
