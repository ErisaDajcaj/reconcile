# Plan 3 — Verifier + refund corroboration · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fail-closed promotion gate that moves a fuzzy `CandidateMatch` out of `needs_review` into a confirmed `VerifiedMatch` — only when a pure-code arithmetic predicate holds *and* an independent verifier LLM (blind to the matcher's reasoning) agrees on the kind above threshold.

**Architecture:** A new `verifier.py` module holds a per-`kind` arithmetic predicate table (pure code) and an independent `classify` LLM call. `promote()` partitions candidates into `verified` vs still-`needs_review`. An optional `RefundLine` third input (parsed by the existing ingest discipline) unlocks the `partial_refund` predicate. `matched` stays deterministic-exact-only; a new CI eval gate proves `verified_false_match_rate == 0.0` and `precision == 1.0` on `FakeLLMClient`.

**Tech Stack:** Python 3.12, stdlib only (`decimal.Decimal`, `csv`), `pytest` for tests, the existing `LLMClient` protocol seam. Zero new runtime dependencies.

## Global Constraints

- **Zero new runtime dependencies.** `anthropic` stays an optional `[llm]` extra; the verifier uses the `LLMClient` protocol, never imports a vendor SDK.
- **Money-safety.** The verifier LLM references lines by label/index only; it never emits or recomputes an amount. All arithmetic is pure code over already-typed `Decimal` values.
- **Independence.** The verifier's prompt receives ONLY the raw order/payout/refund lines — never the matcher's `kind`, `confidence`, or `rationale`.
- **Fail-closed.** Predicate false, verifier disagreement, verifier below threshold, verifier error/malformed, or missing refund → candidate stays in `needs_review`. The only exit from `needs_review` is unanimous agreement.
- **`matched` invariant.** `ReconcileReport.matched` holds deterministic exact matches only; promoted candidates go to the separate `verified` list.
- **KINDS** = `("fee_offset", "partial_refund", "currency_rounding", "other")` — imported from `reconcile.matcher`, never re-literaled.
- **Constants:** `ROUNDING_EPSILON = Decimal("0.02")`, `VERIFIER_THRESHOLD = 0.9` — documented module constants in `verifier.py`.
- **Test command:** `.venv/bin/python -m pytest` (repo root). All 84 existing tests must stay green.
- **Commit style:** Conventional Commits, one commit per task, sign-off trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

- `src/reconcile/schema.py` — **modify**: add `RefundLine`, `VerifiedMatch` dataclasses.
- `src/reconcile/parse.py` — **modify**: add `REFUND_COLUMNS`, `parse_refunds`.
- `src/reconcile/ingest.py` — **modify**: add `load_refunds`.
- `src/reconcile/verifier.py` — **create**: predicates, `classify`, `promote`, constants.
- `src/reconcile/matching.py` — **modify**: add `ReconcileReport.verified` field.
- `src/reconcile/core.py` — **modify**: `reconcile_files` gains `refunds_csv` + `verifier_client`, wires the verifier.
- `src/reconcile/evaluation.py` — **modify**: add `verified_metrics`.
- `tests/test_schema.py`, `tests/test_parse.py`, `tests/test_ingest.py`, `tests/test_verifier.py` (new), `tests/test_matching.py`, `tests/test_core.py`, `tests/test_eval.py` — tests per task.
- `tests/fixtures/refunds.csv`, `tests/fixtures/refunds_raw_headers.csv`, `tests/fixtures/labeled_verified.json` — new fixtures.

---

## Task 1: Data model — `RefundLine` + `VerifiedMatch`

**Files:**
- Modify: `src/reconcile/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: `OrderLine`, `PayoutLine` (existing in `schema.py`).
- Produces:
  - `RefundLine(ref: str, gross... )` → exactly: `RefundLine(ref: str, amount: Decimal, currency: str, refund_date: date)`, `@dataclass(frozen=True)`.
  - `VerifiedMatch(order: OrderLine, payout: PayoutLine, kind: str, matcher_confidence: float, verifier_confidence: float, deterministic_check: str, rationale: str)`, `@dataclass(frozen=True)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_schema.py`:

```python
from datetime import date
from decimal import Decimal

from reconcile.schema import RefundLine, VerifiedMatch, OrderLine, PayoutLine


def test_refund_line_is_a_frozen_typed_record():
    r = RefundLine(ref="ord_refund", amount=Decimal("12.00"), currency="EUR", refund_date=date(2026, 7, 2))
    assert r.ref == "ord_refund"
    assert r.amount == Decimal("12.00")
    assert r.currency == "EUR"
    assert r.refund_date == date(2026, 7, 2)
    try:
        r.amount = Decimal("0")
        assert False, "RefundLine should be frozen"
    except AttributeError:
        pass


def test_verified_match_carries_its_audit_trail():
    order = OrderLine(order_id="ord_fee", amount=Decimal("97.10"), currency="EUR", order_date=date(2026, 7, 2))
    payout = PayoutLine(ref="py_1", gross_amount=Decimal("100.00"), fee=Decimal("2.90"),
                        net_amount=Decimal("97.10"), currency="EUR", line_date=date(2026, 7, 2))
    v = VerifiedMatch(order=order, payout=payout, kind="fee_offset",
                      matcher_confidence=0.91, verifier_confidence=0.95,
                      deterministic_check="fee_offset", rationale="net vs gross")
    assert v.kind == "fee_offset"
    assert v.matcher_confidence == 0.91
    assert v.verifier_confidence == 0.95
    assert v.deterministic_check == "fee_offset"
    assert v.rationale == "net vs gross"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: FAIL with `ImportError: cannot import name 'RefundLine'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/reconcile/schema.py`:

