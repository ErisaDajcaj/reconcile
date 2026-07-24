"""Live model-quality eval, deliberately OUTSIDE the CI gate.

Model calls are non-deterministic and cost money, so they must never decide
whether a merge lands. The CI gate stays deterministic (FakeLLMClient, false
match rate 0); this script reports how good the models actually are.

Usage:
    pip install -e ".[llm]"
    ANTHROPIC_API_KEY=... python scripts/eval_agents.py
"""

import json
import os
import sys

from reconcile.core import reconcile_files
from reconcile.evaluation import candidate_recall
from reconcile.ingest import load_orders
from reconcile.llm import INGEST_MODEL, MATCHER_MODEL, AnthropicClient

FUZZY_PAYOUTS = "tests/fixtures/payout_fuzzy.csv"
FUZZY_ORDERS = "tests/fixtures/orders_fuzzy.csv"
RAW_HEADER_ORDERS = "tests/fixtures/orders_fuzzy_raw_headers.csv"
FUZZY_TRUTH = "tests/fixtures/labeled_fuzzy.json"


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set - skipping the live eval.")
        return 0

    with open(FUZZY_TRUTH, encoding="utf-8") as fh:
        truth = json.load(fh)

    ingest = AnthropicClient(INGEST_MODEL)
    matcher = AnthropicClient(MATCHER_MODEL)

    report = reconcile_files(
        FUZZY_PAYOUTS, FUZZY_ORDERS, client=matcher, ingest_client=ingest
    )
    print(f"matcher  {MATCHER_MODEL}")
    print(f"  candidate_recall  {candidate_recall(report, truth):.2f}")
    print(f"  auto-confirmed    {len(report.matched)}  (must be 0 on this fixture)")
    for c in report.needs_review:
        print(
            f"  {c.order.order_id} ~ {c.payout.ref}  {c.kind}  "
            f"{c.confidence:.2f}  {c.rationale}"
        )

    orders = load_orders(RAW_HEADER_ORDERS, ingest)
    print(f"ingest   {INGEST_MODEL}")
    print(f"  non-canonical headers mapped, {len(orders)} order lines parsed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
