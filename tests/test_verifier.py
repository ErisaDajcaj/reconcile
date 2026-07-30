from datetime import date
from decimal import Decimal

from reconcile.llm import FakeLLMClient, LLMError
from reconcile.schema import CandidateMatch, OrderLine, PayoutLine, RefundLine, VerifiedMatch
from reconcile.verifier import ARITH, ROUNDING_EPSILON, VERIFIER_THRESHOLD, classify, promote


def _order(order_id, amount, currency="EUR"):
    return OrderLine(order_id=order_id, amount=Decimal(amount), currency=currency, order_date=date(2026, 7, 2))


def _payout(ref, gross, fee, net, currency="EUR"):
    return PayoutLine(ref=ref, gross_amount=Decimal(gross), fee=Decimal(fee),
                      net_amount=Decimal(net), currency=currency, line_date=date(2026, 7, 2))


def test_constants():
    assert ROUNDING_EPSILON == Decimal("0.02")
    assert VERIFIER_THRESHOLD == 0.9


def test_fee_offset_holds_when_order_is_net_and_gross_minus_fee_is_net():
    assert ARITH["fee_offset"](_order("o", "97.10"), _payout("p", "100.00", "2.90", "97.10"), []) is True


def test_fee_offset_rejects_when_gross_minus_fee_is_not_net():
    # arithmetic near-miss: net field inconsistent with gross-fee
    assert ARITH["fee_offset"](_order("o", "97.10"), _payout("p", "100.00", "3.00", "97.10"), []) is False


def test_currency_rounding_within_epsilon():
    assert ARITH["currency_rounding"](_order("o", "49.99"), _payout("p", "50.00", "1.75", "48.25"), []) is True


def test_currency_rounding_zero_gap_is_not_rounding():
    assert ARITH["currency_rounding"](_order("o", "50.00"), _payout("p", "50.00", "1.75", "48.25"), []) is False


def test_currency_rounding_beyond_epsilon_rejected():
    assert ARITH["currency_rounding"](_order("o", "49.90"), _payout("p", "50.00", "1.75", "48.25"), []) is False


def test_partial_refund_holds_when_a_matching_refund_covers_the_shortfall():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    refunds = [RefundLine(ref="ord_refund", amount=Decimal("12.00"), currency="EUR", refund_date=date(2026, 7, 2))]
    assert ARITH["partial_refund"](order, payout, refunds) is True


def test_partial_refund_rejected_without_refunds():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    assert ARITH["partial_refund"](order, payout, []) is False


def test_partial_refund_rejected_when_no_refund_matches_the_ref():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    refunds = [RefundLine(ref="ord_other", amount=Decimal("12.00"), currency="EUR", refund_date=date(2026, 7, 2))]
    assert ARITH["partial_refund"](order, payout, refunds) is False


def test_different_currency_never_holds():
    order = _order("o", "97.10", currency="USD")
    payout = _payout("p", "100.00", "2.90", "97.10", currency="EUR")
    assert ARITH["fee_offset"](order, payout, []) is False


def test_other_is_never_promotable():
    assert ARITH["other"](_order("o", "1.00"), _payout("p", "1.00", "0", "1.00"), []) is False


def test_currency_rounding_at_exact_epsilon_boundary():
    # Delta exactly equals ROUNDING_EPSILON (0.02) — boundary is inclusive.
    # order.amount = 49.98, payout.gross_amount = 50.00, delta = 0.02
    assert ARITH["currency_rounding"](_order("o", "49.98"), _payout("p", "50.00", "1.75", "48.25"), []) is True


def test_currency_rounding_rejects_mismatched_currency():
    # Currency mismatch guard: even if delta is within epsilon, should reject.
    order = _order("o", "49.99", currency="USD")
    payout = _payout("p", "50.00", "1.75", "48.25", currency="EUR")
    assert ARITH["currency_rounding"](order, payout, []) is False


def test_partial_refund_rejects_mismatched_currency_between_order_and_payout():
    # Order is EUR, payout is USD — should reject regardless of refund.
    order = _order("ord_refund", "30.00", currency="EUR")
    payout = _payout("py_2", "18.00", "0.82", "17.18", currency="USD")
    refunds = [RefundLine(ref="ord_refund", amount=Decimal("12.00"), currency="EUR", refund_date=date(2026, 7, 2))]
    assert ARITH["partial_refund"](order, payout, refunds) is False


