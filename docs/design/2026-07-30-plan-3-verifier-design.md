# Plan 3 — Verifier + refund corroboration · Design Spec

> **Status:** implemented · **Date:** 2026-07-30 · **Author:** Erisa Dajcaj (with StepUp)
> **Builds on:** [`2026-07-19-reconcile-design.md`](2026-07-19-reconcile-design.md) §5 (pipeline), §7 (verifier semantics), §8 (eval); [`2026-07-20-plan-2-agent-layer-design.md`](2026-07-20-plan-2-agent-layer-design.md) (ingest + matcher). This spec details step 4 — the verifier — the gate that promotes a fuzzy candidate to a confirmed match. Plan 2 deliberately left every fuzzy candidate in `needs_review`; this plan builds the only thing allowed to move one out.

---

## 1. Goal

The verifier is the whole thesis of the project made executable: *deterministic where deterministic wins; agents only on the residual ambiguity; a verifier as the gate.* Plan 1 owned exact matches, Plan 2 surfaced fuzzy candidates without ever confirming one. Plan 3 introduces the **fail-closed promotion gate** that can move a candidate from `needs_review` into a confirmed match — and does so only when independent, redundant evidence agrees. After this plan the repo demonstrates the payments-grade discipline the whole portfolio claims: a candidate is promoted **only** when pure arithmetic corroborates it **and** an independent model, blind to the matcher's reasoning, reaches the same verdict. Anything short of full agreement stays in the review queue. The CI gate proves the promoted set carries a **0% false-match rate**.

## 2. Governing principle (made concrete)

Promotion requires two **independent** confirmations of the same claim:

1. **Deterministic corroboration.** Each `kind` implies an arithmetic predicate over already-typed `Decimal` values. Pure code, no model. If the arithmetic does not hold, the candidate is rejected outright — no LLM is even consulted.
2. **Independent LLM verdict.** A verifier agent, **blind to the matcher's proposed kind, confidence, and rationale**, re-classifies the raw pair on its own. Promotion happens only if the verifier independently names the **same kind** above a documented threshold.

Redundancy is the point: the deterministic check catches what the model hallucinates; the independent model catches arithmetic that is *coincidentally* satisfiable but semantically wrong. A single reasoner confirming its own earlier guess would be theatre — the verifier never sees what the matcher said. This is the architect behaviour Plan 2 named but could not yet show: the model is used, but it is never the sole gate.

## 3. Components

### 3.1 `src/reconcile/schema.py` — data model additions

- `@dataclass(frozen=True) RefundLine(ref: str, amount: Decimal, currency: str, refund_date: date)`
  — an **optional third input**. Same money-safe typing as the other lines; deterministic code coerces values, never the model.
- `@dataclass(frozen=True) VerifiedMatch(order: OrderLine, payout: PayoutLine, kind: str, matcher_confidence: float, verifier_confidence: float, deterministic_check: str, rationale: str)`
  — a promoted candidate that carries its own **audit trail**: which arithmetic predicate confirmed it (`deterministic_check`), both independent confidence votes, and a human-readable rationale. The provenance travels with the result; no separate store is needed for Plan 3 (SQLite audit persistence stays a later plan).

### 3.2 `src/reconcile/verifier.py` — the promotion gate

- `promote(candidates: list[CandidateMatch], refunds: list[RefundLine], client: LLMClient | None) -> tuple[list[VerifiedMatch], list[CandidateMatch]]`
  — returns `(verified, still_needs_review)`. Every candidate lands in exactly one of the two lists; nothing is silently dropped.
- Per candidate, two stages in order:
  1. **`ARITH[kind](order, payout, refunds) -> bool`** — pure predicate table (§3.3). `False` → reject (stays in `needs_review`), **no LLM call**.
  2. **Independent verdict** — `classify(order, payout, refunds, client)` calls the verifier agent, which receives only the raw lines (by index, money-safe) and returns `{kind, confidence}`. Promote iff `verdict.kind == candidate.kind and verdict.confidence >= VERIFIER_THRESHOLD`. Otherwise reject.
