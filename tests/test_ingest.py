from decimal import Decimal
from pathlib import Path

import pytest

from reconcile.ingest import (
    MIN_MAPPING_CONFIDENCE,
    MappingError,
    infer_mapping,
    load_orders,
    load_payouts,
    read_headers,
)
from reconcile.llm import FakeLLMClient, LLMError
from reconcile.parse import ORDER_COLUMNS, PAYOUT_COLUMNS

FIXTURES = Path(__file__).parent / "fixtures"

RAW_HEADERS = ["Order Reference", "Total (EUR)", "Currency Code", "Placed On"]

GOOD_MAPPING = {
    "mapping": [
        {"field": "order_id", "header": "Order Reference"},
        {"field": "amount", "header": "Total (EUR)"},
        {"field": "currency", "header": "Currency Code"},
        {"field": "date", "header": "Placed On"},
    ],
    "confidence": 0.97,
}

RAW_PAYOUT_HEADERS = [
    "Payout Ref",
    "Gross (EUR)",
    "Fee (EUR)",
    "Net (EUR)",
    "Currency Code",
    "Paid On",
]

GOOD_PAYOUT_MAPPING = {
    "mapping": [
        {"field": "ref", "header": "Payout Ref"},
        {"field": "gross_amount", "header": "Gross (EUR)"},
        {"field": "fee", "header": "Fee (EUR)"},
        {"field": "net_amount", "header": "Net (EUR)"},
        {"field": "currency", "header": "Currency Code"},
        {"field": "date", "header": "Paid On"},
    ],
    "confidence": 0.97,
}


def _raw_payouts_csv(tmp_path):
    path = tmp_path / "raw_payouts.csv"
    path.write_text(
        "Payout Ref,Gross (EUR),Fee (EUR),Net (EUR),Currency Code,Paid On\n"
        "pay_1,10.00,0.59,9.41,eur,2026-07-01\n"
    )
    return path


def _raw_orders_csv(tmp_path):
    path = tmp_path / "raw_orders.csv"
    path.write_text(
        "Order Reference,Total (EUR),Currency Code,Placed On\n"
        "ord_1,10.00,eur,2026-07-01\n"
    )
    return path


def test_canonical_headers_short_circuit_without_calling_the_model():
    client = FakeLLMClient([])
    mapping = infer_mapping(sorted(ORDER_COLUMNS), ORDER_COLUMNS, client)
    assert mapping.fields == {f: f for f in ORDER_COLUMNS}
    assert client.calls == []


def test_infer_mapping_reads_the_agent_proposal():
    client = FakeLLMClient([GOOD_MAPPING])
    mapping = infer_mapping(RAW_HEADERS, ORDER_COLUMNS, client)
    assert mapping.fields["order_id"] == "Order Reference"
    assert mapping.fields["date"] == "Placed On"
    assert len(client.calls) == 1


def test_low_confidence_rejects_the_whole_job():
    low = dict(GOOD_MAPPING, confidence=MIN_MAPPING_CONFIDENCE - 0.01)
    with pytest.raises(MappingError, match="confidence"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([low]))


def test_unmapped_required_field_rejects_the_whole_job():
    partial = {
        "mapping": [{"field": "order_id", "header": "Order Reference"}],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="unmapped"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([partial]))


