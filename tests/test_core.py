from reconcile.core import reconcile_files
from reconcile.llm import AnthropicClient, FakeLLMClient

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


class _ExplodingSDKMessages:
    def create(self, **kwargs):
        raise ConnectionError("could not reach the API")


class _ExplodingSDKClient:
    def __init__(self) -> None:
        self.messages = _ExplodingSDKMessages()


def _exploding_matcher_client() -> AnthropicClient:
    """A real AnthropicClient whose underlying SDK call always raises.

    Built without touching the actual `anthropic` package or a network --
    stands in for a real API outage (connection error, rate limit, ...).
    """
    adapter = object.__new__(AnthropicClient)
    adapter._client = _ExplodingSDKClient()
    adapter._model = "test-model"
    return adapter


def test_a_real_api_failure_still_yields_a_complete_report():
    """The seam (llm.py) must turn any SDK exception into LLMError, and the
    matcher's fail-closed drop must absorb it: the deterministic matches
    already computed must not be lost because the matcher agent errored.
    """
    report = reconcile_files(PAYOUTS, ORDERS, client=_exploding_matcher_client())
    assert sorted(o.order_id for o, _ in report.matched) == ["ord_1", "ord_2", "ord_3"]
    assert [o.order_id for o in report.unmatched_orders] == ["ord_missing"]
    assert [p.ref for p in report.unmatched_payouts] == ["ord_ghost"]
    assert report.needs_review == []