- **`VERIFIER_THRESHOLD`** — documented module constant (default `0.9`, overridable per call), mirroring the ingest-confidence pattern from Plan 2.
- **Money-safety** — identical to the matcher: the verifier reasons over already-typed lines, references them by index, never emits or recomputes an amount. Code resolves indices back to real objects.
- **Independence in the prompt** — the verifier's system prompt states its job is to classify one order against one payout (with optional refund context) *from scratch*. It is never given the matcher's `kind`, `confidence`, or `rationale`. A separate `structured` call over the same `LLMClient` seam; `FakeLLMClient` in CI.

### 3.3 Per-kind arithmetic predicates (`verifier.py`)

All predicates first require **same currency**. Then:

| kind | predicate |
|---|---|
| `fee_offset` | `order.amount == payout.net_amount` **and** `payout.gross_amount - payout.fee == payout.net_amount` |
| `currency_rounding` | `0 < abs(order.amount - payout.gross_amount) <= ROUNDING_EPSILON` |
| `partial_refund` | `∃ refund r` with `r.ref == order.order_id` such that `payout.gross_amount + r.amount == order.amount` |
| `other` | always `False` — never promotable |

- **`ROUNDING_EPSILON`** — documented module constant (e.g. `Decimal("0.02")`), the largest tolerated rounding drift. Above it, not a rounding case.
- `partial_refund` is **unsatisfiable without refunds**: absent a matching `RefundLine`, the predicate is `False` and the candidate honestly stays in `needs_review`. Fail-closed by construction.

### 3.4 `src/reconcile/ingest.py` — refund ingest (additive)

- `load_refunds(refunds_csv, client) -> list[RefundLine]` — same header-mapping discipline as `load_orders` / `load_payouts`: canonical short-circuit (no LLM when headers already match), fail-closed `MappingError` on an unmapped required field. Value coercion stays deterministic.
- Purely additive: no existing ingest path changes.

### 3.5 `src/reconcile/matching.py` + `core.py` — report + wiring

- `ReconcileReport` gains `verified: list[VerifiedMatch] = field(default_factory=list)`. **`matched` stays deterministic-exact-only** — the Plan 1/2 invariant is preserved; `verified` is a distinct, separately-gated tier. Rejected candidates remain in `needs_review`.
- `reconcile_files(payout_csv, orders_csv, refunds_csv=None, client=None, *, ingest_client=None, verifier_client=None)`:
  ingest (payouts, orders, and refunds **iff `refunds_csv` given**) → `deterministic_match` → `propose_matches` on the residual → `promote(needs_review, refunds, verifier_client)` → the report's `verified` is set and the promoted candidates are removed from `needs_review`.
- `verifier_client` defaults to `client` (independence lives in the *prompt*, not in requiring a second model instance). `refunds_csv=None` → no refunds → `partial_refund` never promotes. `client=None` → Plan 1 pure-deterministic path, unchanged: no matcher, no verifier, empty `verified`.

## 4. Eval (the production-safety star, extended)

- **New CI gate — deterministic, on `FakeLLMClient`.** `verified_metrics(report, verified_truth)` returns `EvalMetrics` over `report.verified`. CI asserts **`verified_false_match_rate == 0.0`** and **`precision == 1.0`** on a labeled set. This is the plan's headline claim, machine-checked: the promoted tier admits zero wrong matches. Runs on the fake — no key, no cost, no flakiness.
- **The existing deterministic gate is untouched** — `evaluate` still scores `matched` (deterministic-only), FMR stays 0 there too. Two independent gates, two tiers.
- **Non-blocking metric:** promotion **recall** (share of truly-promotable candidates actually promoted) is *measured, never gated* — same principle as `candidate_recall`. We trade recall for precision on purpose; the review queue is the safety net for whatever the gate refuses. Live model-quality measurement stays in `scripts/eval_agents.py`, key-gated.

## 5. Fixtures

