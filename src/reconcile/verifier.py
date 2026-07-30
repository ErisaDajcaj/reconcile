"""The verifier: the fail-closed gate that promotes a fuzzy candidate.

A candidate is promoted only when a pure-code arithmetic predicate keyed by
its `kind` holds AND an independent LLM -- blind to the matcher's reasoning --
re-classifies the raw pair to the same kind above threshold. Every other path
leaves the candidate in `needs_review`.
"""

from decimal import Decimal

from .matcher import KINDS
from .schema import OrderLine, PayoutLine, RefundLine

# Largest tolerated rounding drift. Above it, not a currency-rounding case.
ROUNDING_EPSILON = Decimal("0.02")
# Minimum verifier confidence to promote. Mirrors the ingest-confidence floor.
VERIFIER_THRESHOLD = 0.9


def _fee_offset(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> bool:
    return (
        order.currency == payout.currency
        and order.amount == payout.net_amount
        and payout.gross_amount - payout.fee == payout.net_amount
    )


def _currency_rounding(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> bool:
    if order.currency != payout.currency:
        return False
    delta = abs(order.amount - payout.gross_amount)
    return Decimal(0) < delta <= ROUNDING_EPSILON


def _partial_refund(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> bool:
    if order.currency != payout.currency:
        return False
    return any(
        r.ref == order.order_id
        and r.currency == order.currency
        and payout.gross_amount + r.amount == order.amount
        for r in refunds
    )


def _other(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> bool:
    return False


ARITH = {
    "fee_offset": _fee_offset,
    "currency_rounding": _currency_rounding,
    "partial_refund": _partial_refund,
    "other": _other,
}

assert set(ARITH) == set(KINDS), "ARITH must cover exactly the matcher KINDS"
