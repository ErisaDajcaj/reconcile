# Reconcile — Plan 2 (Agent Layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first two LLM agents of the Reconcile pipeline — an ingest agent that maps arbitrary CSV headers onto the canonical schema, and a matcher agent that proposes fuzzy pairings over the residual left by the deterministic pass — without letting either touch a monetary value or auto-confirm a match.

**Architecture:** A `LLMClient` Protocol is the only seam through which a model enters the system; `FakeLLMClient` (deterministic, free) runs in CI and `AnthropicClient` (lazy SDK import) runs the live eval. The ingest agent returns only a header→field mapping; deterministic code in `parse.py` still coerces every value to `Decimal`/`date`. The matcher agent references lines by index and never emits an amount; its proposals land in a new `needs_review` list on the report, never in `matched`. The CI eval gate therefore stays deterministic with a false-match rate of 0, and model quality is measured off-gate by a new `candidate_recall` metric.

**Tech Stack:** Python 3.12, src-layout, stdlib `csv`/`decimal`/`datetime`, `typing.Protocol`, frozen dataclasses, pytest 8, GitHub Actions. The `anthropic` SDK is an **optional** extra, never a runtime dependency of the core.

**Spec:** [`docs/design/2026-07-20-plan-2-agent-layer-design.md`](../design/2026-07-20-plan-2-agent-layer-design.md)

## Global Constraints

- **Money is never a float.** Every monetary value is `Decimal`, constructed from the raw string (`Decimal(row["amount"])`), never via `float()`. Dates are `datetime.date` via `date.fromisoformat`.
- **The LLM never emits a monetary value.** The ingest agent returns header names only; the matcher agent returns line indices only. Any code path where a model-supplied number becomes an amount is a defect.
- **Fail closed.** Ingest rejects the whole job on an unmapped required field, a low-confidence mapping, or a malformed model response (`MappingError`). The matcher drops any proposal it cannot fully validate; it never fabricates a pair.
- **Nothing fuzzy is auto-confirmed.** `ReconcileReport.matched` holds deterministic exact matches only. Matcher output goes to `ReconcileReport.needs_review`. Promotion is Plan 3's verifier, out of scope here.
- **The core package has zero runtime dependencies.** `pyproject.toml` keeps `dependencies = []`; `anthropic` lives in `[project.optional-dependencies] llm`. `import anthropic` must be lazy (inside `AnthropicClient.__init__`) so `import reconcile.llm` works without the extra.
- **CI runs with no API key and no network.** Every test uses `FakeLLMClient`. Live model calls happen only in `scripts/eval_agents.py`, which exits 0 when `ANTHROPIC_API_KEY` is unset.
- **Model IDs (exact strings):** ingest → `claude-haiku-4-5`, matcher → `claude-sonnet-5`.
- **JSON Schema constraints (structured outputs):** every `object` in a schema sent to the API must carry `"additionalProperties": false`. Numeric bounds (`minimum`/`maximum`) and string-length bounds are **not** supported — validate those in code instead.
- **Backwards compatibility:** `reconcile_files(payout_csv, orders_csv)` with no client must behave exactly as in Plan 1 (canonical headers required, no proposals). The existing tests in `tests/test_core.py`, `tests/test_matching.py`, and the basic-fixture tests in `tests/test_eval.py` must keep passing unchanged.
- **TDD:** every task is RED (write test, watch it fail) → GREEN (minimal implementation, watch it pass) → commit. Run `pytest` from the repo root.

---

### Task 1: The LLM seam (`llm.py`)

**Files:**
- Create: `src/reconcile/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: nothing (this is the base of the agent layer).
- Produces:
  - `class LLMError(RuntimeError)`
  - `class LLMClient(Protocol)` with `structured(self, *, system: str, user: str, schema: dict) -> dict`
  - `class FakeLLMClient` — `__init__(self, responses: list | None = None)`, attribute `calls: list[dict]`, method `structured(*, system, user, schema) -> dict`
  - `class AnthropicClient` — `__init__(self, model: str, *, api_key: str | None = None)`, method `structured(*, system, user, schema) -> dict`
  - Constants `INGEST_MODEL = "claude-haiku-4-5"`, `MATCHER_MODEL = "claude-sonnet-5"`, `MAX_TOKENS = 16000`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm.py`:

```python
import builtins

import pytest

import reconcile.llm as llm_module
from reconcile.llm import AnthropicClient, FakeLLMClient, LLMError


def test_fake_client_returns_canned_response_and_records_the_call():
    client = FakeLLMClient([{"ok": True}])
    out = client.structured(system="s", user="u", schema={"type": "object"})
    assert out == {"ok": True}
    assert client.calls == [{"system": "s", "user": "u", "schema": {"type": "object"}}]


def test_fake_client_raises_when_out_of_responses():
    client = FakeLLMClient([])
    with pytest.raises(LLMError):
        client.structured(system="s", user="u", schema={})


def test_fake_client_can_raise_a_canned_error():
    client = FakeLLMClient([LLMError("boom")])
    with pytest.raises(LLMError, match="boom"):
        client.structured(system="s", user="u", schema={})


def test_importing_the_seam_does_not_import_the_sdk():
    """The core package must install and import with zero runtime dependencies."""
    assert not hasattr(llm_module, "anthropic")


def test_anthropic_client_error_names_the_llm_extra(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ImportError, match=r"\[llm\]"):
        AnthropicClient("claude-sonnet-5")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_llm.py -v`
Expected: FAIL — collection error, `ModuleNotFoundError: No module named 'reconcile.llm'`.

- [ ] **Step 3: Write the implementation**