```python
@dataclass(frozen=True)
class RefundLine:
    ref: str
    amount: Decimal
    currency: str
    refund_date: date


@dataclass(frozen=True)
class VerifiedMatch:
    """A candidate promoted out of `needs_review` by the verifier.

    Carries its own audit trail: which arithmetic predicate confirmed it
    (`deterministic_check`), both independent confidence votes, and the
    matcher's rationale.
    """

    order: OrderLine
    payout: PayoutLine
    kind: str
    matcher_confidence: float
    verifier_confidence: float
    deterministic_check: str
    rationale: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/schema.py tests/test_schema.py
git commit -m "feat: add RefundLine and VerifiedMatch to schema"
```

---

## Task 2: Refund parsing — `REFUND_COLUMNS` + `parse_refunds`

**Files:**
- Modify: `src/reconcile/parse.py`
- Test: `tests/test_parse.py`

**Interfaces:**
- Consumes: `RefundLine` (Task 1), existing `identity_mapping`, `_rows`, `_cell`, `_require_mapped_columns`, `CsvSchemaError` in `parse.py`.
- Produces: `REFUND_COLUMNS = {"ref", "amount", "currency", "date"}`; `parse_refunds(path, mapping: ColumnMapping | None = None) -> list[RefundLine]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_parse.py`:

```python
from reconcile.parse import parse_refunds, REFUND_COLUMNS
from reconcile.schema import RefundLine


def test_parse_refunds_canonical_headers(tmp_path):
    p = tmp_path / "refunds.csv"
    p.write_text("ref,amount,currency,date\nord_refund,12.00,eur,2026-07-02\n", encoding="utf-8")
    refunds = parse_refunds(p)
    assert refunds == [RefundLine(ref="ord_refund", amount=Decimal("12.00"),
                                  currency="EUR", refund_date=date(2026, 7, 2))]


def test_parse_refunds_missing_required_column_fails_closed(tmp_path):
    from reconcile.parse import CsvSchemaError
    p = tmp_path / "bad.csv"
    p.write_text("ref,amount,currency\nord_refund,12.00,EUR\n", encoding="utf-8")
    try:
        parse_refunds(p)
        assert False, "expected CsvSchemaError for missing date column"
    except CsvSchemaError:
        pass


def test_refund_columns_value():
    assert REFUND_COLUMNS == {"ref", "amount", "currency", "date"}
```

Ensure the top of `tests/test_parse.py` imports `date` and `Decimal` (add if absent):

```python
from datetime import date
from decimal import Decimal
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_parse.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_refunds'`.

- [ ] **Step 3: Write minimal implementation**

In `src/reconcile/parse.py`, add `RefundLine` to the schema import line and add the column set + parser. Change:

```python
from .schema import ColumnMapping, PayoutLine, OrderLine
```
to:
```python
from .schema import ColumnMapping, PayoutLine, OrderLine, RefundLine
```

Add after `ORDER_COLUMNS`:

```python
REFUND_COLUMNS = {"ref", "amount", "currency", "date"}
```

Add after `parse_orders`:

```python
def parse_refunds(path, mapping: ColumnMapping | None = None) -> list[RefundLine]:
    mapping = mapping or identity_mapping(REFUND_COLUMNS)
    gen = _rows(path)
    header, p = next(gen)
    _require_mapped_columns(header, mapping, REFUND_COLUMNS, p)
    out = []
    for row, _ in gen:
        out.append(
            RefundLine(
                ref=_cell(row, mapping, "ref").strip(),
                amount=Decimal(_cell(row, mapping, "amount")),
                currency=_cell(row, mapping, "currency").strip().upper(),
                refund_date=date.fromisoformat(_cell(row, mapping, "date").strip()),
            )
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_parse.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/parse.py tests/test_parse.py
git commit -m "feat: parse refund CSV lines into RefundLine records"
```

---

## Task 3: Refund ingest — `load_refunds`

**Files:**
- Modify: `src/reconcile/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `parse_refunds`, `REFUND_COLUMNS` (Task 2); existing `infer_mapping`, `read_headers` in `ingest.py`.
- Produces: `load_refunds(path, client: LLMClient | None = None) -> list[RefundLine]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingest.py`:

```python
from reconcile.ingest import load_refunds
from reconcile.llm import FakeLLMClient
from reconcile.schema import RefundLine


def test_load_refunds_canonical_headers_no_model_call(tmp_path):
    p = tmp_path / "refunds.csv"
    p.write_text("ref,amount,currency,date\nord_refund,12.00,EUR,2026-07-02\n", encoding="utf-8")
    client = FakeLLMClient([])
    refunds = load_refunds(p, client)
    assert refunds == [RefundLine(ref="ord_refund", amount=Decimal("12.00"),
                                  currency="EUR", refund_date=date(2026, 7, 2))]
    assert client.calls == []  # canonical headers short-circuit the model


def test_load_refunds_maps_non_canonical_headers(tmp_path):
    p = tmp_path / "refunds_raw.csv"
    p.write_text("refund_ref,refund_value,ccy,refunded_on\nord_refund,12.00,EUR,2026-07-02\n", encoding="utf-8")
    client = FakeLLMClient([{
        "mapping": [
            {"field": "ref", "header": "refund_ref"},
            {"field": "amount", "header": "refund_value"},
            {"field": "currency", "header": "ccy"},
            {"field": "date", "header": "refunded_on"},
        ],
        "confidence": 0.98,
    }])
    refunds = load_refunds(p, client)
    assert refunds[0].ref == "ord_refund"
    assert refunds[0].amount == Decimal("12.00")
    assert len(client.calls) == 1
