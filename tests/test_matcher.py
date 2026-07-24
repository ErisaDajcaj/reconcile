from datetime import date
from decimal import Decimal

from reconcile.llm import FakeLLMClient, LLMError
from reconcile.matcher import CandidateMatch, propose_matches
from reconcile.schema import OrderLine, PayoutLine

ORDERS = [
    OrderLine(order_id="ord_fee", amount=Decimal("97.10"), currency="EUR", order_date=date(2026, 7, 2)),
    OrderLine(order_id="ord_alone", amount=Decimal("88.00"), currency="EUR", order_date=date(2026, 7, 2)),
]
PAYOUTS = [
    PayoutLine(
        ref="py_1",
        gross_amount=Decimal("100.00"),
        fee=Decimal("2.90"),
        net_amount=Decimal("97.10"),
        currency="EUR",
        line_date=date(2026, 7, 2),
    ),
]


def _proposal(**overrides) -> dict:
    base = {
        "order_index": 0,
        "payout_index": 0,
        "confidence": 0.91,
        "rationale": "the order records the net, the payout the gross",
        "kind": "fee_offset",
    }
    base.update(overrides)
    return {"proposals": [base]}


def test_proposal_is_resolved_back_to_the_real_line_objects():
    client = FakeLLMClient([_proposal()])
    candidates = propose_matches(ORDERS, PAYOUTS, client)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, CandidateMatch)
    assert candidate.order is ORDERS[0]
    assert candidate.payout is PAYOUTS[0]
    assert candidate.kind == "fee_offset"
    assert candidate.confidence == 0.91


def test_no_client_means_no_proposals():
    assert propose_matches(ORDERS, PAYOUTS, None) == []


def test_empty_residual_never_calls_the_model():
    client = FakeLLMClient([])
    assert propose_matches([], PAYOUTS, client) == []
    assert propose_matches(ORDERS, [], client) == []
    assert client.calls == []


def test_out_of_range_index_is_dropped():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(payout_index=7)])) == []
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(order_index=-1)])) == []


def test_unknown_kind_is_dropped():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(kind="vibes")])) == []


def test_out_of_band_confidence_is_dropped():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(confidence=1.4)])) == []


def test_non_integer_index_is_dropped():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(order_index="0")])) == []


def test_a_line_is_proposed_at_most_once():
    payload = {
        "proposals": [
            {"order_index": 0, "payout_index": 0, "confidence": 0.9, "rationale": "a", "kind": "fee_offset"},
            {"order_index": 1, "payout_index": 0, "confidence": 0.8, "rationale": "b", "kind": "other"},
        ]
    }
    candidates = propose_matches(ORDERS, PAYOUTS, FakeLLMClient([payload]))
    assert [c.order.order_id for c in candidates] == ["ord_fee"]


def test_llm_error_leaves_the_residual_without_candidates():
    client = FakeLLMClient([LLMError("model exploded")])
    assert propose_matches(ORDERS, PAYOUTS, client) == []


def test_malformed_payload_leaves_the_residual_without_candidates():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([{"proposals": "nope"}])) == []


def test_the_prompt_never_asks_the_model_for_an_amount():
    client = FakeLLMClient([_proposal()])
    propose_matches(ORDERS, PAYOUTS, client)
    schema = client.calls[0]["schema"]
    item_properties = schema["properties"]["proposals"]["items"]["properties"]
    assert set(item_properties) == {
        "order_index",
        "payout_index",
        "confidence",
        "rationale",
        "kind",
    }
