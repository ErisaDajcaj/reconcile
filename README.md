# Reconcile

Agentic reconciliation & verification for Stripe payouts. Matches a Stripe payout
export against a seller's expected-orders CSV, flags discrepancies, and — its
defining promise — **never auto-confirms a match it isn't sure about**.

_"Reconcile" is a provisional working name (see `docs/design/`)._

## Status

Plan 1 (this milestone): deterministic exact-match core + eval harness in CI.
Agents (ingest / matcher / fail-closed verifier), web UI, and deploy follow in
later plans. See `docs/design/2026-07-19-reconcile-design.md`.

## Develop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
