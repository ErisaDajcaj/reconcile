from decimal import Decimal

import pytest

from reconcile.ingest import (
    MIN_MAPPING_CONFIDENCE,
    MappingError,
    infer_mapping,
    load_orders,
)
from reconcile.llm import FakeLLMClient, LLMError
from reconcile.parse import ORDER_COLUMNS

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


def test_hallucinated_header_is_treated_as_unmapped():
    invented = {
        "mapping": [
            {"field": "order_id", "header": "Order Reference"},
            {"field": "amount", "header": "Total (EUR)"},
            {"field": "currency", "header": "Currency Code"},
            {"field": "date", "header": "A Column That Does Not Exist"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="unmapped"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([invented]))


def test_malformed_agent_response_rejects_the_whole_job():
    with pytest.raises(MappingError, match="malformed"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([{"mapping": "nope"}]))


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
    rows = load_orders("tests/fixtures/orders_basic.csv")
    assert [r.order_id for r in rows] == ["ord_1", "ord_2", "ord_3", "ord_missing"]
