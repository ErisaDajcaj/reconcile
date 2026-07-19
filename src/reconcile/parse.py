import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from .schema import PayoutLine, OrderLine

PAYOUT_COLUMNS = {"ref", "gross_amount", "fee", "net_amount", "currency", "date"}
ORDER_COLUMNS = {"order_id", "amount", "currency", "date"}


class CsvSchemaError(ValueError):
    """Raised when a CSV is missing required columns. Fail closed: no partial parse."""


def _require_columns(header: set[str], required: set[str], path: Path) -> None:
    missing = required - header
    if missing:
        raise CsvSchemaError(f"{path}: missing required columns {sorted(missing)}")


def _rows(path):
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = set(reader.fieldnames or [])
        yield header, path
        for row in reader:
            yield row, path


def parse_payouts(path) -> list[PayoutLine]:
    gen = _rows(path)
    header, p = next(gen)
    _require_columns(header, PAYOUT_COLUMNS, p)
    out = []
    for row, _ in gen:
        out.append(
            PayoutLine(
                ref=row["ref"].strip(),
                gross_amount=Decimal(row["gross_amount"]),
                fee=Decimal(row["fee"]),
                net_amount=Decimal(row["net_amount"]),
                currency=row["currency"].strip().upper(),
                line_date=date.fromisoformat(row["date"].strip()),
            )
        )
    return out


def parse_orders(path) -> list[OrderLine]:
    gen = _rows(path)
    header, p = next(gen)
    _require_columns(header, ORDER_COLUMNS, p)
    out = []
    for row, _ in gen:
        out.append(
            OrderLine(
                order_id=row["order_id"].strip(),
                amount=Decimal(row["amount"]),
                currency=row["currency"].strip().upper(),
                order_date=date.fromisoformat(row["date"].strip()),
            )
        )
    return out
