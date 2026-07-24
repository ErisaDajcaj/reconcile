from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class PayoutLine:
    ref: str
    gross_amount: Decimal
    fee: Decimal
    net_amount: Decimal
    currency: str
    line_date: date


@dataclass(frozen=True)
class OrderLine:
    order_id: str
    amount: Decimal
    currency: str
    order_date: date


@dataclass(frozen=True)
class ColumnMapping:
    """Canonical field name -> source CSV header. The dict is treated as read-only."""

    fields: dict[str, str]