```

Ensure `tests/test_ingest.py` imports `date` and `Decimal` at the top (add if absent).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ingest.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_refunds'`.

- [ ] **Step 3: Write minimal implementation**

In `src/reconcile/ingest.py`, extend the parse import and add the loader. Change:

```python
from .parse import (
    ORDER_COLUMNS,
    PAYOUT_COLUMNS,
    identity_mapping,
    parse_orders,
    parse_payouts,
)
from .schema import ColumnMapping, OrderLine, PayoutLine
```
to:
```python
from .parse import (
    ORDER_COLUMNS,
    PAYOUT_COLUMNS,
    REFUND_COLUMNS,
    identity_mapping,
    parse_orders,
    parse_payouts,
    parse_refunds,
)
from .schema import ColumnMapping, OrderLine, PayoutLine, RefundLine
```

Add after `load_orders`:

```python
def load_refunds(path, client: LLMClient | None = None) -> list[RefundLine]:
    mapping = infer_mapping(read_headers(path), REFUND_COLUMNS, client)
    return parse_refunds(path, mapping)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ingest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/ingest.py tests/test_ingest.py
git commit -m "feat: load_refunds reuses ingest mapping discipline"
```

---

## Task 4: Arithmetic predicates — `ARITH` table + constants

**Files:**
- Create: `src/reconcile/verifier.py`
- Test: `tests/test_verifier.py` (new)

**Interfaces:**
- Consumes: `OrderLine`, `PayoutLine`, `RefundLine` (schema); `KINDS` from `reconcile.matcher`.
- Produces: `ROUNDING_EPSILON: Decimal`, `VERIFIER_THRESHOLD: float`, `ARITH: dict[str, Callable[[OrderLine, PayoutLine, list[RefundLine]], bool]]`. Each predicate signature: `(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_verifier.py`:

```python
from datetime import date
from decimal import Decimal

from reconcile.schema import OrderLine, PayoutLine, RefundLine
from reconcile.verifier import ARITH, ROUNDING_EPSILON, VERIFIER_THRESHOLD


def _order(order_id, amount, currency="EUR"):
    return OrderLine(order_id=order_id, amount=Decimal(amount), currency=currency, order_date=date(2026, 7, 2))


def _payout(ref, gross, fee, net, currency="EUR"):
    return PayoutLine(ref=ref, gross_amount=Decimal(gross), fee=Decimal(fee),
                      net_amount=Decimal(net), currency=currency, line_date=date(2026, 7, 2))


def test_constants():
    assert ROUNDING_EPSILON == Decimal("0.02")
    assert VERIFIER_THRESHOLD == 0.9


def test_fee_offset_holds_when_order_is_net_and_gross_minus_fee_is_net():
    assert ARITH["fee_offset"](_order("o", "97.10"), _payout("p", "100.00", "2.90", "97.10"), []) is True


def test_fee_offset_rejects_when_gross_minus_fee_is_not_net():
    # arithmetic near-miss: net field inconsistent with gross-fee
    assert ARITH["fee_offset"](_order("o", "97.10"), _payout("p", "100.00", "3.00", "97.10"), []) is False


def test_currency_rounding_within_epsilon():
    assert ARITH["currency_rounding"](_order("o", "49.99"), _payout("p", "50.00", "1.75", "48.25"), []) is True


def test_currency_rounding_zero_gap_is_not_rounding():
    assert ARITH["currency_rounding"](_order("o", "50.00"), _payout("p", "50.00", "1.75", "48.25"), []) is False


def test_currency_rounding_beyond_epsilon_rejected():
    assert ARITH["currency_rounding"](_order("o", "49.90"), _payout("p", "50.00", "1.75", "48.25"), []) is False


def test_partial_refund_holds_when_a_matching_refund_covers_the_shortfall():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    refunds = [RefundLine(ref="ord_refund", amount=Decimal("12.00"), currency="EUR", refund_date=date(2026, 7, 2))]
    assert ARITH["partial_refund"](order, payout, refunds) is True


def test_partial_refund_rejected_without_refunds():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    assert ARITH["partial_refund"](order, payout, []) is False


def test_partial_refund_rejected_when_no_refund_matches_the_ref():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    refunds = [RefundLine(ref="ord_other", amount=Decimal("12.00"), currency="EUR", refund_date=date(2026, 7, 2))]
    assert ARITH["partial_refund"](order, payout, refunds) is False


def test_different_currency_never_holds():
    order = _order("o", "97.10", currency="USD")
    payout = _payout("p", "100.00", "2.90", "97.10", currency="EUR")
    assert ARITH["fee_offset"](order, payout, []) is False


def test_other_is_never_promotable():
    assert ARITH["other"](_order("o", "1.00"), _payout("p", "1.00", "0", "1.00"), []) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_verifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reconcile.verifier'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/reconcile/verifier.py`:

