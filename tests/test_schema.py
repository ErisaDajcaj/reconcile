from datetime import date
from decimal import Decimal

import pytest

from reconcile.schema import PayoutLine, OrderLine, RefundLine, VerifiedMatch


def test_payout_line_is_frozen_and_typed():
    p = PayoutLine(
        ref="ord_1",
        gross_amount=Decimal("10.00"),
        fee=Decimal("0.59"),
        net_amount=Decimal("9.41"),
        currency="EUR",
        line_date=date(2026, 7, 1),
    )
    assert p.ref == "ord_1"
    assert p.gross_amount == Decimal("10.00")
    try:
        p.ref = "changed"  # frozen -> should raise
        assert False, "PayoutLine must be frozen"
    except AttributeError:
        pass


def test_order_line_holds_decimal_amount():
    o = OrderLine(
        order_id="ord_1",
        amount=Decimal("10.00"),
        currency="EUR",
        order_date=date(2026, 7, 1),
    )
    assert o.amount == Decimal("10.00")
    assert isinstance(o.amount, Decimal)


def test_column_mapping_is_frozen():
    from dataclasses import FrozenInstanceError

    from reconcile.schema import ColumnMapping

    mapping = ColumnMapping(fields={"order_id": "Order Reference"})
    assert mapping.fields["order_id"] == "Order Reference"
    with pytest.raises(FrozenInstanceError):
        mapping.fields = {}


def test_refund_line_is_a_frozen_typed_record():
    r = RefundLine(ref="ord_refund", amount=Decimal("12.00"), currency="EUR", refund_date=date(2026, 7, 2))
    assert r.ref == "ord_refund"
    assert r.amount == Decimal("12.00")
    assert r.currency == "EUR"
    assert r.refund_date == date(2026, 7, 2)
    try:
        r.amount = Decimal("0")
        assert False, "RefundLine should be frozen"
    except AttributeError:
        pass


def test_verified_match_carries_its_audit_trail():
    order = OrderLine(order_id="ord_fee", amount=Decimal("97.10"), currency="EUR", order_date=date(2026, 7, 2))
    payout = PayoutLine(ref="py_1", gross_amount=Decimal("100.00"), fee=Decimal("2.90"),
                        net_amount=Decimal("97.10"), currency="EUR", line_date=date(2026, 7, 2))
    v = VerifiedMatch(order=order, payout=payout, kind="fee_offset",
                      matcher_confidence=0.91, verifier_confidence=0.95,
                      deterministic_check="fee_offset", rationale="net vs gross")
    assert v.kind == "fee_offset"
    assert v.matcher_confidence == 0.91
    assert v.verifier_confidence == 0.95
    assert v.deterministic_check == "fee_offset"
    assert v.rationale == "net vs gross"
