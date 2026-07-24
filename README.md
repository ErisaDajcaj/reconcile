# Reconcile

Agentic reconciliation & verification for Stripe payouts. Matches a Stripe payout
export against a seller's expected-orders CSV, flags discrepancies, and — its
defining promise — **never auto-confirms a match it isn't sure about**.

_"Reconcile" is a provisional working name (see `docs/design/`)._

## Status

Plan 2 (this milestone): the deterministic core from Plan 1, plus two LLM agents —
an ingest agent that maps arbitrary CSV headers onto the canonical schema, and a
matcher agent that proposes fuzzy pairings over the residual the exact-match pass
could not reconcile. The matcher sees monetary values but never outputs or recomputes them; the ingest agent sees only header names, never data values. **No fuzzy
match is auto-confirmed**: proposals go to a human-review queue. Promotion (the
fail-closed verifier), the web UI, and deploy follow in later plans.
See `docs/design/2026-07-20-plan-2-agent-layer-design.md`.

## Develop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # deterministic core + tests, zero runtime deps
pytest                       # includes the eval gate; no API key needed
```

The agents are an optional extra — the safety layer is not:

```bash
pip install -e ".[llm]"
ANTHROPIC_API_KEY=... python scripts/eval_agents.py   # live model-quality eval, off the CI gate
```