```python
"""The verifier: the fail-closed gate that promotes a fuzzy candidate.

A candidate is promoted only when a pure-code arithmetic predicate keyed by
its `kind` holds AND an independent LLM -- blind to the matcher's reasoning --
re-classifies the raw pair to the same kind above threshold. Every other path
leaves the candidate in `needs_review`.
"""

from decimal import Decimal

from .matcher import KINDS
from .schema import OrderLine, PayoutLine, RefundLine

# Largest tolerated rounding drift. Above it, not a currency-rounding case.
ROUNDING_EPSILON = Decimal("0.02")
# Minimum verifier confidence to promote. Mirrors the ingest-confidence floor.
VERIFIER_THRESHOLD = 0.9


def _fee_offset(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> bool:
    return (
        order.currency == payout.currency
        and order.amount == payout.net_amount
        and payout.gross_amount - payout.fee == payout.net_amount
    )


def _currency_rounding(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> bool:
    if order.currency != payout.currency:
        return False
    delta = abs(order.amount - payout.gross_amount)
    return Decimal(0) < delta <= ROUNDING_EPSILON


def _partial_refund(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> bool:
    if order.currency != payout.currency:
        return False
    return any(
        r.ref == order.order_id
        and r.currency == order.currency
        and payout.gross_amount + r.amount == order.amount
        for r in refunds
    )


def _other(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> bool:
    return False


ARITH = {
    "fee_offset": _fee_offset,
    "currency_rounding": _currency_rounding,
    "partial_refund": _partial_refund,
    "other": _other,
}

assert set(ARITH) == set(KINDS), "ARITH must cover exactly the matcher KINDS"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_verifier.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/verifier.py tests/test_verifier.py
git commit -m "feat: per-kind arithmetic predicates for the verifier"
```

---

## Task 5: Independent verifier verdict — `classify`

**Files:**
- Modify: `src/reconcile/verifier.py`
- Test: `tests/test_verifier.py`

**Interfaces:**
- Consumes: `LLMClient`, `LLMError` from `reconcile.llm`; `KINDS`.
- Produces: `classify(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine], client: LLMClient) -> dict | None` returning `{"kind": str, "confidence": float}` or `None` (fail-closed). The prompt receives ONLY the raw lines — never a matcher kind/rationale/confidence.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_verifier.py`:

```python
from reconcile.llm import FakeLLMClient, LLMError
from reconcile.verifier import classify


def test_classify_returns_kind_and_confidence():
    client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.95}])
    out = classify(_order("o", "97.10"), _payout("p", "100.00", "2.90", "97.10"), [], client)
    assert out == {"kind": "fee_offset", "confidence": 0.95}


def test_classify_prompt_never_leaks_matcher_reasoning():
    client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.95}])
    classify(_order("o", "97.10"), _payout("p", "100.00", "2.90", "97.10"), [], client)
    sent = client.calls[0]["system"] + client.calls[0]["user"]
    assert "rationale" not in sent.lower()
    assert "matcher" not in sent.lower()


def test_classify_fails_closed_on_llm_error():
    assert classify(_order("o", "97.10"), _payout("p", "100.00", "2.90", "97.10"), [],
                    FakeLLMClient([LLMError("boom")])) is None


def test_classify_rejects_unknown_kind():
    assert classify(_order("o", "1"), _payout("p", "1", "0", "1"), [],
                    FakeLLMClient([{"kind": "bogus", "confidence": 0.99}])) is None


def test_classify_rejects_out_of_range_confidence():
    assert classify(_order("o", "1"), _payout("p", "1", "0", "1"), [],
                    FakeLLMClient([{"kind": "fee_offset", "confidence": 1.4}])) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_verifier.py -v -k classify`
Expected: FAIL with `ImportError: cannot import name 'classify'`.

- [ ] **Step 3: Write minimal implementation**

In `src/reconcile/verifier.py`, extend imports and add the verdict call. Change the import block to:

```python
from decimal import Decimal

from .llm import LLMClient, LLMError
from .matcher import KINDS
from .schema import OrderLine, PayoutLine, RefundLine
```

Append at the end of the module:

```python
_SYSTEM = (
    "You are given exactly one order line and one payout line that an exact-match "
    "pass could not reconcile, plus any refund lines on record. Decide, on your own, "
    "which single relationship best explains the pair. Reference lines only by their "
    "labels; never output or recompute an amount. Answer with one kind: fee_offset "
    "(the order records the net, the payout the gross), partial_refund (a refund "
    "explains the shortfall), currency_rounding (they differ only by a rounding "
    "step), or other. Give a confidence on a 0.0-1.0 scale (0.0 = none, 1.0 = "
    "certain), never a percentage."
)

_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "confidence": {"type": "number"},
    },
    "required": ["kind", "confidence"],
    "additionalProperties": False,
}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _render_pair(order: OrderLine, payout: PayoutLine, refunds: list[RefundLine]) -> str:
    lines = [
        "Order:",
        f"  id={order.order_id} amount={order.amount} {order.currency} date={order.order_date}",
        "Payout:",
        f"  ref={payout.ref} gross={payout.gross_amount} fee={payout.fee} "
        f"net={payout.net_amount} {payout.currency} date={payout.line_date}",
    ]
    if refunds:
        lines.append("Refunds on record:")
        for r in refunds:
            lines.append(f"  ref={r.ref} amount={r.amount} {r.currency} date={r.refund_date}")
    else:
        lines.append("Refunds on record: none")
    return "\n".join(lines)