Create `src/reconcile/llm.py`:

```python
"""The LLM seam: the only place a vendor SDK may enter the system.

Everything downstream depends on the `LLMClient` protocol, never on `anthropic`.
The core package has zero runtime dependencies, so `AnthropicClient` imports the
SDK lazily -- `import reconcile.llm` works without the `llm` extra installed.
"""

import json
from typing import Any, Protocol

INGEST_MODEL = "claude-haiku-4-5"
MATCHER_MODEL = "claude-sonnet-5"

MAX_TOKENS = 16000


class LLMError(RuntimeError):
    """The model returned something unusable. Callers fail closed on this."""


class LLMClient(Protocol):
    def structured(self, *, system: str, user: str, schema: dict) -> dict:
        """Return a JSON object conforming to `schema`, or raise `LLMError`."""
        ...


class FakeLLMClient:
    """Deterministic LLMClient for tests and CI: no network, no key, no cost.

    Exercises the harness (parsing, validation, routing, fail-closed paths),
    never model quality -- that is measured by scripts/eval_agents.py.
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict] = []

    def structured(self, *, system: str, user: str, schema: dict) -> dict:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self._responses:
            raise LLMError("FakeLLMClient: no canned response left")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class AnthropicClient:
    """Real adapter over the Anthropic SDK. Requires: pip install -e '.[llm]'."""

    def __init__(self, model: str, *, api_key: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicClient needs the optional SDK: pip install -e '.[llm]'"
            ) from exc
        self._client = (
            anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        )
        self._model = model

    def structured(self, *, system: str, user: str, schema: dict) -> dict:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError(f"{self._model}: response carried no text block")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{self._model}: response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise LLMError(f"{self._model}: response JSON was not an object")
        return payload
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_llm.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q`
Expected: PASS — nothing else changed yet.

- [ ] **Step 6: Commit**

```bash
git add src/reconcile/llm.py tests/test_llm.py
git commit -m "feat: LLMClient seam with deterministic fake and lazy Anthropic adapter"
```

---

### Task 2: `ColumnMapping` and the parse refactor

Splits "which header feeds which field" (soon supplied by the agent) from "coerce the value" (deterministic, money-safe, unchanged). This task is pure refactor — no LLM involved.

