from .ingest import load_orders, load_payouts
from .llm import LLMClient
from .matcher import propose_matches
from .matching import ReconcileReport, deterministic_match


def reconcile_files(
    payout_csv,
    orders_csv,
    client: LLMClient | None = None,
    *,
    ingest_client: LLMClient | None = None,
) -> ReconcileReport:
    """Ingest -> deterministic match -> fuzzy proposals over the residual.

    `client` drives the matcher; `ingest_client` drives header mapping and
    defaults to `client` (they differ only when the two agents run on different
    models). With both unset this is the Plan 1 pipeline exactly: canonical
    headers required, no proposals, nothing confirmed that was not exact.
    """
    if ingest_client is None:
        ingest_client = client

    payouts = load_payouts(payout_csv, ingest_client)
    orders = load_orders(orders_csv, ingest_client)

    report = deterministic_match(orders, payouts)
    report.needs_review = propose_matches(
        report.unmatched_orders, report.unmatched_payouts, client
    )
    return report
