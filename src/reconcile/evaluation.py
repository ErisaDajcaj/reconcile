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
