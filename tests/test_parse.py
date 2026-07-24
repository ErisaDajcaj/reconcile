from decimal import Decimal
from datetime import date

import pytest

from reconcile.parse import parse_payouts, parse_orders, CsvSchemaError, identity_mapping
from reconcile.schema import ColumnMapping

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


def test_parse_orders_with_a_non_canonical_mapping(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text(
        "Order Reference,Total (EUR),Currency Code,Placed On\n"
        "ord_1,10.00,eur,2026-07-01\n"
    )
    mapping = ColumnMapping(
        fields={
            "order_id": "Order Reference",
            "amount": "Total (EUR)",
            "currency": "Currency Code",
            "date": "Placed On",
        }
    )
    rows = parse_orders(raw, mapping)
    assert rows[0].order_id == "ord_1"
    assert rows[0].amount == Decimal("10.00")
    assert isinstance(rows[0].amount, Decimal)
    assert rows[0].currency == "EUR"
    assert rows[0].order_date == date(2026, 7, 1)


def test_mapping_pointing_at_a_missing_column_fails_closed(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text("Order Reference,Total (EUR)\nord_1,10.00\n")
    mapping = ColumnMapping(
        fields={
            "order_id": "Order Reference",
            "amount": "Total (EUR)",
            "currency": "Currency Code",
            "date": "Placed On",
        }
    )
    with pytest.raises(CsvSchemaError):
        parse_orders(raw, mapping)


def test_identity_mapping_names_every_field_after_itself():
    mapping = identity_mapping({"order_id", "amount"})
    assert mapping.fields == {"order_id": "order_id", "amount": "amount"}
