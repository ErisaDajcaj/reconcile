from datetime import date
from decimal import Decimal

from reconcile.schema import OrderLine, PayoutLine, RefundLine
from reconcile.verifier import ARITH, ROUNDING_EPSILON, VERIFIER_THRESHOLD


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
