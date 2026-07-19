# Reconcile — Design Spec (v1)

> **Status:** approved for planning · **Date:** 2026-07-19 · **Author:** Erisa Dajcaj (with StepUp)
> **Name:** "Reconcile" is a **provisional working name** — collides with an existing "Reconcra"; to be revisited before public launch. It does not block the build.

---

## 1. One-liner

An agentic reconciliation service that matches **Stripe payouts** against a seller's **own expected orders**, flags every discrepancy, and — its defining promise — **never auto-confirms a match it isn't sure about**: uncertain matches route to a human-review queue. Trust is the product; the reconciliation is the vehicle.

## 2. Problem

Stripe pays sellers in **aggregated, net** payouts — bundled across orders, minus fees, offset by refunds and disputes, shifted by settlement timing. So a payout almost never maps 1:1 to the seller's list of expected orders. Today sellers reconcile this by exporting CSVs and matching by hand in a spreadsheet, which reportedly becomes fragile and untrustworthy past ~100–150 orders/month. Stripe's own free *Payout Reconciliation* report ties a payout to the bank deposit **internally by category** — it does **not** reconcile a payout against the seller's *external* order list. That specific gap is the wedge.

## 3. Target users

Indie developers, small SaaS businesses, and small e-commerce sellers on Stripe who currently reconcile payouts manually. Builder is a solo backend engineer (payments/banking background) building in public at zero audience.

**Primary goal of the project:** a production-grade portfolio artifact for AI-adjacent backend job applications, demonstrating the identity *"the person who makes agentic systems production-safe."* Commercial upside is a secondary bonus. Hard requirement: **≥5 real external users**.

## 4. Scope

### In scope (v1 / MVP)
- Two-CSV upload: a **Stripe payout export** + an **expected-orders CSV**.
- Reconciliation pipeline: deterministic pass → ingest/normalize agent → matcher agent → **fail-closed verifier agent** → human-review queue.
- Output: a reconciliation report — matched / discrepancies (missing order, extra payout line, amount mismatch with reason) / needs-review.
- Eval harness in CI (at least one real gating test at Sprint 1).
- Per-job observability (traces, token cost, latency, match-rate, false-match-rate).
- Guardrails + a written failure-mode runbook.
- A **free tier** from day one (essential to compete with "Stripe does it free").
- Minimal web UI (upload + report) and a real deployed URL.

### Out of scope (deferred to v1.1+)
- **Live Stripe API pull** (restricted read key / OAuth Connect) — the secret-handling showcase, done deliberately after the engine is proven. *This is the biggest deferred item and an explicit decision (see §11).*
- Store integrations (Shopify/DB order pull).
- Multi-tenant auth hardening, billing, team features.
- Continuous/scheduled reconciliation.
- A polished dashboard beyond the MVP metrics view.

## 5. Architecture

**Governing principle (this is the architect behaviour):** *deterministic where deterministic wins; agents only on the residual ambiguity; a verifier as the gate.* Do not use an LLM for what is a hash-join. Knowing where **not** to put the model is half the value.

### Pipeline
1. **Deterministic pass** *(pure code, no LLM).* Exact join on order-id/reference plus exact amount+date match. Clears the easy 80–95%. Emits confirmed matches directly (still audited); passes only the **residual** downstream.
2. **Ingest / normalize agent** *(LLM).* Maps arbitrary CSV headers (`amount` / `total` / `gross_eur` / `net` …) from both files into a **canonical schema**. This is where the LLM genuinely earns its place: robust schema inference from messy real-world exports. Runs once per file, before matching.
3. **Matcher agent** *(LLM, residual only).* Proposes fuzzy matches with a **confidence score and a rationale**. Handles: amount off by Stripe fee %, partial refund, currency rounding, date/settlement skew, split or combined payouts.
4. **Verifier agent** *(LLM, independent, fail-closed gate).* Re-checks each proposed match **independently** of the matcher. **Never auto-confirms below the confidence/agreement threshold → routes to the human-review queue.** Emits an audit record per decision.

### Data flow
```
payout.csv ─┐   ingest/normalize
            ├─►     agent          ─►  deterministic pass
orders.csv ─┘   (canonical schema)          │
                                            ├─► exact matches ──────────────┐
                                            │   (high-certainty, audited)    │
                                            │                                ▼
                                            └─► residual ─► matcher ─► verifier ─► report
                                                            agent     agent       (matched /
                                                          (fuzzy,   (fail-closed:   discrepancies /
                                                          confidence  confirm or     needs-review)
                                                          + reason)   → needs-review)
```
The verifier gates **only agent-proposed (fuzzy) matches** — deterministic exact matches are high-certainty and go straight to the report (still audited). This keeps LLM verification focused where the uncertainty actually is.

## 6. Data model (MVP, SQLite)

- **job** — id, created_at, status, input file refs, metrics snapshot.
- **line** — normalized payout line or order line (source, canonical fields, raw ref).
- **decision** — job_id, payout_line_id, order_line_id, kind (`exact` | `fuzzy` | `unmatched` | `needs_review`), confidence, rationale, verifier_verdict, **idempotency_key = hash(payout_line, order_line, amount)**, created_at.
- **audit_event** — append-only log of every decision and state transition.