**Files:**
- Modify: `src/reconcile/schema.py` (append `ColumnMapping`)
- Modify: `src/reconcile/parse.py` (whole-file rewrite, shown below)
- Test: `tests/test_parse.py` (append two tests), `tests/test_schema.py` (append one test)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `schema.ColumnMapping` — `@dataclass(frozen=True)` with a single attribute `fields: dict[str, str]` mapping canonical field name → source CSV header.
  - `parse.identity_mapping(fields) -> ColumnMapping`
  - `parse.parse_payouts(path, mapping: ColumnMapping | None = None) -> list[PayoutLine]`
  - `parse.parse_orders(path, mapping: ColumnMapping | None = None) -> list[OrderLine]`
  - `parse.PAYOUT_COLUMNS`, `parse.ORDER_COLUMNS`, `parse.CsvSchemaError` (unchanged names)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parse.py` (and extend its import line to `from reconcile.parse import parse_payouts, parse_orders, CsvSchemaError, identity_mapping`, plus add `from reconcile.schema import ColumnMapping`):

```python
def test_parse_orders_with_a_non_canonical_mapping(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text(
        "Order Reference,Total (EUR),Currency Code,Placed On\n"
        "ord_1,10.00,eur,2026-07-01\n"
    )
    mapping = ColumnMapping(
        fields={
            "order_id": "Order Reference",
            "amount": "Total (EUR)",
            "currency": "Currency Code",
            "date": "Placed On",
        }
    )
    rows = parse_orders(raw, mapping)
    assert rows[0].order_id == "ord_1"
    assert rows[0].amount == Decimal("10.00")
    assert isinstance(rows[0].amount, Decimal)
    assert rows[0].currency == "EUR"
    assert rows[0].order_date == date(2026, 7, 1)


def test_mapping_pointing_at_a_missing_column_fails_closed(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text("Order Reference,Total (EUR)\nord_1,10.00\n")
    mapping = ColumnMapping(
        fields={
            "order_id": "Order Reference",
            "amount": "Total (EUR)",
            "currency": "Currency Code",
            "date": "Placed On",
        }
    )
    with pytest.raises(CsvSchemaError):
        parse_orders(raw, mapping)


def test_identity_mapping_names_every_field_after_itself():
    mapping = identity_mapping({"order_id", "amount"})
    assert mapping.fields == {"order_id": "order_id", "amount": "amount"}
```

Append to `tests/test_schema.py`:

```python
def test_column_mapping_is_frozen():
    from dataclasses import FrozenInstanceError

    from reconcile.schema import ColumnMapping

    mapping = ColumnMapping(fields={"order_id": "Order Reference"})
    assert mapping.fields["order_id"] == "Order Reference"
    with pytest.raises(FrozenInstanceError):
        mapping.fields = {}
```

(If `tests/test_schema.py` does not already import pytest, add `import pytest` at the top.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_parse.py tests/test_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'identity_mapping'` / `cannot import name 'ColumnMapping'`.

- [ ] **Step 3: Write the implementation**

Append to `src/reconcile/schema.py`:

```python
@dataclass(frozen=True)
class ColumnMapping:
    """Canonical field name -> source CSV header. The dict is treated as read-only."""

    fields: dict[str, str]
```

Replace `src/reconcile/parse.py` entirely with:

```python
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from .schema import ColumnMapping, PayoutLine, OrderLine

PAYOUT_COLUMNS = {"ref", "gross_amount", "fee", "net_amount", "currency", "date"}
ORDER_COLUMNS = {"order_id", "amount", "currency", "date"}


class CsvSchemaError(ValueError):
    """Raised when a CSV lacks a column the mapping points at. Fail closed: no partial parse."""


def identity_mapping(fields) -> ColumnMapping:
    """The canonical-headers case: every field is named after itself."""
    return ColumnMapping(fields={f: f for f in fields})


def _require_mapped_columns(header: set[str], mapping: ColumnMapping, required: set[str], path: Path) -> None:
    missing = sorted(f for f in required if mapping.fields.get(f) not in header)
    if missing:
        raise CsvSchemaError(f"{path}: no column feeds required field(s) {missing}")


def _rows(path):
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = set(reader.fieldnames or [])
        yield header, path
        for row in reader:
            yield row, path


def _cell(row: dict, mapping: ColumnMapping, field: str) -> str:
    return row[mapping.fields[field]]


def parse_payouts(path, mapping: ColumnMapping | None = None) -> list[PayoutLine]:
    mapping = mapping or identity_mapping(PAYOUT_COLUMNS)
    gen = _rows(path)
    header, p = next(gen)
    _require_mapped_columns(header, mapping, PAYOUT_COLUMNS, p)
    out = []
    for row, _ in gen:
        out.append(
            PayoutLine(
                ref=_cell(row, mapping, "ref").strip(),
                gross_amount=Decimal(_cell(row, mapping, "gross_amount")),
                fee=Decimal(_cell(row, mapping, "fee")),
                net_amount=Decimal(_cell(row, mapping, "net_amount")),
                currency=_cell(row, mapping, "currency").strip().upper(),
                line_date=date.fromisoformat(_cell(row, mapping, "date").strip()),
            )
        )
    return out


def parse_orders(path, mapping: ColumnMapping | None = None) -> list[OrderLine]:
    mapping = mapping or identity_mapping(ORDER_COLUMNS)
    gen = _rows(path)
    header, p = next(gen)
    _require_mapped_columns(header, mapping, ORDER_COLUMNS, p)
    out = []
    for row, _ in gen:
        out.append(
            OrderLine(
                order_id=_cell(row, mapping, "order_id").strip(),
                amount=Decimal(_cell(row, mapping, "amount")),
                currency=_cell(row, mapping, "currency").strip().upper(),
                order_date=date.fromisoformat(_cell(row, mapping, "date").strip()),
            )
        )
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_parse.py tests/test_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite (Plan 1 regression check)**

Run: `pytest -q`
Expected: PASS — every pre-existing test still green; `parse_payouts(path)` / `parse_orders(path)` behave exactly as before.

- [ ] **Step 6: Commit**

```bash
git add src/reconcile/schema.py src/reconcile/parse.py tests/test_parse.py tests/test_schema.py
git commit -m "refactor: split header->field mapping from value coercion in parse"
```

---

### Task 3: The ingest agent (`ingest.py`)

**Files:**
- Create: `src/reconcile/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `llm.LLMClient`, `llm.LLMError`, `FakeLLMClient` (tests); `parse.identity_mapping`, `parse.parse_payouts`, `parse.parse_orders`, `parse.PAYOUT_COLUMNS`, `parse.ORDER_COLUMNS`; `schema.ColumnMapping`.
- Produces:
  - `class MappingError(ValueError)`
  - `MIN_MAPPING_CONFIDENCE = 0.9`
  - `infer_mapping(headers, target_fields, client, *, min_confidence=MIN_MAPPING_CONFIDENCE) -> ColumnMapping`
  - `read_headers(path) -> list[str]`
  - `load_payouts(path, client: LLMClient | None = None) -> list[PayoutLine]`
  - `load_orders(path, client: LLMClient | None = None) -> list[OrderLine]`

The model returns a **list of `{field, header}` pairs**, not a free-form object: structured outputs reject `additionalProperties` set to anything other than `false`, so a dict with arbitrary keys is not expressible as a schema.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingest.py`:

```python
from decimal import Decimal

import pytest

from reconcile.ingest import (
    MIN_MAPPING_CONFIDENCE,
    MappingError,
    infer_mapping,
    load_orders,
)
from reconcile.llm import FakeLLMClient, LLMError
from reconcile.parse import ORDER_COLUMNS

RAW_HEADERS = ["Order Reference", "Total (EUR)", "Currency Code", "Placed On"]

GOOD_MAPPING = {
    "mapping": [
        {"field": "order_id", "header": "Order Reference"},
        {"field": "amount", "header": "Total (EUR)"},
        {"field": "currency", "header": "Currency Code"},
        {"field": "date", "header": "Placed On"},
    ],
    "confidence": 0.97,
}


def _raw_orders_csv(tmp_path):
    path = tmp_path / "raw_orders.csv"
    path.write_text(
        "Order Reference,Total (EUR),Currency Code,Placed On\n"
        "ord_1,10.00,eur,2026-07-01\n"
    )
    return path


def test_canonical_headers_short_circuit_without_calling_the_model():
    client = FakeLLMClient([])
    mapping = infer_mapping(sorted(ORDER_COLUMNS), ORDER_COLUMNS, client)
    assert mapping.fields == {f: f for f in ORDER_COLUMNS}
    assert client.calls == []


def test_infer_mapping_reads_the_agent_proposal():
    client = FakeLLMClient([GOOD_MAPPING])
    mapping = infer_mapping(RAW_HEADERS, ORDER_COLUMNS, client)
    assert mapping.fields["order_id"] == "Order Reference"
    assert mapping.fields["date"] == "Placed On"
    assert len(client.calls) == 1


def test_low_confidence_rejects_the_whole_job():
    low = dict(GOOD_MAPPING, confidence=MIN_MAPPING_CONFIDENCE - 0.01)
    with pytest.raises(MappingError, match="confidence"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([low]))


def test_unmapped_required_field_rejects_the_whole_job():
    partial = {
        "mapping": [{"field": "order_id", "header": "Order Reference"}],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="unmapped"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([partial]))


def test_hallucinated_header_is_treated_as_unmapped():
    invented = {
        "mapping": [
            {"field": "order_id", "header": "Order Reference"},
            {"field": "amount", "header": "Total (EUR)"},
            {"field": "currency", "header": "Currency Code"},
            {"field": "date", "header": "A Column That Does Not Exist"},
        ],
        "confidence": 0.99,
    }
    with pytest.raises(MappingError, match="unmapped"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([invented]))


def test_malformed_agent_response_rejects_the_whole_job():
    with pytest.raises(MappingError, match="malformed"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, FakeLLMClient([{"mapping": "nope"}]))


def test_llm_error_becomes_a_mapping_error():
    client = FakeLLMClient([LLMError("model exploded")])
    with pytest.raises(MappingError):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, client)


def test_non_canonical_headers_without_a_client_reject_the_whole_job():
    with pytest.raises(MappingError, match="no LLM client"):
        infer_mapping(RAW_HEADERS, ORDER_COLUMNS, None)


def test_load_orders_maps_then_parses_deterministically(tmp_path):
    rows = load_orders(_raw_orders_csv(tmp_path), FakeLLMClient([GOOD_MAPPING]))
    assert len(rows) == 1
    assert rows[0].order_id == "ord_1"
    assert rows[0].amount == Decimal("10.00")
    assert isinstance(rows[0].amount, Decimal)
    assert rows[0].currency == "EUR"


def test_load_orders_on_canonical_headers_needs_no_client():
    rows = load_orders("tests/fixtures/orders_basic.csv")
    assert [r.order_id for r in rows] == ["ord_1", "ord_2", "ord_3", "ord_missing"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reconcile.ingest'`.

- [ ] **Step 3: Write the implementation**

Create `src/reconcile/ingest.py`:

```python
"""Ingest agent: the LLM maps headers, deterministic code coerces values.

The model is asked exactly one question per file -- "which source header feeds
which canonical field?" -- and answers with header names only. It never sees a
task where it could produce a number.
"""

import csv
from pathlib import Path

from .llm import LLMClient, LLMError
from .parse import (
    ORDER_COLUMNS,
    PAYOUT_COLUMNS,
    identity_mapping,
    parse_orders,
    parse_payouts,
)
from .schema import ColumnMapping, OrderLine, PayoutLine

MIN_MAPPING_CONFIDENCE = 0.9

_SYSTEM = (
    "You map the column headers of a CSV onto a fixed canonical schema. "
    "Every header you return must be one of the source headers, copied verbatim. "
    "Never invent a header, never read or interpret data values, never return a "
    "number you computed. If a required field has no plausible source header, "
    "leave it out and lower your confidence."
)


class MappingError(ValueError):
    """Headers could not be mapped with confidence. Fail closed: reject the job."""


def _mapping_schema(target_fields: set[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "mapping": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": sorted(target_fields)},
                        "header": {"type": "string"},
                    },
                    "required": ["field", "header"],
                    "additionalProperties": False,
                },
            },
            "confidence": {"type": "number"},
        },
        "required": ["mapping", "confidence"],
        "additionalProperties": False,
    }


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def infer_mapping(
    headers,
    target_fields,
    client: LLMClient | None,
    *,
    min_confidence: float = MIN_MAPPING_CONFIDENCE,
) -> ColumnMapping:
    headers = list(headers)
    target = set(target_fields)

    # Deterministic short-circuit: the common case stays free and model-free.
    if target <= set(headers):
        return identity_mapping(target)

    if client is None:
        raise MappingError(
            f"headers {sorted(headers)} are not canonical and no LLM client was supplied"
        )

    user = (
        "Canonical fields: " + ", ".join(sorted(target)) + "\n"
        "Source headers: " + ", ".join(headers)
    )
    try:
        out = client.structured(system=_SYSTEM, user=user, schema=_mapping_schema(target))
    except LLMError as exc:
        raise MappingError(f"header mapping failed: {exc}") from exc

    pairs = out.get("mapping")
    confidence = out.get("confidence")
    if not isinstance(pairs, list) or not _is_number(confidence):
        raise MappingError(f"malformed mapping response: {out!r}")
    if confidence < min_confidence:
        raise MappingError(
            f"mapping confidence {confidence} below threshold {min_confidence}"
        )

    fields: dict[str, str] = {}
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        field, header = pair.get("field"), pair.get("header")
        if field in target and header in headers:
            fields.setdefault(field, header)

    missing = sorted(target - fields.keys())
    if missing:
        raise MappingError(f"required field(s) left unmapped: {missing}")
    return ColumnMapping(fields=fields)


def read_headers(path) -> list[str]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh), [])


def load_payouts(path, client: LLMClient | None = None) -> list[PayoutLine]:
    mapping = infer_mapping(read_headers(path), PAYOUT_COLUMNS, client)
    return parse_payouts(path, mapping)


def load_orders(path, client: LLMClient | None = None) -> list[OrderLine]:
    mapping = infer_mapping(read_headers(path), ORDER_COLUMNS, client)
    return parse_orders(path, mapping)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_ingest.py -v`
Expected: PASS, 11 passed.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/reconcile/ingest.py tests/test_ingest.py
git commit -m "feat: ingest agent maps headers, fails closed below confidence threshold"
```

---

### Task 4: The matcher agent (`matcher.py`)

**Files:**
- Create: `src/reconcile/matcher.py`
- Test: `tests/test_matcher.py`

**Interfaces:**
- Consumes: `llm.LLMClient`, `llm.LLMError`, `FakeLLMClient` (tests); `schema.OrderLine`, `schema.PayoutLine`.
- Produces:
  - `KINDS = ("fee_offset", "partial_refund", "currency_rounding", "other")`
  - `@dataclass(frozen=True) class CandidateMatch` with attributes `order: OrderLine`, `payout: PayoutLine`, `confidence: float`, `rationale: str`, `kind: str`
  - `propose_matches(unmatched_orders, unmatched_payouts, client) -> list[CandidateMatch]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_matcher.py`:

```python
from datetime import date
from decimal import Decimal

from reconcile.llm import FakeLLMClient, LLMError
from reconcile.matcher import CandidateMatch, propose_matches
from reconcile.schema import OrderLine, PayoutLine

ORDERS = [
    OrderLine(order_id="ord_fee", amount=Decimal("97.10"), currency="EUR", order_date=date(2026, 7, 2)),
    OrderLine(order_id="ord_alone", amount=Decimal("88.00"), currency="EUR", order_date=date(2026, 7, 2)),
]
PAYOUTS = [
    PayoutLine(
        ref="py_1",
        gross_amount=Decimal("100.00"),
        fee=Decimal("2.90"),
        net_amount=Decimal("97.10"),
        currency="EUR",
        line_date=date(2026, 7, 2),
    ),
]


def _proposal(**overrides) -> dict:
    base = {
        "order_index": 0,
        "payout_index": 0,
        "confidence": 0.91,
        "rationale": "the order records the net, the payout the gross",
        "kind": "fee_offset",
    }
    base.update(overrides)
    return {"proposals": [base]}


def test_proposal_is_resolved_back_to_the_real_line_objects():
    client = FakeLLMClient([_proposal()])
    candidates = propose_matches(ORDERS, PAYOUTS, client)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, CandidateMatch)
    assert candidate.order is ORDERS[0]
    assert candidate.payout is PAYOUTS[0]
    assert candidate.kind == "fee_offset"
    assert candidate.confidence == 0.91


def test_no_client_means_no_proposals():
    assert propose_matches(ORDERS, PAYOUTS, None) == []


def test_empty_residual_never_calls_the_model():
    client = FakeLLMClient([])
    assert propose_matches([], PAYOUTS, client) == []
    assert propose_matches(ORDERS, [], client) == []
    assert client.calls == []


def test_out_of_range_index_is_dropped():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(payout_index=7)])) == []
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(order_index=-1)])) == []


