# Plan 2 — Agent Layer (ingest + matcher) · Design Spec

> **Status:** approved for planning · **Date:** 2026-07-20 · **Author:** Erisa Dajcaj (with StepUp)
> **Builds on:** [`2026-07-19-reconcile-design.md`](2026-07-19-reconcile-design.md) §5 (pipeline), §8 (eval), §10 (guardrails). This spec details steps 2 (ingest/normalize agent) and 3 (matcher agent). The verifier (step 4) stays **Plan 3**.

---

## 1. Goal

Introduce the first two LLM agents of the pipeline while keeping the production-safety
invariants intact: the deterministic core still owns the numbers, the eval gate in CI
stays deterministic and free, and **no fuzzy match is auto-confirmed** (that promotion
is the verifier's job in Plan 3). After this plan the repo is genuinely *multi-agent*
and the "agents only on the residual ambiguity" architecture is visible in code, not
just in the design doc.

## 2. Governing principle (made concrete)

The LLM enters in exactly two places and nowhere else:

1. **Ingest:** infer the *mapping* from arbitrary CSV headers to the canonical schema.
2. **Matcher:** propose *fuzzy pairings* over the residual left by the deterministic pass.

The matcher does see monetary values — but only after deterministic code has already
parsed them into `Decimal` (§3.3). The LLM never parses a raw value into a number, never
emits or recomputes one, and is never the gate. Deterministic code coerces values
(`Decimal`/`date`), validates references, and assembles the report. This is the architect
behaviour: knowing where **not** to put the model.

## 3. Components

### 3.1 `src/reconcile/llm.py` — the testability seam

- `class LLMClient(Protocol)` with `structured(*, system: str, user: str, schema: dict) -> dict`:
  returns JSON validated against `schema`; raises **`LLMError`** on malformed output
  (fail-closed).
- `AnthropicClient(model: str)` — real adapter over the Anthropic SDK (tool/JSON mode).
  `import anthropic` is **lazy** (inside `__init__`), so the base package never requires
  the SDK. Models: ingest → **Haiku** (cheap header mapping), matcher → **Sonnet**
  (reasoning over money).
- `FakeLLMClient` — deterministic, constructed with canned responses. **This is what runs
  in CI**: free, fast, no secret, no flakiness. It exercises the *harness logic* (parsing,
  routing, fail-closed), not model quality.

The protocol makes the LLM swappable; a consumer can bring their own `LLMClient` without
ever installing `anthropic`.

### 3.2 `src/reconcile/ingest.py` — ingest / normalize agent

- `infer_mapping(headers, target, client) -> ColumnMapping` — the LLM maps
  `{source_header → canonical_field}` with a confidence, **once per file**.
- **Deterministic short-circuit:** if the headers already equal the canonical set, return
  the identity mapping with **no LLM call**. The common case stays free and deterministic.
- **Fail-closed:** a required canonical field left unmapped, or mapped below the confidence
  threshold → **`MappingError`**, whole job rejected (no partial parse). The threshold is a
  documented module constant (default `≥ 0.9`), overridable per call.
- Value coercion stays in deterministic code. `parse.py` is refactored to split
  "which header feeds which field" (now supplied by the mapping) from "coerce the value to
  `Decimal`/`date`" (unchanged, money-safe). `ingest.py` composes: read headers →
  `infer_mapping` → deterministic parse-with-mapping.

### 3.3 `src/reconcile/matcher.py` — matcher agent

- `propose_matches(unmatched_orders, unmatched_payouts, client) -> list[CandidateMatch]`,
  run over the **residual** from `deterministic_match`.
- `@dataclass(frozen=True) CandidateMatch(order: OrderLine, payout: PayoutLine,
  confidence: float, rationale: str, kind: str)` where
  `kind ∈ {fee_offset, partial_refund, currency_rounding, other}`.
- **Money-safety:** the agent reasons over already-typed lines (`Decimal`) and **references
  lines by index** — it never emits an amount. Code resolves indices back to the real
  line objects and validates they exist.
- **Fail-closed:** a malformed proposal or an out-of-range index is **dropped** (never
  fabricate a match). Because nothing here is auto-confirmed, dropping is safe.

### 3.4 `src/reconcile/matching.py` + `core.py` — report + wiring

- `ReconcileReport` gains `needs_review: list[CandidateMatch] = field(default_factory=list)`.
  `matched` still holds **only** deterministic exact matches. `unmatched_orders` /
  `unmatched_payouts` remain the full residual; `needs_review` is an overlay of candidate
  pairings over that residual.
- `reconcile_files(payout_csv, orders_csv, client: LLMClient | None = None)`:
  ingest (map + parse) → `deterministic_match` → `matcher.propose_matches` on the residual
  → assemble report. `client=None` → pure deterministic path (Plan 1 behaviour preserved:
  exact headers required, matcher skipped).

## 4. Eval (the production-safety star, extended)

- **CI gate — unchanged and deterministic.** `precision` / `recall` / `false_match_rate`
  are computed over **auto-confirmed** matches, which remain deterministic-only → FMR
  stays 0. New assertion: with `FakeLLMClient`, **no fuzzy proposal leaks into `matched`**
  (auto-confirmed stays deterministic-only). Runs on `FakeLLMClient` — no key, no cost.
- **New, non-blocking metric:** `candidate_recall` = fraction of true fuzzy matches surfaced
  in `needs_review`. Computed against the fuzzy ground truth. Run by
  `scripts/eval_agents.py` (or a pytest `@mark.live` test **skipped without
  `ANTHROPIC_API_KEY`**) against real Haiku/Sonnet → prints a report. This measures *model
  quality* deliberately **outside** the CI gate, because model calls are non-deterministic
  and cost money.

## 5. Fixtures

- `tests/fixtures/payout_fuzzy.csv` / `orders_fuzzy.csv`: **fee-offset, partial-refund,
  currency-rounding** cases (all 1:1) + one variant with **non-canonical headers** to
  exercise ingest mapping. `tests/fixtures/labeled_fuzzy.json` — ground truth with a
  `kind` label per pair.
- **Deferred (documented, not a gap):** split / combined payouts (N:M). They require an
  N:M report model; addressed in a dedicated later increment.

## 6. Packaging (option 2 — optional extra + lazy import)

```toml
dependencies = []                       # core stays zero-dependency
[project.optional-dependencies]
llm = ["anthropic>=<current>"]          # exact floor pinned at implementation vs the current SDK
dev = ["pytest>=8.0"]
```

The deterministic core installs with **zero runtime deps** (as in Plan 1); the CI gate
installs `[dev]` and never pulls in `anthropic`. Agents and the live eval need
`pip install -e ".[llm]"`. This makes the claim *"the model is optional, the safety layer
is not"* a verifiable fact of `pyproject.toml`, not just narrative.

## 7. Error handling / fail-closed table (Plan 2 additions)

| Failure mode | System response |
|---|---|
| Ingest: required canonical field unmapped or low-confidence | `MappingError` → reject whole job. No partial parse. |
| Ingest / matcher: malformed LLM output (schema violation) | `LLMError`; ingest → reject job; matcher → drop the proposal. |
| Matcher: proposal references out-of-range line index | Drop the proposal. Never fabricate a match. |
| LLM transient/API error (real adapter) | Ingest → abort job (fail closed); matcher → residual simply gets no candidates (safe: nothing wrongly confirmed). |

## 8. Testing strategy

- Unit tests use `FakeLLMClient` (deterministic): ingest mapping inference, ingest
  fail-closed on unmapped/low-confidence, short-circuit on canonical headers, matcher
  proposal shape + index validation + fail-closed on bad output, report structure, core
  wiring, and `client=None` deterministic path (Plan 1 regression).
- CI eval test: deterministic gate as above, plus the "no fuzzy leaks into `matched`"
  assertion.
- `scripts/eval_agents.py`: live model-quality eval, key-gated, non-blocking.
- TDD (RED/GREEN) per task, as in Plan 1.

## 9. Scope boundary

**In:** llm seam, ingest agent, matcher agent, report/core extension, eval extension +
live script, fuzzy fixtures, packaging change.
**Out (later plans):** verifier + promotion of candidates to confirmed (Plan 3), web UI +
deploy (Plan 4), observability (Plan 5), N:M split payouts, SQLite persistence/audit.

## 10. Success criteria

- Repo is multi-agent: ingest + matcher agents present, behind a swappable `LLMClient`.
- CI gate still green, deterministic, zero-dependency, FMR = 0 on auto-confirmed.
- `candidate_recall` measurable via the live script on the fuzzy fixtures.
- `pip install reconcile` still pulls zero runtime deps; agents live behind `[llm]`.
- Fail-closed table above holds, covered by tests.
