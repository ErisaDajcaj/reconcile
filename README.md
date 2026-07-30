# Reconcile

**Agentic reconciliation for Stripe payouts — that never auto-confirms a match it isn't sure about.**

Stripe pays sellers in aggregated, net payouts: bundled across orders, minus fees,
offset by refunds and disputes, shifted by settlement timing. So a payout almost
never maps 1:1 to a seller's expected orders, and reconciling by hand in a
spreadsheet gets fragile fast. Reconcile matches a Stripe payout export against the
seller's own expected-orders CSV, flags every discrepancy, and routes anything
uncertain to a human-review queue — **fail-closed by design.**

> _"Reconcile" is a provisional working name (see [`docs/design/`](docs/design/))._

## The governing principle

**Deterministic where deterministic wins; agents only on the residual ambiguity; an
independent verifier as the gate.** An LLM is never used for what is a hash-join.
Knowing where *not* to put the model is half the value.

```
payout.csv ─┐   ingest agent
            ├─► (header → schema,  ─►  deterministic pass  ─►  matched
orders.csv ─┘    fails closed)         (pure code, hash-join)  (exact only)
                                              │
                                              ▼
                                           residual  ─►  matcher agent  ─►  needs_review
                                                         (fuzzy, by index,   (nothing
                                                          confidence+reason)   auto-confirmed)
                                                                                    │
                                                            [Plan 3] verifier ──────┘
                                                                (built)
```

Everything down to `needs_review` is shipped. The verifier that promotes proposals
out of the review queue is Plan 3: a fuzzy candidate is promoted only when a
deterministic arithmetic predicate holds and an independent verifier LLM (blind to
the matcher's reasoning) agrees on the kind above threshold; otherwise it stays in
review.

## Status — building in public

| Milestone | Scope | State |
|---|---|---|
| **Plan 1** | Deterministic exact-match core + eval harness in CI | ✅ **shipped** |
| **Plan 2** | LLM ingest agent + fuzzy matcher agent, behind a vendor-neutral seam | ✅ **shipped** |
| Plan 3 | Independent fail-closed verifier (the only path out of `needs_review`) | ✅ **shipped** |
| Plan 4 | Web UI + deployed URL | designed |
| Plan 5 | Per-job observability (traces, cost, latency, match-rate) | designed |

Design docs: [Plan 1 architecture](docs/design/2026-07-19-reconcile-design.md) ·
[Plan 2 agent layer](docs/design/2026-07-20-plan-2-agent-layer-design.md) ·
[Plan 3 verifier](docs/design/2026-07-30-plan-3-verifier-design.md). Plans land
incrementally, each behind a green eval gate.

## What's actually enforced

Each claim below is pinned to a test, not to intent.

- **Money is `Decimal` end-to-end**, parsed from the string — never through a float.
- **Parsing fails closed.** A missing column, or a CSV carrying two columns of the
  same name, rejects the whole job. No partial results — and no silently reading the
  fee out of the net-amount column.
- **The ingest agent cannot widen the blast radius.** It returns *header names only*,
  never data values, and its mapping is rejected outright — not best-effort repaired —
  on low confidence, an unknown header, a duplicate field, or two fields claiming the
  same column.
- **No fuzzy proposal is ever auto-confirmed.** `matched` holds only deterministic
  exact matches; agent proposals land in `needs_review` and stay in the residual. A
  dedicated test asserts the fuzzy path cannot contaminate `matched`.
- **The agents cannot take the pipeline down with them.** Every vendor error is
  converted at the seam, so a model or network failure degrades to "no proposals" —
  and the deterministic matches already computed still come back.
- **CI gates on precision, not on match rate.** The eval harness runs on every PR and
  fails if `false_match_rate > 0` or `precision < 1.0` — for a money-verification
  tool, precision is the metric that matters. Candidate recall is *measured and
  reported, never gated*: a fuzzy-recall threshold would create pressure to confirm.

## Install

The safety layer has **zero runtime dependencies**. The agents are an optional extra:
the full suite is green with the Anthropic SDK absent from the environment, which is
how it runs in CI.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # deterministic core + tests. No API key, no network.
pytest                       # includes the CI eval gate
```

```bash
pip install -e ".[llm]"                                # adds the Anthropic SDK
ANTHROPIC_API_KEY=... python scripts/eval_agents.py    # live model-quality eval, off the CI gate
```

Python 3.12 · `pytest` eval harness · GitHub Actions CI gate.