- Extend `tests/fixtures/` with refund cases: `refunds.csv` (+ a non-canonical-header variant to exercise `load_refunds` mapping) and `labeled_verified.json` — ground truth marking which candidates **should** promote and to which kind.
- **Adversarial cases are mandatory** (the gate is only credible if it refuses the near-misses):
  - a `fee_offset` candidate where `gross - fee != net` → must **not** promote;
  - a `partial_refund` candidate whose shortfall matches **no** refund line → must **not** promote;
  - a `currency_rounding` candidate whose gap exceeds `ROUNDING_EPSILON` → must **not** promote;
  - an `other` candidate → must **never** promote;
  - a candidate where arithmetic holds but the **verifier disagrees on kind** → must **not** promote (independence catches it).
- **Deferred (documented, not a gap):** N:M split/combined payouts still out of scope (needs an N:M report model, a later increment).

## 6. Packaging

No change and no new runtime dependency. The verifier reuses the Plan 2 `LLMClient` seam; the deterministic core still installs with **zero runtime deps**, CI still runs on `FakeLLMClient` behind `[dev]`, agents still live behind `[llm]`. "The model is optional, the safety layer is not" remains a fact of `pyproject.toml`.

## 7. Error handling / fail-closed table (Plan 3 additions)

| Failure mode | System response |
|---|---|
| Deterministic predicate fails | Reject → stays in `needs_review`. **No LLM call.** |
| Verifier disagrees on kind, or below `VERIFIER_THRESHOLD` | Reject → stays in `needs_review`. |
| Verifier LLM error / malformed output (`LLMError`) | Reject → stays in `needs_review` (fail closed). |
| `partial_refund` but no `refunds_csv`, or no matching refund line | Reject → stays in `needs_review`. |
| Refund ingest: required field unmapped / low-confidence | `MappingError` → reject whole job (same as other ingest). |
| Verifier transient/API error (real adapter) | Candidate simply not promoted (safe: nothing wrongly confirmed). |

Every path fails toward the review queue. The only way out of `needs_review` is unanimous agreement.

## 8. Testing strategy

- Unit tests on `FakeLLMClient` (deterministic): each `ARITH` predicate (hold and near-miss), `promote` two-list partition, independence (verifier never receives matcher fields), threshold boundary, `partial_refund` with and without refunds, refund-ingest mapping + fail-closed, `VerifiedMatch` provenance fields populated, report wiring, and the `client=None` Plan 1 regression path.
- CI eval test: the new `verified_false_match_rate == 0.0` / `precision == 1.0` gate, plus a guard that no candidate reaches `verified` without both confirmations.
- `scripts/eval_agents.py`: extend the live, key-gated, non-blocking model-quality eval to report promotion precision/recall against real models.
- TDD (RED/GREEN) per task, as in Plans 1 and 2.

## 9. Scope boundary

**In:** `verifier.py` (predicates + independent-verdict gate), `RefundLine` + `VerifiedMatch`, refund ingest (`load_refunds`), report/`core` wiring, eval extension + new FMR gate, refund + adversarial fixtures, fail-closed tests.
**Out (later plans):** SQLite persistence / durable audit log (Plan 3 keeps provenance in-memory on `VerifiedMatch`), web UI + deploy (Plan 4), observability (Plan 5), N:M split payouts.

## 10. Success criteria

- A candidate is promoted to `verified` **only** when arithmetic corroborates it **and** an independent, matcher-blind verifier agrees on the kind above threshold.
- CI proves **`verified_false_match_rate == 0.0`** and **`precision == 1.0`** on the labeled set, on `FakeLLMClient` — deterministic, keyless, free.
- The existing deterministic gate and `matched = deterministic-only` invariant are unchanged.
- Optional `refunds_csv` unlocks `partial_refund`; absent, that kind honestly stays in review.
- Every promotion carries its audit trail (`deterministic_check`, both votes, rationale).
- `pip install reconcile` still pulls zero runtime deps; the verifier lives behind the same `[llm]` seam.
- The fail-closed table holds, covered by adversarial tests.
