from datetime import date
from decimal import Decimal

from reconcile.schema import PayoutLine, OrderLine


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
