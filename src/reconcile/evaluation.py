from dataclasses import dataclass

from .matching import ReconcileReport


@dataclass(frozen=True)
class EvalMetrics:
    precision: float
    recall: float
    false_match_rate: float


def evaluate(report: ReconcileReport, truth: list[dict]) -> EvalMetrics:
    proposed = {(o.order_id, p.ref) for o, p in report.matched}
    truth_set = {(t["order_id"], t["payout_ref"]) for t in truth}

    tp = len(proposed & truth_set)
    fp = len(proposed - truth_set)
    fn = len(truth_set - proposed)

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    false_match_rate = fp / len(proposed) if proposed else 0.0

    return EvalMetrics(precision=precision, recall=recall, false_match_rate=false_match_rate)


def candidate_recall(report: ReconcileReport, fuzzy_truth: list[dict]) -> float:
    """Share of true fuzzy pairs surfaced in `needs_review`.

    Deliberately measured, never gated: it scores model quality, which is
    non-deterministic and costs money. The CI gate stays on `evaluate`, which
    scores auto-confirmed matches only.
    """
    surfaced = {(c.order.order_id, c.payout.ref) for c in report.needs_review}
    truth = {(t["order_id"], t["payout_ref"]) for t in fuzzy_truth}
    if not truth:
        return 1.0
    return len(surfaced & truth) / len(truth)
