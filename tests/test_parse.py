from decimal import Decimal
from datetime import date

import pytest

from reconcile.parse import parse_payouts, parse_orders, CsvSchemaError

PAYOUTS = "tests/fixtures/payout_basic.csv"
ORDERS = "tests/fixtures/orders_basic.csv"


def test_parse_payouts_returns_typed_rows():
    rows = parse_payouts(PAYOUTS)
    assert len(rows) == 4
    first = rows[0]
    assert first.ref == "ord_1"
    assert first.gross_amount == Decimal("10.00")
    assert first.fee == Decimal("0.59")
    assert first.net_amount == Decimal("9.41")
    assert first.currency == "EUR"
    assert first.line_date == date(2026, 7, 1)


def test_parse_orders_returns_typed_rows():
    rows = parse_orders(ORDERS)
    assert len(rows) == 4
    assert rows[0].order_id == "ord_1"
    assert rows[0].amount == Decimal("10.00")
    assert isinstance(rows[0].amount, Decimal)


def test_missing_column_fails_closed(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("order_id,amount\nord_1,10.00\n")  # no currency/date
    with pytest.raises(CsvSchemaError):
        parse_orders(bad)