def test_hallucinated_header_is_rejected_even_with_a_valid_pair_for_the_same_field():
    invented = {
        "mapping": [
            {"field": "order_id", "header": "Order Reference"},
            {"field": "amount", "header": "Total (EUR)"},
            {"field": "currency", "header": "Currency Code"},
            {"field": "date", "header": "A Column That Does Not Exist"},
            {"field": "date", "header": "Placed On"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="unknown header"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([invented]))


def test_malformed_mapping_type_rejects_the_whole_job():
    with pytest.raises(MappingError, match="malformed"):
        infer_mapping(
            RAW_HEADERS,
            ORDER_COLUMNS,
            FakeLLMClient([{"mapping": "nope", "confidence": 0.99}]),
        )


def test_malformed_confidence_type_rejects_the_whole_job():
    with pytest.raises(MappingError, match="malformed"):
        infer_mapping(
            RAW_HEADERS,
            ORDER_COLUMNS,
            FakeLLMClient([{"mapping": GOOD_MAPPING["mapping"], "confidence": "high"}]),
        )


def test_non_dict_mapping_item_rejects_the_whole_job():
    malformed = {
        "mapping": [
            "nope",
            {"field": "order_id", "header": "Order Reference"},
            {"field": "amount", "header": "Total (EUR)"},
            {"field": "currency", "header": "Currency Code"},
            {"field": "date", "header": "Placed On"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="malformed mapping pair"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([malformed]))


def test_out_of_schema_field_name_rejects_the_whole_job():
    malformed = {
        "mapping": [
            {"field": "amuont", "header": "Total (EUR)"},
            {"field": "order_id", "header": "Order Reference"},
            {"field": "amount", "header": "Total (EUR)"},
            {"field": "currency", "header": "Currency Code"},
            {"field": "date", "header": "Placed On"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="malformed mapping pair"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([malformed]))


def test_llm_error_becomes_a_mapping_error():
    client = FakeLLMClient([LLMError("model exploded")])
    with pytest.raises(MappingError):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, client)


def test_non_canonical_headers_without_a_client_reject_the_whole_job():
    with pytest.raises(MappingError, match="no LLM client"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, None)


def test_load_orders_maps_then_parses_deterministically(tmp_path):
    rows = load_orders(_raw_orders_csv(tmp_path), FakeLLMClient([GOOD_MAPPING]))
    assert len(rows) == 1
    assert rows[0].order_id == "ord_1"
    assert rows[0].amount == Decimal("10.00")
    assert isinstance(rows[0].amount, Decimal)
    assert rows[0].currency == "EUR"


def test_load_orders_on_canonical_headers_needs_no_client():
    rows = load_orders(FIXTURES / "orders_basic.csv")
    assert [r.order_id for r in rows] == ["ord_1", "ord_2", "ord_3", "ord_missing"]


def test_confidence_above_one_rejects_the_whole_job():
    over = dict(GOOD_MAPPING, confidence=40)
    with pytest.raises(MappingError, match="range"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([over]))


def test_confidence_below_zero_rejects_the_whole_job():
    under = dict(GOOD_MAPPING, confidence=-0.01)
    with pytest.raises(MappingError, match="range"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([under]))


def test_confidence_nan_rejects_the_whole_job():
    nan = dict(GOOD_MAPPING, confidence=float("nan"))
    with pytest.raises(MappingError, match="range"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([nan]))


def test_duplicate_field_rejects_the_whole_job():
    duplicated = {
        "mapping": [
            {"field": "order_id", "header": "Order Reference"},
            {"field": "amount", "header": "Total (EUR)"},
            {"field": "amount", "header": "Currency Code"},
            {"field": "currency", "header": "Currency Code"},
            {"field": "date", "header": "Placed On"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="more than once"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([duplicated]))


def test_header_collision_across_fields_rejects_the_whole_job():
    collided = {
        "mapping": [
            {"field": "order_id", "header": "Order Reference"},
            {"field": "amount", "header": "Total (EUR)"},
            {"field": "currency", "header": "Total (EUR)"},
            {"field": "date", "header": "Placed On"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="more than one field"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([collided]))


def test_non_string_field_fails_closed_instead_of_crashing():
    malformed = {
        "mapping": [
            {"field": ["order_id"], "header": "Order Reference"},
            {"field": "amount", "header": "Total (EUR)"},
            {"field": "currency", "header": "Currency Code"},
            {"field": "date", "header": "Placed On"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="malformed mapping pair"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([malformed]))


def test_non_string_header_fails_closed_instead_of_crashing():
    malformed = {
        "mapping": [
            {"field": "order_id", "header": ["Order Reference"]},
            {"field": "amount", "header": "Total (EUR)"},
            {"field": "currency", "header": "Currency Code"},
            {"field": "date", "header": "Placed On"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="malformed mapping pair"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([malformed]))


def test_confidence_exactly_at_threshold_is_accepted():
    at_threshold = dict(GOOD_MAPPING, confidence=MIN_MAPPING_CONFIDENCE)
    mapping = infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([at_threshold]))
    assert mapping.fields["order_id"] == "Order Reference"


def test_min_mapping_confidence_constant_is_pinned():
    assert MIN_MAPPING_CONFIDENCE == 0.9


def test_min_confidence_override_above_one_rejects():
    with pytest.raises(ValueError, match="range"):
        infer_mapping(
            RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([GOOD_MAPPING]), min_confidence=1.5
        )


def test_min_confidence_override_below_zero_rejects():
    with pytest.raises(ValueError, match="range"):
        infer_mapping(
            RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([GOOD_MAPPING]), min_confidence=-0.01
        )


def test_min_confidence_override_nan_rejects():
    with pytest.raises(ValueError, match="range"):
        infer_mapping(
            RAW_HEADERS,
            ORDER_COLUMNS,
            FakeLLMClient([GOOD_MAPPING]),
            min_confidence=float("nan"),
        )


def test_min_confidence_override_takes_effect():
    below_default = dict(GOOD_MAPPING, confidence=MIN_MAPPING_CONFIDENCE - 0.01)
    client = FakeLLMClient([below_default])
    mapping = infer_mapping(
        RAW_HEADERS, ORDER_COLUMNS, client, min_confidence=MIN_MAPPING_CONFIDENCE - 0.1
    )
    assert mapping.fields["order_id"] == "Order Reference"

    below_override = dict(GOOD_MAPPING, confidence=MIN_MAPPING_CONFIDENCE - 0.15)
    with pytest.raises(MappingError, match="confidence"):
        infer_mapping(
            RAW_HEADERS,
            ORDER_COLUMNS,
            FakeLLMClient([below_override]),
            min_confidence=MIN_MAPPING_CONFIDENCE - 0.1,
        )


def test_load_payouts_maps_then_parses_deterministically(tmp_path):
    rows = load_payouts(_raw_payouts_csv(tmp_path), FakeLLMClient([GOOD_PAYOUT_MAPPING]))
    assert len(rows) == 1
    assert rows[0].ref == "pay_1"
    assert rows[0].gross_amount == Decimal("10.00")
    assert rows[0].fee == Decimal("0.59")
    assert rows[0].net_amount == Decimal("9.41")
    assert isinstance(rows[0].fee, Decimal)
    assert isinstance(rows[0].net_amount, Decimal)
    assert rows[0].currency == "EUR"


def test_load_payouts_on_canonical_headers_needs_no_client():
    rows = load_payouts(FIXTURES / "payout_basic.csv")
    assert [r.ref for r in rows] == ["ord_1", "ord_2", "ord_3", "ord_ghost"]


def test_read_headers_rejects_a_duplicate_column_name(tmp_path):
    path = tmp_path / "dup.csv"
    path.write_text(
        "ref,gross_amount,fee,net_amount,currency,date,fee\n"
        "pay_1,10.00,0.59,9.41,EUR,2026-07-01,0.59\n"
    )
    with pytest.raises(MappingError, match="'fee'"):
        read_headers(path)


def test_load_payouts_rejects_a_duplicate_source_column_even_on_the_short_circuit(tmp_path):
    """A repeated header name must fail closed even when the canonical set is a
    subset of the (duplicated) headers -- otherwise csv.DictReader silently
    reads the field from the wrong (last) column."""
    path = tmp_path / "dup.csv"
    path.write_text(
        "ref,gross_amount,fee,net_amount,currency,date,fee\n"
        "pay_1,10.00,0.59,9.41,EUR,2026-07-01,0.59\n"
    )
    with pytest.raises(MappingError, match="'fee'"):
        load_payouts(path)


def test_payout_fee_and_net_amount_mapped_to_same_header_rejects_the_whole_job():
    collided = {
        "mapping": [
            {"field": "ref", "header": "Payout Ref"},
            {"field": "gross_amount", "header": "Gross (EUR)"},
            {"field": "fee", "header": "Net (EUR)"},
            {"field": "net_amount", "header": "Net (EUR)"},
            {"field": "currency", "header": "Currency Code"},
            {"field": "date", "header": "Paid On"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="more than one field"):
        infer_mapping(RAW_PAYOUT_HEADERS, PAYOUT_COLUMNS, FakeLLMClient([collided]))