def classify(
    order: OrderLine, payout: PayoutLine, refunds: list[RefundLine], client: LLMClient
) -> dict | None:
    try:
        out = client.structured(
            system=_SYSTEM, user=_render_pair(order, payout, refunds), schema=_VERDICT_SCHEMA
        )
    except LLMError:
        return None
    kind = out.get("kind")
    confidence = out.get("confidence")
    if kind not in KINDS:
        return None
    if not _is_number(confidence) or not 0.0 <= confidence <= 1.0:
        return None
    return {"kind": kind, "confidence": float(confidence)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_verifier.py -v`
Expected: PASS (all Task 4 + Task 5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/verifier.py tests/test_verifier.py
git commit -m "feat: independent matcher-blind verifier verdict"
```

---

## Task 6: The promotion gate — `promote`

**Files:**
- Modify: `src/reconcile/verifier.py`
- Test: `tests/test_verifier.py`

**Interfaces:**
- Consumes: `ARITH`, `classify`, `VERIFIER_THRESHOLD` (this module); `CandidateMatch`, `VerifiedMatch` from schema.
- Produces: `promote(candidates: list[CandidateMatch], refunds: list[RefundLine], client: LLMClient | None) -> tuple[list[VerifiedMatch], list[CandidateMatch]]`. Returns `(verified, still_needs_review)`; every candidate appears in exactly one list.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_verifier.py`:

```python
from reconcile.schema import CandidateMatch, VerifiedMatch
from reconcile.verifier import promote


def _candidate(order, payout, kind, confidence=0.91):
    return CandidateMatch(order=order, payout=payout, confidence=confidence,
                          rationale="matcher said so", kind=kind)


FEE_ORDER = _order("ord_fee", "97.10")
FEE_PAYOUT = _payout("py_1", "100.00", "2.90", "97.10")


def test_promotes_when_arithmetic_and_verifier_agree():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.95}])
    verified, remaining = promote([cand], [], client)
    assert remaining == []
    assert len(verified) == 1
    v = verified[0]
    assert isinstance(v, VerifiedMatch)
    assert v.kind == "fee_offset"
    assert v.matcher_confidence == 0.91
    assert v.verifier_confidence == 0.95
    assert v.deterministic_check == "fee_offset"


def test_rejects_when_arithmetic_fails_without_calling_the_model():
    # gross-fee != net -> predicate false -> no LLM call
    bad_payout = _payout("py_1", "100.00", "3.00", "97.10")
    cand = _candidate(FEE_ORDER, bad_payout, "fee_offset")
    client = FakeLLMClient([])  # would raise if called
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]
    assert client.calls == []


def test_rejects_when_verifier_disagrees_on_kind():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    client = FakeLLMClient([{"kind": "currency_rounding", "confidence": 0.99}])
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]


def test_rejects_when_verifier_below_threshold():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.5}])
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]


def test_rejects_when_verifier_errors():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    client = FakeLLMClient([LLMError("down")])
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]


def test_no_client_leaves_everything_in_needs_review():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "fee_offset")
    verified, remaining = promote([cand], [], None)
    assert verified == []
    assert remaining == [cand]


def test_other_kind_is_never_promoted():
    cand = _candidate(FEE_ORDER, FEE_PAYOUT, "other")
    client = FakeLLMClient([{"kind": "other", "confidence": 0.99}])
    verified, remaining = promote([cand], [], client)
    assert verified == []
    assert remaining == [cand]
    assert client.calls == []  # 'other' predicate is False -> no model call


def test_partial_refund_promotes_only_with_a_matching_refund():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    cand = _candidate(order, payout, "partial_refund")
    refunds = [RefundLine(ref="ord_refund", amount=Decimal("12.00"), currency="EUR", refund_date=date(2026, 7, 2))]
    client = FakeLLMClient([{"kind": "partial_refund", "confidence": 0.93}])
    verified, remaining = promote([cand], refunds, client)
    assert len(verified) == 1 and remaining == []


def test_partial_refund_stays_in_review_without_refunds():
    order = _order("ord_refund", "30.00")
    payout = _payout("py_2", "18.00", "0.82", "17.18")
    cand = _candidate(order, payout, "partial_refund")
    client = FakeLLMClient([])  # predicate false first -> no call
    verified, remaining = promote([cand], [], client)
    assert verified == [] and remaining == [cand]
    assert client.calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_verifier.py -v -k promote`
Expected: FAIL with `ImportError: cannot import name 'promote'`.

- [ ] **Step 3: Write minimal implementation**

In `src/reconcile/verifier.py`, add `CandidateMatch, VerifiedMatch` to the schema import:

```python
from .schema import CandidateMatch, OrderLine, PayoutLine, RefundLine, VerifiedMatch
```

Append at the end of the module:

```python
def promote(
    candidates: list[CandidateMatch],
    refunds: list[RefundLine],
    client: LLMClient | None,
) -> tuple[list[VerifiedMatch], list[CandidateMatch]]:
    """Partition candidates into (verified, still-needs-review).

    A candidate is promoted only when its arithmetic predicate holds AND an
    independent verifier agrees on the kind above threshold. Every other path
    leaves it in the review queue.
    """
    verified: list[VerifiedMatch] = []
    remaining: list[CandidateMatch] = []

    for c in candidates:
        predicate = ARITH.get(c.kind)
        if predicate is None or not predicate(c.order, c.payout, refunds):
            remaining.append(c)
            continue
        if client is None:
            remaining.append(c)
            continue
        verdict = classify(c.order, c.payout, refunds, client)
        if verdict is None or verdict["kind"] != c.kind or verdict["confidence"] < VERIFIER_THRESHOLD:
            remaining.append(c)
            continue
        verified.append(
            VerifiedMatch(
                order=c.order,
                payout=c.payout,
                kind=c.kind,
                matcher_confidence=c.confidence,
                verifier_confidence=verdict["confidence"],
                deterministic_check=c.kind,
                rationale=c.rationale,
            )
        )
    return verified, remaining
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_verifier.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/verifier.py tests/test_verifier.py
git commit -m "feat: fail-closed promotion gate combining predicate and verdict"
```

---

## Task 7: Report field — `ReconcileReport.verified`

**Files:**
- Modify: `src/reconcile/matching.py`
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: `VerifiedMatch` (Task 1).
- Produces: `ReconcileReport.verified: list[VerifiedMatch]` (default empty). `matched` unchanged (deterministic-only).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_matching.py`:

