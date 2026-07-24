from dataclasses import dataclass, field

from .schema import CandidateMatch, PayoutLine, OrderLine


@dataclass
class ReconcileReport:
    matched: list[tuple[OrderLine, PayoutLine]] = field(default_factory=list)
    unmatched_orders: list[OrderLine] = field(default_factory=list)
    unmatched_payouts: list[PayoutLine] = field(default_factory=list)
    # Candidate pairings over the residual. Never auto-confirmed: promoting one
    # into `matched` is the Plan 3 verifier's job.
    needs_review: list[CandidateMatch] = field(default_factory=list)


def _key(order_id: str, amount, currency: str) -> tuple:
    return (order_id, amount, currency)


def deterministic_match(orders: list[OrderLine], payouts: list[PayoutLine]) -> ReconcileReport:
    """Exact match on (id/ref, amount, currency). Each payout line consumed at most once."""
    # index payout lines by exact key, preserving order for deterministic consumption
    buckets: dict[tuple, list[PayoutLine]] = {}
    for p in payouts:
        buckets.setdefault(_key(p.ref, p.gross_amount, p.currency), []).append(p)

    report = ReconcileReport()
    consumed: set[int] = set()  # id() of payout objects already matched

    for o in orders:
        candidates = buckets.get(_key(o.order_id, o.amount, o.currency), [])
        match = next((p for p in candidates if id(p) not in consumed), None)
        if match is not None:
            consumed.add(id(match))
            report.matched.append((o, match))
        else:
            report.unmatched_orders.append(o)

    report.unmatched_payouts = [p for p in payouts if id(p) not in consumed]
    return report