def test_unknown_kind_is_dropped():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(kind="vibes")])) == []


def test_out_of_band_confidence_is_dropped():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(confidence=1.4)])) == []


def test_non_integer_index_is_dropped():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([_proposal(order_index="0")])) == []


def test_a_line_is_proposed_at_most_once():
    payload = {
        "proposals": [
            {"order_index": 0, "payout_index": 0, "confidence": 0.9, "rationale": "a", "kind": "fee_offset"},
            {"order_index": 1, "payout_index": 0, "confidence": 0.8, "rationale": "b", "kind": "other"},
        ]
    }
    candidates = propose_matches(ORDERS, PAYOUTS, FakeLLMClient([payload]))
    assert [c.order.order_id for c in candidates] == ["ord_fee"]


def test_llm_error_leaves_the_residual_without_candidates():
    client = FakeLLMClient([LLMError("model exploded")])
    assert propose_matches(ORDERS, PAYOUTS, client) == []


def test_malformed_payload_leaves_the_residual_without_candidates():
    assert propose_matches(ORDERS, PAYOUTS, FakeLLMClient([{"proposals": "nope"}])) == []


def test_the_prompt_never_asks_the_model_for_an_amount():
    client = FakeLLMClient([_proposal()])
    propose_matches(ORDERS, PAYOUTS, client)
    schema = client.calls[0]["schema"]
    item_properties = schema["properties"]["proposals"]["items"]["properties"]
    assert set(item_properties) == {
        "order_index",
        "payout_index",
        "confidence",
        "rationale",
        "kind",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_matcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reconcile.matcher'`.

- [ ] **Step 3: Write the implementation**

Create `src/reconcile/matcher.py`:

```python
"""Matcher agent: proposes fuzzy pairings over the deterministic residual.

The agent is never given a task where it could emit money. It sees already-typed
lines and answers with indices; code resolves those indices back to the real
objects and drops anything it cannot fully validate. Nothing here is confirmed --
every proposal lands in the human-review queue.
"""

from dataclasses import dataclass

from .llm import LLMClient, LLMError
from .schema import OrderLine, PayoutLine

KINDS = ("fee_offset", "partial_refund", "currency_rounding", "other")

_SYSTEM = (
    "You pair unmatched orders with unmatched payout lines that an exact-match "
    "pass could not reconcile. Reference every line ONLY by its index. Never "
    "output an amount and never recompute a number. Propose a pair only when a "
    "concrete explanation applies: fee_offset (the order records the net, the "
    "payout the gross), partial_refund (the payout is smaller because part was "
    "refunded), currency_rounding (the two differ by a rounding step), otherwise "
    "'other'. Use each order index and each payout index at most once. Nothing "
    "you propose is confirmed automatically: a human reviews every pair."
)

_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order_index": {"type": "integer"},
                    "payout_index": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                },
                "required": [
                    "order_index",
                    "payout_index",
                    "confidence",
                    "rationale",
                    "kind",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["proposals"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class CandidateMatch:
    order: OrderLine
    payout: PayoutLine
    confidence: float
    rationale: str
    kind: str


def _render(orders: list[OrderLine], payouts: list[PayoutLine]) -> str:
    lines = ["Unmatched orders:"]
    for i, o in enumerate(orders):
        lines.append(
            f"  [{i}] id={o.order_id} amount={o.amount} {o.currency} date={o.order_date}"
        )
    lines.append("Unmatched payout lines:")
    for i, p in enumerate(payouts):
        lines.append(
            f"  [{i}] ref={p.ref} gross={p.gross_amount} fee={p.fee} "
            f"net={p.net_amount} {p.currency} date={p.line_date}"
        )
    return "\n".join(lines)


def _is_index(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def propose_matches(
    unmatched_orders: list[OrderLine],
    unmatched_payouts: list[PayoutLine],
    client: LLMClient | None,
) -> list[CandidateMatch]:
    if client is None or not unmatched_orders or not unmatched_payouts:
        return []

    try:
        out = client.structured(
            system=_SYSTEM,
            user=_render(unmatched_orders, unmatched_payouts),
            schema=_PROPOSAL_SCHEMA,
        )
    except LLMError:
        # Fail closed: the residual simply gets no candidates. Safe, because
        # nothing here would have been auto-confirmed anyway.
        return []

    proposals = out.get("proposals")
    if not isinstance(proposals, list):
        return []

    seen_orders: set[int] = set()
    seen_payouts: set[int] = set()
    candidates: list[CandidateMatch] = []

    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        order_index = proposal.get("order_index")
        payout_index = proposal.get("payout_index")
        if not _is_index(order_index) or not _is_index(payout_index):
            continue
        if not 0 <= order_index < len(unmatched_orders):
            continue
        if not 0 <= payout_index < len(unmatched_payouts):
            continue
        if order_index in seen_orders or payout_index in seen_payouts:
            continue
        confidence = proposal.get("confidence")
        if not _is_number(confidence) or not 0.0 <= confidence <= 1.0:
            continue
        rationale = proposal.get("rationale")
        kind = proposal.get("kind")
        if not isinstance(rationale, str) or kind not in KINDS:
            continue

        seen_orders.add(order_index)
        seen_payouts.add(payout_index)
        candidates.append(
            CandidateMatch(
                order=unmatched_orders[order_index],
                payout=unmatched_payouts[payout_index],
                confidence=float(confidence),
                rationale=rationale,
                kind=kind,
            )
        )
    return candidates
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_matcher.py -v`
Expected: PASS, 11 passed.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/reconcile/matcher.py tests/test_matcher.py
git commit -m "feat: matcher agent proposes fuzzy pairings by index, drops what it cannot validate"
```

---

### Task 5: Report and pipeline wiring

**Files:**
- Modify: `src/reconcile/matching.py` (add `needs_review` to `ReconcileReport`)
- Modify: `src/reconcile/core.py` (whole-file rewrite, shown below)
- Test: `tests/test_matching.py` (append one test), `tests/test_core.py` (append two tests)

**Interfaces:**
- Consumes: `matcher.CandidateMatch`, `matcher.propose_matches`; `ingest.load_payouts`, `ingest.load_orders`; `llm.LLMClient`.
- Produces:
  - `ReconcileReport` gains `needs_review: list[CandidateMatch] = field(default_factory=list)` as its fourth field.
  - `core.reconcile_files(payout_csv, orders_csv, client=None, *, ingest_client=None) -> ReconcileReport`

`ingest_client` defaults to `client` and exists so the live eval can run ingest on Haiku and the matcher on Sonnet, as the spec's §3.1 model split requires. `matcher.py` imports only `llm` and `schema`, so `matching.py` importing `matcher` creates no cycle.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_matching.py`:

```python
def test_report_starts_with_an_empty_review_queue():
    from reconcile.matching import ReconcileReport

    report = ReconcileReport()
    assert report.needs_review == []
```

Append to `tests/test_core.py` (extend its imports with `from reconcile.llm import FakeLLMClient`):

```python
def test_client_none_preserves_the_plan_1_pipeline():
    report = reconcile_files(PAYOUTS, ORDERS)
    assert report.needs_review == []
    assert sorted(o.order_id for o, _ in report.matched) == ["ord_1", "ord_2", "ord_3"]


def test_candidates_land_in_needs_review_and_never_in_matched():
    payload = {
        "proposals": [
            {
                "order_index": 0,
                "payout_index": 0,
                "confidence": 0.88,
                "rationale": "amounts differ by a plausible fee",
                "kind": "fee_offset",
            }
        ]
    }
    report = reconcile_files(PAYOUTS, ORDERS, client=FakeLLMClient([payload]))
    assert sorted(o.order_id for o, _ in report.matched) == ["ord_1", "ord_2", "ord_3"]
    assert len(report.needs_review) == 1
    assert report.needs_review[0].order.order_id == "ord_missing"
    assert report.needs_review[0].payout.ref == "ord_ghost"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_core.py tests/test_matching.py -v`
Expected: FAIL — `AttributeError: 'ReconcileReport' object has no attribute 'needs_review'`, and `TypeError: reconcile_files() got an unexpected keyword argument 'client'`.

- [ ] **Step 3: Write the implementation**

In `src/reconcile/matching.py`, add the import and the field. The top of the file becomes:

```python
from dataclasses import dataclass, field

from .matcher import CandidateMatch
from .schema import PayoutLine, OrderLine


@dataclass
class ReconcileReport:
    matched: list[tuple[OrderLine, PayoutLine]] = field(default_factory=list)
    unmatched_orders: list[OrderLine] = field(default_factory=list)
    unmatched_payouts: list[PayoutLine] = field(default_factory=list)
    # Candidate pairings over the residual. Never auto-confirmed: promoting one
    # into `matched` is the Plan 3 verifier's job.
    needs_review: list[CandidateMatch] = field(default_factory=list)
```

The rest of `matching.py` (`_key`, `deterministic_match`) is unchanged.

Replace `src/reconcile/core.py` entirely with:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_core.py tests/test_matching.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q`
Expected: PASS — including the untouched Plan 1 eval-gate tests.

- [ ] **Step 6: Commit**

```bash
git add src/reconcile/matching.py src/reconcile/core.py tests/test_core.py tests/test_matching.py
git commit -m "feat: route matcher proposals to needs_review, wire agents into the pipeline"
```

---

### Task 6: Fuzzy fixtures and the eval extension

**Files:**
- Create: `tests/fixtures/payout_fuzzy.csv`, `tests/fixtures/orders_fuzzy.csv`, `tests/fixtures/orders_fuzzy_raw_headers.csv`, `tests/fixtures/labeled_fuzzy.json`
- Modify: `src/reconcile/evaluation.py` (append `candidate_recall`)
- Test: `tests/test_eval.py` (append fixtures block and four tests)

**Interfaces:**
- Consumes: `matching.ReconcileReport` (its `needs_review` field), `core.reconcile_files`, `llm.FakeLLMClient`.
- Produces: `evaluation.candidate_recall(report, fuzzy_truth: list[dict]) -> float`

The fuzzy fixture deliberately contains **no** exact match: order IDs and payout refs differ, so `deterministic_match` leaves the whole file in the residual and the "no fuzzy proposal leaks into `matched`" assertion is meaningful.

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/payout_fuzzy.csv`:

```csv
ref,gross_amount,fee,net_amount,currency,date
py_1,100.00,2.90,97.10,EUR,2026-07-02
py_2,18.00,0.82,17.18,EUR,2026-07-02
py_3,50.00,1.75,48.25,EUR,2026-07-02
py_4,7.00,0.51,6.49,EUR,2026-07-02
```

`tests/fixtures/orders_fuzzy.csv`:

```csv
order_id,amount,currency,date
ord_fee,97.10,EUR,2026-07-02
ord_refund,30.00,EUR,2026-07-02
ord_round,49.99,EUR,2026-07-02
ord_alone,88.00,EUR,2026-07-02
```

`tests/fixtures/orders_fuzzy_raw_headers.csv` — the same four orders behind non-canonical headers, to exercise the ingest agent:

```csv
Order Reference,Total (EUR),Currency Code,Placed On
ord_fee,97.10,EUR,2026-07-02
ord_refund,30.00,EUR,2026-07-02
ord_round,49.99,EUR,2026-07-02
ord_alone,88.00,EUR,2026-07-02
```

`tests/fixtures/labeled_fuzzy.json` — ground truth. `ord_alone` and `py_4` are unrelated distractors and appear in no pair:

```json
[
  {"order_id": "ord_fee",    "payout_ref": "py_1", "kind": "fee_offset"},
  {"order_id": "ord_refund", "payout_ref": "py_2", "kind": "partial_refund"},
  {"order_id": "ord_round",  "payout_ref": "py_3", "kind": "currency_rounding"}
]
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_eval.py` (extend its imports with `from reconcile.evaluation import candidate_recall` and `from reconcile.llm import FakeLLMClient`):

```python
FUZZY_PAYOUTS = "tests/fixtures/payout_fuzzy.csv"
FUZZY_ORDERS = "tests/fixtures/orders_fuzzy.csv"
FUZZY_TRUTH = "tests/fixtures/labeled_fuzzy.json"

# Residual order matches file order: orders ord_fee/ord_refund/ord_round/ord_alone
# are indices 0-3, payouts py_1..py_4 are indices 0-3.
ALL_THREE = {
    "proposals": [
        {"order_index": 0, "payout_index": 0, "confidence": 0.94,
         "rationale": "order records the net, payout the gross", "kind": "fee_offset"},
        {"order_index": 1, "payout_index": 1, "confidence": 0.81,
         "rationale": "payout is smaller by a plausible partial refund", "kind": "partial_refund"},
        {"order_index": 2, "payout_index": 2, "confidence": 0.88,
         "rationale": "amounts differ by one rounding step", "kind": "currency_rounding"},
    ]
}


def _fuzzy_truth():
    with open(FUZZY_TRUTH, encoding="utf-8") as fh:
        return json.load(fh)


def test_no_fuzzy_proposal_is_ever_auto_confirmed():
    """The CI gate's core promise: only the deterministic pass confirms anything."""
    report = reconcile_files(FUZZY_PAYOUTS, FUZZY_ORDERS, client=FakeLLMClient([ALL_THREE]))
    assert report.matched == []
    assert len(report.needs_review) == 3
    m = evaluate(report, [])
    assert m.false_match_rate == 0.0
    assert m.precision == 1.0


def test_candidate_recall_counts_surfaced_fuzzy_pairs():
    report = reconcile_files(FUZZY_PAYOUTS, FUZZY_ORDERS, client=FakeLLMClient([ALL_THREE]))
    assert candidate_recall(report, _fuzzy_truth()) == 1.0


def test_candidate_recall_is_zero_when_nothing_is_proposed():
    empty = {"proposals": []}
    report = reconcile_files(FUZZY_PAYOUTS, FUZZY_ORDERS, client=FakeLLMClient([empty]))
    assert candidate_recall(report, _fuzzy_truth()) == 0.0


def test_candidate_recall_ignores_proposals_outside_the_ground_truth():
    """Surfacing the distractor pair must not inflate recall."""
    distractor = {
        "proposals": [
            {"order_index": 3, "payout_index": 3, "confidence": 0.55,
             "rationale": "no relation found", "kind": "other"}
        ]
    }
    report = reconcile_files(FUZZY_PAYOUTS, FUZZY_ORDERS, client=FakeLLMClient([distractor]))
    assert len(report.needs_review) == 1
    assert candidate_recall(report, _fuzzy_truth()) == 0.0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_eval.py -v`
Expected: FAIL — `ImportError: cannot import name 'candidate_recall' from 'reconcile.evaluation'`.

- [ ] **Step 4: Write the implementation**

Append to `src/reconcile/evaluation.py`:

```python
def candidate_recall(report: ReconcileReport, fuzzy_truth: list[dict]) -> float:
    """Share of true fuzzy pairs surfaced in `needs_review`.

    Deliberately measured, never gated: it scores model quality, which is
    non-deterministic and costs money. The CI gate stays on `evaluate`, which
    scores auto-confirmed matches only.
    """
    surfaced = {(c.order.order_id, c.payout.ref) for c in report.needs_review}
    truth = {(t["order_id"], t["payout_ref"]) for t in fuzzy_truth}
    if not truth:
        return 1.0
    return len(surfaced & truth) / len(truth)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_eval.py -v`
Expected: PASS — the four new tests plus the two pre-existing deterministic gate tests.

- [ ] **Step 6: Run the whole suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/payout_fuzzy.csv tests/fixtures/orders_fuzzy.csv \
        tests/fixtures/orders_fuzzy_raw_headers.csv tests/fixtures/labeled_fuzzy.json \
        src/reconcile/evaluation.py tests/test_eval.py
git commit -m "feat: fuzzy fixtures, candidate_recall metric, no-leak assertion on the gate"
```

---

### Task 7: Live eval script, packaging, docs

**Files:**
- Create: `scripts/eval_agents.py`
- Modify: `pyproject.toml` (add the `llm` extra)
- Modify: `README.md` (status + develop section)

**Interfaces:**
- Consumes: `core.reconcile_files`, `evaluation.candidate_recall`, `ingest.load_orders`, `llm.AnthropicClient`, `llm.INGEST_MODEL`, `llm.MATCHER_MODEL`.
- Produces: no importable API — a runnable script and the packaging contract.

- [ ] **Step 1: Write the live eval script**

Create `scripts/eval_agents.py`:

```python
#!/usr/bin/env python
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
```

- [ ] **Step 2: Verify the script is key-gated and does not call the API**

Run: `env -u ANTHROPIC_API_KEY python scripts/eval_agents.py`
Expected: prints `ANTHROPIC_API_KEY not set - skipping the live eval.` and exits 0, with no network call. (If the script cannot import `reconcile`, install the package first: `pip install -e ".[dev]"`.)

- [ ] **Step 3: Add the optional extra to `pyproject.toml`**

Change the dependency block to:

```toml
dependencies = []                       # the safety layer needs nothing at runtime

[project.optional-dependencies]
llm = ["anthropic>=0.119"]              # the agents are optional; the guardrails are not
dev = ["pytest>=8.0"]
```

`dependencies` stays empty and `dev` stays as-is — the CI gate installs `[dev]` and must never pull in `anthropic`.

- [ ] **Step 4: Verify the packaging claim holds**

Run: `pip install -e ".[dev]" && python -c "import reconcile.llm; print('core imports without the SDK')" && pytest -q`
Expected: the import succeeds and the whole suite passes with `anthropic` absent from the `[dev]` install set. This is the check that makes "the model is optional, the safety layer is not" a verifiable fact rather than a claim.

- [ ] **Step 5: Update the README**

Replace the `## Status` and `## Develop` sections of `README.md` with:

```markdown
## Status

Plan 2 (this milestone): the deterministic core from Plan 1, plus two LLM agents —
an ingest agent that maps arbitrary CSV headers onto the canonical schema, and a
matcher agent that proposes fuzzy pairings over the residual the exact-match pass
could not reconcile. Neither agent ever handles a monetary value, and **no fuzzy
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
```

- [ ] **Step 6: Run the full suite one last time**

Run: `pytest -q`
Expected: PASS, all tests green.

- [ ] **Step 7: Commit**

```bash
git add scripts/eval_agents.py pyproject.toml README.md
git commit -m "feat: live agent eval script, optional llm extra, README for Plan 2"
```

---

## Done criteria

- `pytest` green with no `ANTHROPIC_API_KEY` and no network.
- `pip install -e ".[dev]"` does not install `anthropic`; `import reconcile.llm` still works.
- `reconcile_files(payouts, orders)` (no client) reproduces Plan 1 behaviour exactly.
- On the fuzzy fixture, `report.matched` is empty and every proposal is in `report.needs_review`.
- `scripts/eval_agents.py` exits 0 and calls nothing when the key is unset.
- Every fail-closed row in the design's §7 table is covered by a test:
  ingest unmapped/low-confidence → `MappingError`; `LLMError` in ingest → `MappingError`;
  `LLMError` in the matcher → empty candidate list; out-of-range index → dropped.