**Idempotency + audit (payments DNA, made concrete):** every decision is keyed and logged; re-running a job produces an **identical** result; no line is ever double-matched. Re-processing is safe by construction.

## 7. Verifier semantics (the differentiator)

- The verifier is a **separate agent call** from the matcher — independence is the point; a **fuzzy (agent-proposed) match** is only confirmed when both independent reasoners agree above threshold. (Deterministic exact matches bypass the verifier — see §5.)
- **Fail-closed:** on low confidence, on matcher/verifier disagreement, or on any verifier error → the match is **not** confirmed; it goes to `needs_review`. Silence/uncertainty never resolves to "confirmed".
- Threshold is **configurable and documented**; the default target is **false-match-rate = 0%** on the labeled eval set, trading recall for precision (correct for a money-verification tool).
- Every verifier decision writes its rationale to the audit log → the "auditable" promise is literal, not marketing.

## 8. Eval harness (the production-safety star, CI-gated)

- **Labeled dataset:** payout↔order pairs — true matches, true non-matches, and fuzzy cases (fee offsets, partial refunds, currency rounding, split payouts).
- **Metrics:** match **precision**, **recall**, **false-match-rate**.
- **CI gate (GitHub Actions):** a merge is **blocked** if false-match-rate > threshold (target 0%) or precision < threshold. Implemented as `pytest` tests.
- **Sprint 1 deliverable:** one real gating test — a tiny labeled set + a match-precision check that actually runs and passes/fails in CI. First brick of the harness.

## 9. Observability

Per-job trace capturing: which lines went deterministic vs. agent vs. review; token cost; latency; match-rate; false-match-rate; model + prompt version. MVP surfaces these as a simple metrics view; a fuller dashboard is post-MVP.

## 10. Guardrails + failure-mode runbook

| Failure mode | System response |
|---|---|
| LLM low confidence | Route to `needs_review` (fail closed). |
| Matcher vs. verifier disagree | Fail closed → `needs_review`. |
| CSV parse failure | Reject the whole job with a clear error. **No partial results.** |
| Model / (future) Stripe API error | Idempotent retry; **never double-count**. |
| Unmapped/ambiguous CSV schema | Ingest agent flags columns it can't map; job pauses for user confirmation rather than guessing. |

The runbook (documented failure modes + responses) is itself an exit-criterion artifact.

## 11. Key decisions (locked)

1. **Vertical:** Stripe payouts ↔ seller orders. *(vs. expense receipts, or reconciling Stripe against its own charges — rejected: the former is OCR-heavy and off-identity; the latter is near-trivial since Stripe already links them.)*
2. **Order source:** user-uploaded CSV. *(vs. Stripe charges / Shopify integration — deferred.)*
3. **Stack:** Python. *(vs. Java/Spring or TypeScript — Python is the AI lingua franca, richest eval/agent ecosystem, and adds production Python reps to the CV.)*
4. **MVP ingestion = two-CSV upload, NOT live Stripe API.** Rationale: removes secret-handling and OAuth from the critical path to first users, and — per the market analysis — directly lowers the **trust barrier** (the #1 acquisition risk for an unknown solo builder handling financial data). Live API is v1.1, done deliberately as the secret-handling showcase once the engine + verifier + eval are proven.

## 12. Positioning (from the market analysis)

- **Lead with the fail-closed / auditable promise**, not generic matching: *"Reconcile never auto-confirms a payout match it isn't sure about."* This named guarantee is the strongest, least-copied differentiator.
- **Free tier is mandatory** to compete with Stripe's free native report.
- The eval/observability/production-safety story is **engineer- and hiring-manager-legible** more than seller-legible — it is the portfolio and Show-HN/writeup angle, deliberately, not the primary sales hook to sellers.

## 13. Tech stack & deployment

- Python 3.12 · FastAPI · Anthropic SDK (Sonnet for agents).
- `pytest` for the eval harness · GitHub Actions as the CI gate.
- SQLite for MVP persistence (jobs, decisions, audit) → Postgres later.
- Minimal UI in server-rendered HTML/htmx (no React until the engine is solid).
- Deploy: Fly.io or Render → a real public URL, near-free tier.

## 14. Success criteria (maps to StepUp exit criteria)

Legible (public repo + README + this design doc) · Deployed (real URL, ≥5 external users) · Evaluated (eval harness in CI with a gating threshold) · Observable (traces + cost/latency/match-rate) · Guarded (verifier fail-closed + runbook) · Published (one write-up of the reusable production-safety pattern) · In motion (≥3 AI-adjacent applications with this as centerpiece).

## 15. Open questions

- **Final product name** (revisit; "Reconcile" is provisional).
- Exact confidence-threshold defaults — to be tuned against the labeled eval set once it exists.
- Which Stripe payout export format to target first (CSV column set) for the deterministic pass.