```python
from reconcile.matching import ReconcileReport


def test_report_has_an_empty_verified_list_by_default():
    report = ReconcileReport()
    assert report.verified == []


def test_deterministic_match_leaves_verified_empty():
    from datetime import date
    from decimal import Decimal
    from reconcile.matching import deterministic_match
    from reconcile.schema import OrderLine, PayoutLine
    orders = [OrderLine(order_id="a", amount=Decimal("1.00"), currency="EUR", order_date=date(2026, 7, 2))]
    payouts = [PayoutLine(ref="a", gross_amount=Decimal("1.00"), fee=Decimal("0"),
                          net_amount=Decimal("1.00"), currency="EUR", line_date=date(2026, 7, 2))]
    report = deterministic_match(orders, payouts)
    assert report.verified == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_matching.py -v -k verified`
Expected: FAIL with `AttributeError: 'ReconcileReport' object has no attribute 'verified'`.

- [ ] **Step 3: Write minimal implementation**

In `src/reconcile/matching.py`, extend the schema import and add the field. Change:

```python
from .schema import CandidateMatch, PayoutLine, OrderLine
```
to:
```python
from .schema import CandidateMatch, PayoutLine, OrderLine, VerifiedMatch
```

Add to the `ReconcileReport` dataclass, after the `needs_review` field:

```python
    # Candidates promoted by the verifier (Plan 3). Distinct from `matched`,
    # which stays deterministic-exact-only.
    verified: list[VerifiedMatch] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_matching.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/matching.py tests/test_matching.py
git commit -m "feat: add verified tier to ReconcileReport"
```

---

## Task 8: Core wiring — `reconcile_files` runs the verifier

**Files:**
- Modify: `src/reconcile/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `load_refunds` (Task 3), `promote` (Task 6), existing `deterministic_match`, `propose_matches`.
- Produces: `reconcile_files(payout_csv, orders_csv, refunds_csv=None, client=None, *, ingest_client=None, verifier_client=None) -> ReconcileReport`. Sets `report.verified` and reassigns `report.needs_review` to the un-promoted remainder.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_core.py`. Note the fixtures `PAYOUTS`/`ORDERS` and helpers already exist at the top of the file; reuse them. Add:

```python
def test_verifier_promotes_a_fee_offset_candidate(tmp_path):
    payout = tmp_path / "p.csv"
    payout.write_text(
        "ref,gross_amount,fee,net_amount,currency,date\n"
        "py_1,100.00,2.90,97.10,EUR,2026-07-02\n", encoding="utf-8")
    orders = tmp_path / "o.csv"
    orders.write_text(
        "order_id,amount,currency,date\n"
        "ord_fee,97.10,EUR,2026-07-02\n", encoding="utf-8")
    # matcher proposes the pair; verifier confirms fee_offset
    matcher_client = FakeLLMClient([{
        "proposals": [{"order_index": 0, "payout_index": 0, "confidence": 0.9,
                       "rationale": "net vs gross", "kind": "fee_offset"}]
    }])
    verifier_client = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.95}])
    report = reconcile_files(payout, orders, client=matcher_client, verifier_client=verifier_client)
    assert len(report.verified) == 1
    assert report.verified[0].kind == "fee_offset"
    assert report.needs_review == []
    assert report.matched == []  # promotion never touches the deterministic tier


def test_verifier_client_defaults_to_client(tmp_path):
    # With only `client` given, it drives BOTH matcher and verifier. Feed the
    # single client a matcher response then a verdict, in call order.
    payout = tmp_path / "p.csv"
    payout.write_text(
        "ref,gross_amount,fee,net_amount,currency,date\n"
        "py_1,100.00,2.90,97.10,EUR,2026-07-02\n", encoding="utf-8")
    orders = tmp_path / "o.csv"
    orders.write_text(
        "order_id,amount,currency,date\n"
        "ord_fee,97.10,EUR,2026-07-02\n", encoding="utf-8")
    client = FakeLLMClient([
        {"proposals": [{"order_index": 0, "payout_index": 0, "confidence": 0.9,
                        "rationale": "net vs gross", "kind": "fee_offset"}]},
        {"kind": "fee_offset", "confidence": 0.95},
    ])
    report = reconcile_files(payout, orders, client=client)
    assert len(report.verified) == 1  # verifier_client defaulted to client


def test_plan_1_path_unchanged_no_verified(tmp_path):
    # no client at all -> pure deterministic, empty verified
    report = reconcile_files(PAYOUTS, ORDERS)
    assert report.verified == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_core.py -v -k verifier`
Expected: FAIL with `TypeError: reconcile_files() got an unexpected keyword argument 'verifier_client'`.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `src/reconcile/core.py` with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_core.py -v`
Expected: PASS (new tests + all existing `test_core.py` tests, since `client` is still keyword in every existing call).

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/core.py tests/test_core.py
git commit -m "feat: wire the verifier into reconcile_files with optional refunds"
```

