import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from .schema import ColumnMapping, PayoutLine, OrderLine

PAYOUT_COLUMNS = {"ref", "gross_amount", "fee", "net_amount", "currency", "date"}
ORDER_COLUMNS = {"order_id", "amount", "currency", "date"}


class CsvSchemaError(ValueError):
    """Raised when a CSV lacks a column the mapping points at. Fail closed: no partial parse."""


def identity_mapping(fields) -> ColumnMapping:
    """The canonical-headers case: every field is named after itself."""
    return ColumnMapping(fields={f: f for f in fields})


def _require_mapped_columns(header: set[str], mapping: ColumnMapping, required: set[str], path: Path) -> None:
    missing = sorted(f for f in required if mapping.fields.get(f) not in header)
    if missing:
        raise CsvSchemaError(f"{path}: no column feeds required field(s) {missing}")


def _rows(path):
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = set(reader.fieldnames or [])
        yield header, path
        for row in reader:
            yield row, path


def _cell(row: dict, mapping: ColumnMapping, field: str) -> str:
    return row[mapping.fields[field]]


def parse_payouts(path, mapping: ColumnMapping | None = None) -> list[PayoutLine]:
    mapping = mapping or identity_mapping(PAYOUT_COLUMNS)
    gen = _rows(path)
    header, p = next(gen)
    _require_mapped_columns(header, mapping, PAYOUT_COLUMNS, p)
    out = []
    for row, _ in gen:
        out.append(
            PayoutLine(
                ref=_cell(row, mapping, "ref").strip(),
                gross_amount=Decimal(_cell(row, mapping, "gross_amount")),
                fee=Decimal(_cell(row, mapping, "fee")),
                net_amount=Decimal(_cell(row, mapping, "net_amount")),
                currency=_cell(row, mapping, "currency").strip().upper(),
                line_date=date.fromisoformat(_cell(row, mapping, "date").strip()),
            )
        )
    return out


def parse_orders(path, mapping: ColumnMapping | None = None) -> list[OrderLine]:
    mapping = mapping or identity_mapping(ORDER_COLUMNS)
    gen = _rows(path)
    header, p = next(gen)
    _require_mapped_columns(header, mapping, ORDER_COLUMNS, p)
    out = []
    for row, _ in gen:
        out.append(
            OrderLine(
                order_id=_cell(row, mapping, "order_id").strip(),
                amount=Decimal(_cell(row, mapping, "amount")),
                currency=_cell(row, mapping, "currency").strip().upper(),
                order_date=date.fromisoformat(_cell(row, mapping, "date").strip()),
            )
        )
    return out
