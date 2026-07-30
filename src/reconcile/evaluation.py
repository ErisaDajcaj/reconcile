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

    CI does assert this metric's value, but only against `FakeLLMClient` --
    that gates the *metric implementation* against a deterministic fake, not
    model quality. It never gates a merge on how good the real model is: that
    would require live model calls, which are non-deterministic and cost
    money, and stays confined to `scripts/eval_agents.py`. The CI merge gate
    is `evaluate`, which scores auto-confirmed (deterministic-only) matches.
    """
    surfaced = {(c.order.order_id, c.payout.ref) for c in report.needs_review}
    truth = {(t["order_id"], t["payout_ref"]) for t in fuzzy_truth}
    if not truth:
        return 1.0
    return len(surfaced & truth) / len(truth)


def verified_metrics(report: ReconcileReport, verified_truth: list[dict]) -> EvalMetrics:
    """Precision / recall / false-match-rate over the verifier-promoted tier.

    The `false_match_rate` returned here is the plan's headline gate: CI asserts
    it is 0.0 (and precision 1.0) on `FakeLLMClient`. Scores `report.verified`,
    never `report.matched` (which `evaluate` scores).
    """
    proposed = {(v.order.order_id, v.payout.ref) for v in report.verified}
    truth_set = {(t["order_id"], t["payout_ref"]) for t in verified_truth}

    tp = len(proposed & truth_set)
    fp = len(proposed - truth_set)
    fn = len(truth_set - proposed)

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    false_match_rate = fp / len(proposed) if proposed else 0.0

    return EvalMetrics(precision=precision, recall=recall, false_match_rate=false_match_rate)