---

## Task 9: Eval — `verified_metrics`

**Files:**
- Modify: `src/reconcile/evaluation.py`
- Test: `tests/test_eval.py`

**Interfaces:**
- Consumes: `ReconcileReport` with `verified` (Task 7); existing `EvalMetrics`.
- Produces: `verified_metrics(report: ReconcileReport, verified_truth: list[dict]) -> EvalMetrics` scoring `report.verified` (keys `order_id`, `payout_ref` per truth row). The `false_match_rate` field of the returned metrics IS the `verified_false_match_rate`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_eval.py`:

```python
from datetime import date
from decimal import Decimal

from reconcile.evaluation import verified_metrics, EvalMetrics
from reconcile.matching import ReconcileReport
from reconcile.schema import OrderLine, PayoutLine, VerifiedMatch


def _vm(order_id, ref, kind="fee_offset"):
    order = OrderLine(order_id=order_id, amount=Decimal("1"), currency="EUR", order_date=date(2026, 7, 2))
    payout = PayoutLine(ref=ref, gross_amount=Decimal("1"), fee=Decimal("0"),
                        net_amount=Decimal("1"), currency="EUR", line_date=date(2026, 7, 2))
    return VerifiedMatch(order=order, payout=payout, kind=kind, matcher_confidence=0.9,
                         verifier_confidence=0.95, deterministic_check=kind, rationale="x")


def test_verified_metrics_all_correct_is_perfect():
    report = ReconcileReport(verified=[_vm("ord_fee", "py_1")])
    truth = [{"order_id": "ord_fee", "payout_ref": "py_1", "kind": "fee_offset"}]
    m = verified_metrics(report, truth)
    assert m == EvalMetrics(precision=1.0, recall=1.0, false_match_rate=0.0)


def test_verified_metrics_flags_a_wrong_promotion():
    report = ReconcileReport(verified=[_vm("ord_x", "py_wrong")])
    truth = [{"order_id": "ord_fee", "payout_ref": "py_1", "kind": "fee_offset"}]
    m = verified_metrics(report, truth)
    assert m.precision == 0.0
    assert m.false_match_rate == 1.0


def test_verified_metrics_empty_report_is_vacuously_clean():
    m = verified_metrics(ReconcileReport(), [])
    assert m.false_match_rate == 0.0
    assert m.precision == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval.py -v -k verified_metrics`
Expected: FAIL with `ImportError: cannot import name 'verified_metrics'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/reconcile/evaluation.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_eval.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/evaluation.py tests/test_eval.py
git commit -m "feat: verified_metrics scores the promoted tier"
```

---

## Task 10: Fixtures + the CI false-match gate

**Files:**
- Create: `tests/fixtures/refunds.csv`, `tests/fixtures/labeled_verified.json`
- Test: `tests/test_eval.py`

**Interfaces:**
- Consumes: `reconcile_files` (Task 8), `verified_metrics` (Task 9), the existing fuzzy fixtures (`payout_fuzzy.csv`, `orders_fuzzy.csv`), `FakeLLMClient`.
- Produces: an end-to-end CI gate proving the promoted tier is false-match-free, plus an adversarial guard that a near-miss never promotes.

**Fixture facts (from existing `orders_fuzzy.csv` / `payout_fuzzy.csv`):** `ord_fee/97.10` ↔ `py_1/gross100.00 fee2.90 net97.10` (fee_offset holds); `ord_round/49.99` ↔ `py_3/gross50.00` (rounding, gap 0.01 ≤ ε); `ord_refund/30.00` ↔ `py_2/gross18.00` needs a 12.00 refund; `ord_alone/88.00` and `py_4` have no partner.

- [ ] **Step 1: Create the refund fixture**

Create `tests/fixtures/refunds.csv`:

```csv
ref,amount,currency,date
ord_refund,12.00,EUR,2026-07-02
```

Create `tests/fixtures/labeled_verified.json` (the three fuzzy pairs are all genuinely promotable given the refund):

```json
[
  {"order_id": "ord_fee",    "payout_ref": "py_1", "kind": "fee_offset"},
  {"order_id": "ord_refund", "payout_ref": "py_2", "kind": "partial_refund"},
  {"order_id": "ord_round",  "payout_ref": "py_3", "kind": "currency_rounding"}
]
```

- [ ] **Step 2: Write the failing gate test**

Add to `tests/test_eval.py`. This drives the whole pipeline on `FakeLLMClient` with a matcher that proposes all three fuzzy pairs and a verifier that confirms each kind, then asserts the gate:

```python
import json
from pathlib import Path

from reconcile.core import reconcile_files
from reconcile.llm import FakeLLMClient

FIX = Path(__file__).parent / "fixtures"


def _fuzzy_matcher_response():
    # order indices follow orders_fuzzy.csv row order (ord_fee=0, ord_refund=1,
    # ord_round=2, ord_alone=3); payout indices follow payout_fuzzy.csv
    # (py_1=0, py_2=1, py_3=2, py_4=3). Deterministic pass matches nothing here.
    return {"proposals": [
        {"order_index": 0, "payout_index": 0, "confidence": 0.9, "rationale": "net vs gross", "kind": "fee_offset"},
        {"order_index": 1, "payout_index": 1, "confidence": 0.9, "rationale": "refund shortfall", "kind": "partial_refund"},
        {"order_index": 2, "payout_index": 2, "confidence": 0.9, "rationale": "rounding step", "kind": "currency_rounding"},
    ]}


