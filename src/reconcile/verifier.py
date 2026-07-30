"""The verifier: the fail-closed gate that promotes a fuzzy candidate.

A candidate is promoted only when a pure-code arithmetic predicate keyed by
its `kind` holds AND an independent LLM -- blind to the matcher's reasoning --
re-classifies the raw pair to the same kind above threshold. Every other path
leaves the candidate in `needs_review`.
"""

from decimal import Decimal

from .llm import LLMClient, LLMError
from .matcher import KINDS
from .schema import CandidateMatch, OrderLine, PayoutLine, RefundLine, VerifiedMatch

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

_SYSTEM = (
    "You are given exactly one order line and one payout line that an exact-match "
    "pass could not reconcile, plus any refund lines on record. Decide, on your own, "
    "which single relationship best explains the pair. Reference lines only by their "
    "labels; never output or recompute an amount. Answer with one kind: fee_offset "
    "(the order records the net, the payout the gross), partial_refund (a refund "
    "explains the shortfall), currency_rounding (they differ only by a rounding "
    "step), or other. Give a confidence on a 0.0-1.0 scale (0.0 = none, 1.0 = "
    "certain), never a percentage."
)

_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "confidence": {"type": "number"},
    },
    "required": ["kind", "confidence"],
    "additionalProperties": False,
}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _render_pair(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> str:
    lines = [
        "Order:",
        f"  id={order.order_id} amount={order.amount} {order.currency} date={order.order_date}",
        "Payout:",
        f"  ref={payout.ref} gross={payout.gross_amount} fee={payout.fee} "
        f"net={payout.net_amount} {payout.currency} date={payout.line_date}",
    ]
    if refunds:
        lines.append("Refunds on record:")
        for r in refunds:
            lines.append(f"  ref={r.ref} amount={r.amount} {r.currency} date={r.refund_date}")
    else:
        lines.append("Refunds on record: none")
    return "\n".join(lines)


def classify(
    order: OrderLine, payout: PayoutLine, refunds: list[RefundLine], client: LLMClient
) -> dict | None:
    try:
        out = client.structured(
            system=_SYSTEM, user=_render_pair(order, payout, refunds), schema=_VERDICT_SCHEMA
        )
    except LLMError:
        return None
    kind = out.get("kind")
    confidence = out.get("confidence")
    if kind not in KINDS:
        return None
    if not _is_number(confidence) or not 0.0 <= confidence <= 1.0:
        return None
    return {"kind": kind, "confidence": float(confidence)}


def promote(
    candidates: list[CandidateMatch],
    refunds: list[RefundLine],
    client: LLMClient | None,
) -> tuple[list[VerifiedMatch], list[CandidateMatch]]:
    """Partition candidates into (verified, still-needs-review).

    A candidate is promoted only when its arithmetic predicate holds AND an
    independent verifier agrees on the kind above threshold. Every other path
    leaves it in the review queue.
    """
    verified: list[VerifiedMatch] = []
    remaining: list[CandidateMatch] = []

    for c in candidates:
        predicate = ARITH.get(c.kind)
        if predicate is None or not predicate(c.order, c.payout, refunds):
            remaining.append(c)
            continue
        if client is None:
            remaining.append(c)
            continue
        verdict = classify(c.order, c.payout, refunds, client)
        if verdict is None or verdict["kind"] != c.kind or verdict["confidence"] < VERIFIER_THRESHOLD:
            remaining.append(c)
            continue
        verified.append(
            VerifiedMatch(
                order=c.order,
                payout=c.payout,
                kind=c.kind,
                matcher_confidence=c.confidence,
                verifier_confidence=verdict["confidence"],
                deterministic_check=c.kind,
                rationale=c.rationale,
            )
        )
    return verified, remaining