def test_partial_refund_rejects_mismatched_refund_currency():
    # Refund currency (USD) doesn't match order currency (EUR) — should reject.
    order = _order("ord_refund", "30.00", currency="EUR")
    payout = _payout("py_2", "18.00", "0.82", "17.18", currency="EUR")
    refunds = [RefundLine(ref="ord_refund", amount=Decimal("12.00"), currency="USD", refund_date=date(2026, 7, 2))]
    assert ARITH["partial_refund"](order, payout, refunds) is False


def test_classify_returns_kind_and_confidence():
    client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.95}])
    out = classify(_order("o", "97.10"), _payout("p", "100.00", "2.90", "97.10"), [], client)
    assert out == {"kind": "fee_offset", "confidence": 0.95}


def test_classify_prompt_never_leaks_matcher_reasoning():
    client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.95}])
    classify(_order("o", "97.10"), _payout("p", "100.00", "2.90", "97.10"), [], client)
    sent = client.calls[0]["system"] + client.calls[0]["user"]
    assert "rationale" not in sent.lower()
    assert "matcher" not in sent.lower()


def test_classify_fails_closed_on_llm_error():
    assert classify(_order("o", "97.10"), _payout("p", "100.00", "2.90", "97.10"), [],
                    FakeLLMClient([LLMError("boom")])) is None


def test_classify_rejects_unknown_kind():
    assert classify(_order("o", "1"), _payout("p", "1", "0", "1"), [],
                    FakeLLMClient([{"kind": "bogus", "confidence": 0.99}])) is None


def test_classify_rejects_out_of_range_confidence():
    assert classify(_order("o", "1"), _payout("p", "1", "0", "1"), [],
                    FakeLLMClient([{"kind": "fee_offset", "confidence": 1.4}])) is None


def _candidate(order, payout, kind, confidence=0.91):
    return CandidateMatch(order=order, payout=payout, confidence=confidence,
                          rationale="matcher said so", kind=kind)


FEE_ORDER = _order("ord_fee", "97.10")
FEE_PAYOUT = _payout("py_1", "100.00", "2.90", "97.10")


def test_promotes_when_arithmetic_and_verifier_agree():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.95}])
    verified, remaining = promote([cand], [], client)
    assert remaining == []
    assert len(verified) == 1
    v = verified[0]
    assert isinstance(v, VerifiedMatch)
    assert v.kind == "fee_offset"
    assert v.matcher_confidence == 0.91
    assert v.verifier_confidence == 0.95
    assert v.deterministic_check == "fee_offset"


def test_rejects_when_arithmetic_fails_without_calling_the_model():
    # gross-fee != net -> predicate false -> no LLM call
    bad_payout = _payout("py_1", "100.00", "3.00", "97.10")
    cand = _candidate(FEE_ORDER, bad_payout, "fee_offset")
    client = FakeLLMClient([])  # would raise if called
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]
    assert client.calls == []


def test_rejects_when_verifier_disagrees_on_kind():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    client = FakeLLMClient([{"kind": "currency_rounding", "confidence": 0.99}])
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]


def test_rejects_when_verifier_below_threshold():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.5}])
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]


def test_rejects_when_verifier_errors():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    client = FakeLLMClient([LLMError("down")])
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]


def test_no_client_leaves_everything_in_needs_review():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    verified, remaining = promote([cand], [], None)
    assert verified == []
    assert remaining == [cand]


def test_other_kind_is_never_promoted():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "other")
    client = FakeLLMClient([{"kind": "other", "confidence": 0.99}])
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]
    assert client.calls == []  # 'other' predicate is False -> no model call


def test_partial_refund_promotes_only_with_a_matching_refund():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    cand = _candidate(order, payout, "partial_refund")
    refunds = [RefundLine(ref="ord_refund", amount=Decimal("12.00"), currency="EUR", refund_date=date(2026, 7, 2))]
    client = FakeLLMClient([{"kind": "partial_refund", "confidence": 0.93}])
    verified, remaining = promote([cand], refunds, client)
    assert len(verified) == 1 and remaining == []


def test_partial_refund_stays_in_review_without_refunds():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    cand = _candidate(order, payout, "partial_refund")
    client = FakeLLMClient([])  # predicate false first -> no call
    verified, remaining = promote([cand], [], client)
    assert verified == [] and remaining == [cand]
    assert client.calls == []