def test_verified_tier_has_zero_false_match_rate_on_fakes():
    truth = json.loads((FIX / "labeled_verified.json").read_text())
    matcher = FakeLLMClient([_fuzzy_matcher_response()])
    # one verdict per proposal, in proposal order
    verifier = FakeLLMClient([
        {"kind": "fee_offset", "confidence": 0.95},
        {"kind": "partial_refund", "confidence": 0.93},
        {"kind": "currency_rounding", "confidence": 0.94},
    ])
    report = reconcile_files(
        FIX / "payout_fuzzy.csv", FIX / "orders_fuzzy.csv", FIX / "refunds.csv",
        client=matcher, verifier_client=verifier,
    )
    from reconcile.evaluation import verified_metrics
    m = verified_metrics(report, truth)
    # THE GATE: the promoted tier admits zero wrong matches.
    assert m.false_match_rate == 0.0
    assert m.precision == 1.0
    assert len(report.verified) == 3
    assert report.matched == []  # deterministic tier untouched


def test_adversarial_near_miss_never_promotes():
    # matcher claims fee_offset on a pair whose gross-fee != net.
    # Build the near-miss inline so the fixture stays self-describing.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "p.csv"
        p.write_text("ref,gross_amount,fee,net_amount,currency,date\n"
                     "py_x,100.00,3.00,97.10,EUR,2026-07-02\n", encoding="utf-8")
        o = Path(d) / "o.csv"
        o.write_text("order_id,amount,currency,date\n"
                     "ord_x,97.10,EUR,2026-07-02\n", encoding="utf-8")
        matcher = FakeLLMClient([{"proposals": [
            {"order_index": 0, "payout_index": 0, "confidence": 0.99,
             "rationale": "looks like a fee", "kind": "fee_offset"}]}])
        verifier = FakeLLMClient([{"kind": "fee_offset", "confidence": 0.99}])
        report = reconcile_files(p, o, client=matcher, verifier_client=verifier)
        # arithmetic predicate is false (100.00 - 3.00 != 97.10) -> never promoted
        assert report.verified == []
        assert len(report.needs_review) == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval.py -v -k "verified_tier or adversarial"`
Expected: FAIL first on missing fixtures / missing behavior. (If both fixtures from Step 1 are already written, the gate test should pass once Tasks 1–9 are merged; the adversarial test passes on the predicate logic from Task 4. If either fails, STOP and debug — a red gate here means a real hole.)

- [ ] **Step 4: Run the full suite to verify everything is green**

Run: `.venv/bin/python -m pytest`
Expected: PASS — all 84 original tests plus every test added in Tasks 1–10.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/refunds.csv tests/fixtures/labeled_verified.json tests/test_eval.py
git commit -m "test: end-to-end verified false-match gate + adversarial near-miss"
```

---

## Task 11: Docs — mark Plan 3 built

**Files:**
- Modify: `README.md` (if it enumerates plan status), `docs/design/2026-07-30-plan-3-verifier-design.md` (status line)
- Test: none (docs)

- [ ] **Step 1: Update the design doc status**

In `docs/design/2026-07-30-plan-3-verifier-design.md`, change the `Status:` line from `approved for planning` to `implemented`.

- [ ] **Step 2: Update README plan status if present**

Read `README.md`. If it lists plan/phase status, mark Plan 3 (verifier) as done, mirroring how Plans 1–2 are described. If README does not track plan status, skip this step (do not invent a section).

- [ ] **Step 3: Commit**

```bash
git add README.md docs/design/2026-07-30-plan-3-verifier-design.md
git commit -m "docs: mark Plan 3 verifier as implemented"
```

---

## Self-Review

**Spec coverage** (against `docs/design/2026-07-30-plan-3-verifier-design.md`):
- §3.1 `RefundLine` + `VerifiedMatch` → Task 1. ✓
- §3.2 `promote` two-stage gate → Tasks 5, 6. ✓
- §3.3 per-kind predicates + `ROUNDING_EPSILON` → Task 4. ✓
- §3.4 `load_refunds` additive ingest → Tasks 2, 3. ✓
- §3.5 `ReconcileReport.verified` + `reconcile_files` wiring → Tasks 7, 8. ✓
- §4 `verified_metrics` + CI FMR/precision gate → Tasks 9, 10. ✓
- §5 refund fixture + adversarial cases → Task 10. ✓
- §6 zero new deps → Global Constraints; no `pyproject.toml` change needed. ✓
- §7 fail-closed table → Tasks 5, 6 tests (LLMError, disagreement, threshold, no refund). ✓
- §10 success criteria → Task 10 gate + Task 8 `matched` invariant assertion. ✓

**Placeholder scan:** No TBD/TODO; every code step carries real code; every test step carries real asserts. ✓

**Type consistency:** `promote` returns `(list[VerifiedMatch], list[CandidateMatch])` — consumed correctly in Task 8. `classify` returns `dict | None` with keys `kind`/`confidence` — consumed in `promote`. `verified_metrics` reads `v.order.order_id` / `v.payout.ref` matching `VerifiedMatch` fields from Task 1. `ARITH` keys == `KINDS` (asserted at import). `reconcile_files` signature keeps `client` positionally after `refunds_csv`, but all existing call sites pass `client=` as keyword → non-breaking. ✓

**Note on the spec's `partial_refund` linkage:** the predicate links a refund to an order by `r.ref == order.order_id` (the deterministic anchor). Flagged to Erisa; adjust only if target refund data references the payout/charge ref instead.
