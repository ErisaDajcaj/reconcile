from .ingest import load_orders, load_payouts, load_refunds
from .llm import LLMClient
from .matcher import propose_matches
from .matching import ReconcileReport, deterministic_match
from .verifier import promote


def reconcile_files(
    payout_csv,
    orders_csv,
    refunds_csv=None,
    client: LLMClient | None = None,
    *,
    ingest_client: LLMClient | None = None,
    verifier_client: LLMClient | None = None,
) -> ReconcileReport:
    """Ingest -> deterministic match -> fuzzy proposals -> fail-closed verifier.

    `client` drives the matcher. `ingest_client` drives header mapping and
    `verifier_client` drives promotion; both default to `client`. `refunds_csv`
    is optional -- absent, `partial_refund` candidates can never be promoted and
    stay in `needs_review`. With every client unset this is the Plan 1 pipeline
    exactly: canonical headers required, no proposals, nothing verified.
    """
    if ingest_client is None:
        ingest_client = client
    if verifier_client is None:
        verifier_client = client

    payouts = load_payouts(payout_csv, ingest_client)
    orders = load_orders(orders_csv, ingest_client)
    refunds = load_refunds(refunds_csv, ingest_client) if refunds_csv is not None else []

    report = deterministic_match(orders, payouts)
    candidates = propose_matches(report.unmatched_orders, report.unmatched_payouts, client)
    verified, remaining = promote(candidates, refunds, verifier_client)
    report.verified = verified
    report.needs_review = remaining
    return report
