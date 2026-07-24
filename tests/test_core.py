from reconcile.core import reconcile_files
from reconcile.llm import FakeLLMClient

PAYOUTS = "tests/fixtures/payout_basic.csv"
ORDERS = "tests/fixtures/orders_basic.csv"


def test_reconcile_files_end_to_end():
    report = reconcile_files(PAYOUTS, ORDERS)
    matched_ids = sorted(o.order_id for o, _ in report.matched)
    assert matched_ids == ["ord_1", "ord_2", "ord_3"]
    assert [o.order_id for o in report.unmatched_orders] == ["ord_missing"]
    assert [p.ref for p in report.unmatched_payouts] == ["ord_ghost"]


def test_client_none_preserves_the_plan_1_pipeline():
    report = reconcile_files(PAYOUTS, ORDERS)
    assert report.needs_review == []
    assert sorted(o.order_id for o, _ in report.matched) == ["ord_1", "ord_2", "ord_3"]


def test_candidates_land_in_needs_review_and_never_in_matched():
    payload = {
        "proposals": [
            {
                "order_index": 0,
                "payout_index": 0,
                "confidence": 0.88,
                "rationale": "amounts differ by a plausible fee",
                "kind": "fee_offset",
            }
        ]
    }
    report = reconcile_files(PAYOUTS, ORDERS, client=FakeLLMClient([payload]))
    assert sorted(o.order_id for o, _ in report.matched) == ["ord_1", "ord_2", "ord_3"]
    assert len(report.needs_review) == 1
    assert report.needs_review[0].order.order_id == "ord_missing"
    assert report.needs_review[0].payout.ref == "ord_ghost"

    # Verify that candidates land in needs_review as an overlay on the residual,
    # not a filter — proposed pairs must remain in the residual lists.
    assert [o.order_id for o in report.unmatched_orders] == ["ord_missing"]
    assert [p.ref for p in report.unmatched_payouts] == ["ord_ghost"]
