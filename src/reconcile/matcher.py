"""Matcher agent: proposes fuzzy pairings over the deterministic residual.

The agent is never given a task where it could emit money. It sees already-typed
lines and answers with indices; code resolves those indices back to the real
objects and drops anything it cannot fully validate. Nothing here is confirmed --
every proposal lands in the human-review queue.
"""

from .llm import LLMClient, LLMError
from .schema import CandidateMatch, OrderLine, PayoutLine

KINDS = ("fee_offset", "partial_refund", "currency_rounding", "other")

_SYSTEM = (
    "You pair unmatched orders with unmatched payout lines that an exact-match "
    "pass could not reconcile. Reference every line ONLY by its index. Never "
    "output an amount and never recompute a number. Propose a pair only when a "
    "concrete explanation applies: fee_offset (the order records the net, the "
    "payout the gross), partial_refund (the payout is smaller because part was "
    "refunded), currency_rounding (the two differ by a rounding step), otherwise "
    "'other'. Use each order index and each payout index at most once. Nothing "
    "you propose is confirmed automatically: a human reviews every pair."
)

_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order_index": {"type": "integer"},
                    "payout_index": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                },
                "required": [
                    "order_index",
                    "payout_index",
                    "confidence",
                    "rationale",
                    "kind",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["proposals"],
    "additionalProperties": False,
}


def _render(orders: list[OrderLine], payouts: list[PayoutLine]) -> str:
    lines = ["Unmatched orders:"]
    for i, o in enumerate(orders):
        lines.append(
            f"  [{i}] id={o.order_id} amount={o.amount} {o.currency} date={o.order_date}"
        )
    lines.append("Unmatched payout lines:")
    for i, p in enumerate(payouts):
        lines.append(
            f"  [{i}] ref={p.ref} gross={p.gross_amount} fee={p.fee} "
            f"net={p.net_amount} {p.currency} date={p.line_date}"
        )
    return "\n".join(lines)


def _is_index(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def propose_matches(
    unmatched_orders: list[OrderLine],
    unmatched_payouts: list[PayoutLine],
    client: LLMClient | None,
) -> list[CandidateMatch]:
    if client is None or not unmatched_orders or not unmatched_payouts:
        return []

    try:
        out = client.structured(
            system=_SYSTEM,
            user=_render(unmatched_orders, unmatched_payouts),
            schema=_PROPOSAL_SCHEMA,
        )
    except LLMError:
        # Fail closed: the residual simply gets no candidates. Safe, because
        # nothing here would have been auto-confirmed anyway.
        return []

    proposals = out.get("proposals")
    if not isinstance(proposals, list):
        return []

    seen_orders: set[int] = set()
    seen_payouts: set[int] = set()
    candidates: list[CandidateMatch] = []

    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        order_index = proposal.get("order_index")
        payout_index = proposal.get("payout_index")
        if not _is_index(order_index) or not _is_index(payout_index):
            continue
        if not 0 <= order_index < len(unmatched_orders):
            continue
        if not 0 <= payout_index < len(unmatched_payouts):
            continue
        if order_index in seen_orders or payout_index in seen_payouts:
            continue
        confidence = proposal.get("confidence")
        if not _is_number(confidence) or not 0.0 <= confidence <= 1.0:
            continue
        rationale = proposal.get("rationale")
        kind = proposal.get("kind")
        if not isinstance(rationale, str) or kind not in KINDS:
            continue

        seen_orders.add(order_index)
        seen_payouts.add(payout_index)
        candidates.append(
            CandidateMatch(
                order=unmatched_orders[order_index],
                payout=unmatched_payouts[payout_index],
                confidence=float(confidence),
                rationale=rationale,
                kind=kind,
            )
        )
    return candidates
