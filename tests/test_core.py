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


# -- Ingest agent genuinely invoked: non-canonical headers on the orders side. --
# Every other fixture in this file has canonical headers, so `infer_mapping`'s
# deterministic short-circuit fires and the ingest agent is never called --
# a regression in call ordering, or in `ingest_client = client` defaulting,
# would pass every other test here. Pairs the raw-header orders fixture
# (exercises ingest mapping) with the canonical fuzzy payouts fixture (so the
# payout side still short-circuits and the residual lands on the matcher).

RAW_HEADER_ORDERS = "tests/fixtures/orders_fuzzy_raw_headers.csv"
FUZZY_PAYOUTS = "tests/fixtures/payout_fuzzy.csv"

_ORDER_MAPPING = {
    "mapping": [
        {"field": "order_id", "header": "Order Reference"},
        {"field": "amount", "header": "Total (EUR)"},
        {"field": "currency", "header": "Currency Code"},
        {"field": "date", "header": "Placed On"},
    ],
    "confidence": 0.97,
}

_PROPOSALS = {
    "proposals": [
        {"order_index": 0, "payout_index": 0, "confidence": 0.94,
         "rationale": "order records the net, payout the gross", "kind": "fee_offset"},
        {"order_index": 1, "payout_index": 1, "confidence": 0.81,
         "rationale": "payout is smaller by a plausible partial refund", "kind": "partial_refund"},
        {"order_index": 2, "payout_index": 2, "confidence": 0.88,
         "rationale": "amounts differ by one rounding step", "kind": "currency_rounding"},
    ]
}


def test_ingest_agent_is_actually_invoked_for_non_canonical_headers():
    client = FakeLLMClient([_ORDER_MAPPING, _PROPOSALS])
    report = reconcile_files(FUZZY_PAYOUTS, RAW_HEADER_ORDERS, client=client)

    # Both agents were called, in pipeline order: ingest maps headers before
    # anything else runs, then the matcher proposes over the residual.
    # (Verifier is also called but fails closed when responses run out.)
    assert len(client.calls) >= 2
    assert "mapping" in client.calls[0]["schema"]["properties"]
    assert "proposals" in client.calls[1]["schema"]["properties"]

    # The mapping was actually used: order ids came from the mapped header,
    # not a raw/failed parse, and the deterministic pass ran on real values.
    assert report.matched == []  # order ids (ord_*) never equal payout refs (py_*)
    assert sorted(o.order_id for o in report.unmatched_orders) == [
        "ord_alone", "ord_fee", "ord_refund", "ord_round",
    ]
    assert sorted(p.ref for p in report.unmatched_payouts) == ["py_1", "py_2", "py_3", "py_4"]

    proposed = {(c.order.order_id, c.payout.ref) for c in report.needs_review}
    assert proposed == {("ord_fee", "py_1"), ("ord_refund", "py_2"), ("ord_round", "py_3")}


def test_verifier_promotes_a_fee_offset_candidate(tmp_path):
    payout = tmp_path / "p.csv"
    payout.write_text(
        "ref,gross_amount,fee,net_amount,currency,date\n"
        "py_1,100.00,2.90,97.10,EUR,2026-07-02\n", encoding="utf-8")
    orders = tmp_path / "o.csv"
    orders.write_text(
        "order_id,amount,currency,date\n"
        "ord_fee,97.10,EUR,2026-07-02\n", encoding="utf-8")
    # matcher proposes the pair; verifier confirms fee_offset
    matcher_client = FakeLLMClient([{
        "proposals": [{"order_index": 0, "payout_index": 0, "confidence": 0.9,
                       "rationale": "net vs gross", "kind": "fee_offset"}]
    }])
    verifier_client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.95}])
    report = reconcile_files(payout, orders, client=matcher_client, verifier_client=verifier_client)
    assert len(report.verified) == 1
    assert report.verified[0].kind == "fee_offset"
    assert report.needs_review == []
    assert report.matched == []  # promotion never touches the deterministic tier


def test_verifier_client_defaults_to_client(tmp_path):
    # With only `client` given, it drives BOTH matcher and verifier. Feed the
    # single client a matcher response then a verdict, in call order.
    payout = tmp_path / "p.csv"
    payout.write_text(
        "ref,gross_amount,fee,net_amount,currency,date\n"
        "py_1,100.00,2.90,97.10,EUR,2026-07-02\n", encoding="utf-8")
    orders = tmp_path / "o.csv"
    orders.write_text(
        "order_id,amount,currency,date\n"
        "ord_fee,97.10,EUR,2026-07-02\n", encoding="utf-8")
    client = FakeLLMClient([
        {"proposals": [{"order_index": 0, "payout_index": 0, "confidence": 0.9,
                        "rationale": "net vs gross", "kind": "fee_offset"}]},
        {"kind": "fee_offset", "confidence": 0.95},
    ])
    report = reconcile_files(payout, orders, client=client)
    assert len(report.verified) == 1  # verifier_client defaulted to client


def test_plan_1_path_unchanged_no_verified(tmp_path):
    # no client at all -> pure deterministic, empty verified
    report = reconcile_files(PAYOUTS, ORDERS)
    assert report.verified == []
