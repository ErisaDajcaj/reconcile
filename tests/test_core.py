from reconcile.core import reconcile_files

PAYOUTS = "tests/fixtures/payout_basic.csv"
ORDERS = "tests/fixtures/orders_basic.csv"


def test_reconcile_files_end_to_end():
    report = reconcile_files(PAYOUTS, ORDERS)
    matched_ids = sorted(o.order_id for o, _ in report.matched)
    assert matched_ids == ["ord_1", "ord_2", "ord_3"]
    assert [o.order_id for o in report.unmatched_orders] == ["ord_missing"]
    assert [p.ref for p in report.unmatched_payouts] == ["ord_ghost"]
