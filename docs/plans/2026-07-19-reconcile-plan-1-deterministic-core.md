# Reconcile — Plan 1: Deterministic Core + First Eval Test in CI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic reconciliation skeleton (canonical schema → CSV parse → exact-match pass → reconciliation report) and gate it with a labeled eval test running in GitHub Actions CI.

**Architecture:** Pure-Python, dependency-light walking skeleton. No LLM yet — the deterministic pass and the eval/CI harness are the foundation every later (agentic) plan gates on. Money is `Decimal` end-to-end; canonical data are frozen dataclasses; matching is idempotent (no line matched twice).

**Tech Stack:** Python 3.12 · stdlib `csv`/`json`/`decimal` · `pytest` · GitHub Actions.

## Global Constraints

- Python **3.12**.
- All monetary values are `decimal.Decimal` — **never `float`**. Parse straight from string.
- Canonical records are **`@dataclass(frozen=True)`**.
- Plan 1 adds **no runtime dependencies** beyond `pytest` (dev-only). FastAPI / Anthropic SDK arrive in later plans.
- Reconciliation must be **idempotent**: a payout line and an order line each match **at most once**; re-running yields an identical report.
- Package import root is `reconcile` under `src/` (src-layout). Tests import `from reconcile...`.
- Eval CI gate thresholds: **false-match-rate == 0.0** and **precision == 1.0** for the deterministic pass.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/reconcile/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`
- Create: `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `reconcile` package; `pytest` runnable from repo root resolving `from reconcile...`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "reconcile"
version = "0.1.0"
description = "Agentic reconciliation & verification for Stripe payouts (deterministic core)"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Create package + test package markers**

`src/reconcile/__init__.py`:
```python
"""Reconcile — deterministic reconciliation core."""
```

`tests/__init__.py`:
```python
```

- [ ] **Step 3: Create `.gitignore`**

```gitignore
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
*.egg-info/
dist/
build/
.env
.env.local
*.db
```

- [ ] **Step 4: Create `README.md` stub**

```markdown
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
```

- [ ] **Step 5: Verify pytest resolves the package (collects zero tests, no import error)**

Run: `pip install -e ".[dev]" && pytest -q`
Expected: `no tests ran` (exit 5) with **no import/config errors**.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/reconcile/__init__.py tests/__init__.py .gitignore README.md
git commit -m "chore: scaffold reconcile python package (src-layout)"
```

---

### Task 2: Canonical schema

**Files:**
- Create: `src/reconcile/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PayoutLine(ref: str, gross_amount: Decimal, fee: Decimal, net_amount: Decimal, currency: str, line_date: date)` — frozen.
  - `OrderLine(order_id: str, amount: Decimal, currency: str, order_date: date)` — frozen.

- [ ] **Step 1: Write the failing test**

`tests/test_schema.py`:
```python
from datetime import date
from decimal import Decimal

from reconcile.schema import PayoutLine, OrderLine


def test_payout_line_is_frozen_and_typed():
    p = PayoutLine(
        ref="ord_1",
        gross_amount=Decimal("10.00"),
        fee=Decimal("0.59"),
        net_amount=Decimal("9.41"),
        currency="EUR",
        line_date=date(2026, 7, 1),
    )
    assert p.ref == "ord_1"
    assert p.gross_amount == Decimal("10.00")
    try:
        p.ref = "changed"  # frozen -> should raise
        assert False, "PayoutLine must be frozen"
    except AttributeError:
        pass


def test_order_line_holds_decimal_amount():
    o = OrderLine(
        order_id="ord_1",
        amount=Decimal("10.00"),
        currency="EUR",
        order_date=date(2026, 7, 1),
    )
    assert o.amount == Decimal("10.00")
    assert isinstance(o.amount, Decimal)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reconcile.schema'`.

- [ ] **Step 3: Write minimal implementation**

`src/reconcile/schema.py`:
```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class PayoutLine:
    ref: str
    gross_amount: Decimal
    fee: Decimal
    net_amount: Decimal
    currency: str
    line_date: date


@dataclass(frozen=True)
class OrderLine:
    order_id: str
    amount: Decimal
    currency: str
    order_date: date
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/schema.py tests/test_schema.py
git commit -m "feat: add canonical PayoutLine/OrderLine schema"
```

---

### Task 3: CSV parsing

**Files:**
- Create: `src/reconcile/parse.py`
- Create: `tests/fixtures/payout_basic.csv`
- Create: `tests/fixtures/orders_basic.csv`
- Test: `tests/test_parse.py`

**Interfaces:**
- Consumes: `PayoutLine`, `OrderLine` from Task 2.
- Produces:
  - `parse_payouts(path: str | Path) -> list[PayoutLine]`
  - `parse_orders(path: str | Path) -> list[OrderLine]`
  - `class CsvSchemaError(ValueError)` — raised on missing required columns (fail closed, no partial parse).
- Expected payout columns: `ref,gross_amount,fee,net_amount,currency,date`.
- Expected order columns: `order_id,amount,currency,date`.
- `date` is ISO `YYYY-MM-DD`.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/payout_basic.csv`:
```csv
ref,gross_amount,fee,net_amount,currency,date
ord_1,10.00,0.59,9.41,EUR,2026-07-01
ord_2,25.00,0.95,24.05,EUR,2026-07-01
ord_3,40.00,1.30,38.70,EUR,2026-07-01
ord_ghost,5.00,0.44,4.56,EUR,2026-07-01
```

`tests/fixtures/orders_basic.csv`:
```csv
order_id,amount,currency,date
ord_1,10.00,EUR,2026-07-01
ord_2,25.00,EUR,2026-07-01
ord_3,40.00,EUR,2026-07-01
ord_missing,12.00,EUR,2026-07-01
```

- [ ] **Step 2: Write the failing test**

`tests/test_parse.py`:
```python
from decimal import Decimal
from datetime import date

import pytest

from reconcile.parse import parse_payouts, parse_orders, CsvSchemaError

PAYOUTS = "tests/fixtures/payout_basic.csv"
ORDERS = "tests/fixtures/orders_basic.csv"


def test_parse_payouts_returns_typed_rows():
    rows = parse_payouts(PAYOUTS)
    assert len(rows) == 4
    first = rows[0]
    assert first.ref == "ord_1"
    assert first.gross_amount == Decimal("10.00")
    assert first.fee == Decimal("0.59")
    assert first.net_amount == Decimal("9.41")
    assert first.currency == "EUR"
    assert first.line_date == date(2026, 7, 1)


def test_parse_orders_returns_typed_rows():
    rows = parse_orders(ORDERS)
    assert len(rows) == 4
    assert rows[0].order_id == "ord_1"
    assert rows[0].amount == Decimal("10.00")
    assert isinstance(rows[0].amount, Decimal)


def test_missing_column_fails_closed(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("order_id,amount\nord_1,10.00\n")  # no currency/date
    with pytest.raises(CsvSchemaError):
        parse_orders(bad)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reconcile.parse'`.

- [ ] **Step 4: Write minimal implementation**

`src/reconcile/parse.py`:
```python
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from .schema import PayoutLine, OrderLine

PAYOUT_COLUMNS = {"ref", "gross_amount", "fee", "net_amount", "currency", "date"}
ORDER_COLUMNS = {"order_id", "amount", "currency", "date"}


class CsvSchemaError(ValueError):
    """Raised when a CSV is missing required columns. Fail closed: no partial parse."""


def _require_columns(header: set[str], required: set[str], path: Path) -> None:
    missing = required - header
    if missing:
        raise CsvSchemaError(f"{path}: missing required columns {sorted(missing)}")


def _rows(path):
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = set(reader.fieldnames or [])
        yield header, path
        for row in reader:
            yield row, path


def parse_payouts(path) -> list[PayoutLine]:
    gen = _rows(path)
    header, p = next(gen)
    _require_columns(header, PAYOUT_COLUMNS, p)
    out = []
    for row, _ in gen:
        out.append(
            PayoutLine(
                ref=row["ref"].strip(),
                gross_amount=Decimal(row["gross_amount"]),
                fee=Decimal(row["fee"]),
                net_amount=Decimal(row["net_amount"]),
                currency=row["currency"].strip().upper(),
                line_date=date.fromisoformat(row["date"].strip()),
            )
        )
    return out


def parse_orders(path) -> list[OrderLine]:
    gen = _rows(path)
    header, p = next(gen)
    _require_columns(header, ORDER_COLUMNS, p)
    out = []
    for row, _ in gen:
        out.append(
            OrderLine(
                order_id=row["order_id"].strip(),
                amount=Decimal(row["amount"]),
                currency=row["currency"].strip().upper(),
                order_date=date.fromisoformat(row["date"].strip()),
            )
        )
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_parse.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add src/reconcile/parse.py tests/test_parse.py tests/fixtures/payout_basic.csv tests/fixtures/orders_basic.csv
git commit -m "feat: add fail-closed CSV parsing to canonical schema"
```

---

### Task 4: Deterministic matcher + report

**Files:**
- Create: `src/reconcile/matching.py`
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: `PayoutLine`, `OrderLine` from Task 2.
- Produces:
  - `@dataclass ReconcileReport` with fields `matched: list[tuple[OrderLine, PayoutLine]]`, `unmatched_orders: list[OrderLine]`, `unmatched_payouts: list[PayoutLine]`.
  - `deterministic_match(orders: list[OrderLine], payouts: list[PayoutLine]) -> ReconcileReport`.
- Match rule (exact): `order.order_id == payout.ref` **and** `order.amount == payout.gross_amount` **and** `order.currency == payout.currency`. Each payout line consumed at most once (idempotent).

- [ ] **Step 1: Write the failing test**

`tests/test_matching.py`:
```python
from decimal import Decimal
from datetime import date

from reconcile.schema import PayoutLine, OrderLine
from reconcile.matching import deterministic_match, ReconcileReport


def _order(oid, amt):
    return OrderLine(oid, Decimal(amt), "EUR", date(2026, 7, 1))


def _payout(ref, gross):
    g = Decimal(gross)
    return PayoutLine(ref, g, Decimal("0.50"), g - Decimal("0.50"), "EUR", date(2026, 7, 1))


def test_exact_matches_pair_up():
    orders = [_order("ord_1", "10.00"), _order("ord_2", "25.00")]
    payouts = [_payout("ord_1", "10.00"), _payout("ord_2", "25.00")]
    report = deterministic_match(orders, payouts)
    assert len(report.matched) == 2
    assert report.unmatched_orders == []
    assert report.unmatched_payouts == []


def test_amount_mismatch_is_not_matched():
    orders = [_order("ord_1", "10.00")]
    payouts = [_payout("ord_1", "9.00")]  # same ref, different amount
    report = deterministic_match(orders, payouts)
    assert report.matched == []
    assert report.unmatched_orders == orders
    assert report.unmatched_payouts == payouts


def test_residual_lines_are_reported_unmatched():
    orders = [_order("ord_1", "10.00"), _order("ord_missing", "12.00")]
    payouts = [_payout("ord_1", "10.00"), _payout("ord_ghost", "5.00")]
    report = deterministic_match(orders, payouts)
    assert len(report.matched) == 1
    assert [o.order_id for o in report.unmatched_orders] == ["ord_missing"]
    assert [p.ref for p in report.unmatched_payouts] == ["ord_ghost"]


def test_each_payout_consumed_at_most_once_idempotent():
    orders = [_order("ord_1", "10.00"), _order("ord_1", "10.00")]  # duplicate order id
    payouts = [_payout("ord_1", "10.00")]  # only one payout
    report = deterministic_match(orders, payouts)
    assert len(report.matched) == 1                      # not double-matched
    assert len(report.unmatched_orders) == 1
    # re-running yields identical counts (idempotent)
    again = deterministic_match(orders, payouts)
    assert (len(again.matched), len(again.unmatched_orders), len(again.unmatched_payouts)) == \
           (len(report.matched), len(report.unmatched_orders), len(report.unmatched_payouts))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reconcile.matching'`.

- [ ] **Step 3: Write minimal implementation**

`src/reconcile/matching.py`:
```python
from dataclasses import dataclass, field

from .schema import PayoutLine, OrderLine


@dataclass
class ReconcileReport:
    matched: list[tuple[OrderLine, PayoutLine]] = field(default_factory=list)
    unmatched_orders: list[OrderLine] = field(default_factory=list)
    unmatched_payouts: list[PayoutLine] = field(default_factory=list)


def _key(order_id: str, amount, currency: str) -> tuple:
    return (order_id, amount, currency)


def deterministic_match(orders: list[OrderLine], payouts: list[PayoutLine]) -> ReconcileReport:
    """Exact match on (id/ref, amount, currency). Each payout line consumed at most once."""
    # index payout lines by exact key, preserving order for deterministic consumption
    buckets: dict[tuple, list[PayoutLine]] = {}
    for p in payouts:
        buckets.setdefault(_key(p.ref, p.gross_amount, p.currency), []).append(p)

    report = ReconcileReport()
    consumed: set[int] = set()  # id() of payout objects already matched

    for o in orders:
        candidates = buckets.get(_key(o.order_id, o.amount, o.currency), [])
        match = next((p for p in candidates if id(p) not in consumed), None)
        if match is not None:
            consumed.add(id(match))
            report.matched.append((o, match))
        else:
            report.unmatched_orders.append(o)

    report.unmatched_payouts = [p for p in payouts if id(p) not in consumed]
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_matching.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/matching.py tests/test_matching.py
git commit -m "feat: add idempotent deterministic exact-match pass"
```

---

### Task 5: Reconcile entrypoint (parse + match)

**Files:**
- Create: `src/reconcile/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `parse_payouts`/`parse_orders` (Task 3), `deterministic_match`/`ReconcileReport` (Task 4).
- Produces: `reconcile_files(payout_csv, orders_csv) -> ReconcileReport`.

- [ ] **Step 1: Write the failing test**

`tests/test_core.py`:
```python
from reconcile.core import reconcile_files

PAYOUTS = "tests/fixtures/payout_basic.csv"
ORDERS = "tests/fixtures/orders_basic.csv"


def test_reconcile_files_end_to_end():
    report = reconcile_files(PAYOUTS, ORDERS)
    matched_ids = sorted(o.order_id for o, _ in report.matched)
    assert matched_ids == ["ord_1", "ord_2", "ord_3"]
    assert [o.order_id for o in report.unmatched_orders] == ["ord_missing"]
    assert [p.ref for p in report.unmatched_payouts] == ["ord_ghost"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reconcile.core'`.

- [ ] **Step 3: Write minimal implementation**

`src/reconcile/core.py`:
```python
from .parse import parse_payouts, parse_orders
from .matching import deterministic_match, ReconcileReport


def reconcile_files(payout_csv, orders_csv) -> ReconcileReport:
    payouts = parse_payouts(payout_csv)
    orders = parse_orders(orders_csv)
    return deterministic_match(orders, payouts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_core.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/reconcile/core.py tests/test_core.py
git commit -m "feat: add reconcile_files parse+match entrypoint"
```

---

### Task 6: Eval harness + labeled fixture + gating test

**Files:**
- Create: `tests/fixtures/labeled_matches.json`
- Create: `src/reconcile/evaluation.py`
- Test: `tests/test_eval.py`

**Interfaces:**
- Consumes: `ReconcileReport` (Task 4), `reconcile_files` (Task 5).
- Produces: `evaluate(report: ReconcileReport, truth: list[dict]) -> EvalMetrics` where `EvalMetrics(precision: float, recall: float, false_match_rate: float)` (frozen dataclass). `truth` entries are `{"order_id": str, "payout_ref": str}`.
- Metric definitions: proposed = set of `(order_id, payout.ref)` in `report.matched`; truth = set of `(order_id, payout_ref)`. `tp=|proposed∩truth|`, `fp=|proposed−truth|`, `fn=|truth−proposed|`. `precision = tp/(tp+fp)` (1.0 if no proposals), `recall = tp/(tp+fn)` (1.0 if no truth), `false_match_rate = fp/|proposed|` (0.0 if no proposals).

- [ ] **Step 1: Create the labeled truth fixture**

`tests/fixtures/labeled_matches.json` — ground-truth correct matches for the basic fixtures:
```json
[
  {"order_id": "ord_1", "payout_ref": "ord_1"},
  {"order_id": "ord_2", "payout_ref": "ord_2"},
  {"order_id": "ord_3", "payout_ref": "ord_3"}
]
```

- [ ] **Step 2: Write the failing test**

`tests/test_eval.py`:
```python
import json

from reconcile.core import reconcile_files
from reconcile.evaluation import evaluate, EvalMetrics

PAYOUTS = "tests/fixtures/payout_basic.csv"
ORDERS = "tests/fixtures/orders_basic.csv"
TRUTH = "tests/fixtures/labeled_matches.json"


def _truth():
    with open(TRUTH, encoding="utf-8") as fh:
        return json.load(fh)


def test_evaluate_computes_metrics():
    report = reconcile_files(PAYOUTS, ORDERS)
    m = evaluate(report, _truth())
    assert isinstance(m, EvalMetrics)
    # deterministic pass finds all 3 true matches, proposes nothing wrong
    assert m.precision == 1.0
    assert m.recall == 1.0
    assert m.false_match_rate == 0.0


def test_ci_gate_thresholds():
    """The gate later plans must never regress: no false matches, perfect precision."""
    report = reconcile_files(PAYOUTS, ORDERS)
    m = evaluate(report, _truth())
    assert m.false_match_rate == 0.0, "fail-closed: deterministic pass must never mis-match"
    assert m.precision == 1.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reconcile.evaluation'`.

- [ ] **Step 4: Write minimal implementation**

`src/reconcile/evaluation.py`:
```python
from dataclasses import dataclass

from .matching import ReconcileReport


@dataclass(frozen=True)
class EvalMetrics:
    precision: float
    recall: float
    false_match_rate: float


def evaluate(report: ReconcileReport, truth: list[dict]) -> EvalMetrics:
    proposed = {(o.order_id, p.ref) for o, p in report.matched}
    truth_set = {(t["order_id"], t["payout_ref"]) for t in truth}

    tp = len(proposed & truth_set)
    fp = len(proposed - truth_set)
    fn = len(truth_set - proposed)

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    false_match_rate = fp / len(proposed) if proposed else 0.0

    return EvalMetrics(precision=precision, recall=recall, false_match_rate=false_match_rate)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_eval.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/labeled_matches.json src/reconcile/evaluation.py tests/test_eval.py
git commit -m "feat: add eval harness (precision/recall/false-match-rate) + gating test"
```

---

### Task 7: GitHub Actions CI gate

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the full `pytest` suite (Tasks 2–6). The eval gate test (`tests/test_eval.py::test_ci_gate_thresholds`) is what makes CI a reconciliation-quality gate, not just a unit-test run.
- Produces: a required CI check that fails the build if any test — including the eval gate — fails.

- [ ] **Step 1: Create the workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -e ".[dev]"
      - name: Run tests (includes eval gate)
        run: pytest -v
```

- [ ] **Step 2: Verify the full suite passes locally (this is what CI will run)**

Run: `pytest -v`
Expected: PASS — all tests from Tasks 2–6 green (schema, parse, matching, core, eval).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run pytest + eval gate on push/PR to main"
```

- [ ] **Step 4: Push and confirm CI is green on GitHub**

```bash
git push
```
Expected: the **CI** check runs on GitHub Actions and passes. If the repo is on a branch, open a PR to `main` to see the gate on the PR. **This green CI badge is the Sprint-1 "eval test in CI" deliverable (StepUp exit criterion #3, first brick).**

---

## Self-Review

**Spec coverage (against `docs/design/2026-07-19-reconcile-design.md`):**
- §5 deterministic pass → Task 4. ✅ (Ingest/matcher/verifier **agents** are explicitly out of Plan 1 — later plans.)
- §6 data model: canonical `PayoutLine`/`OrderLine` → Task 2; full `job`/`decision`/`audit_event` persistence is **deferred** (needs the agent pipeline + web layer — Plan 3/4). Plan 1's report is in-memory. ✅ (scoped deferral, noted)
- §8 eval harness (precision/recall/false-match-rate, CI gate) → Tasks 6–7. ✅
- §10 fail-closed on parse failure ("no partial results") → Task 3 `CsvSchemaError`. ✅
- §13 tech stack (Python 3.12, pytest, GitHub Actions, src-layout) → Tasks 1, 7. ✅
- Idempotency (§6) → Task 4 test `test_each_payout_consumed_at_most_once_idempotent`. ✅

**Deferred-by-design (tracked for later plans, NOT gaps):** LLM ingest/matcher/verifier agents; human-review queue; SQLite persistence + audit log; observability traces/cost/latency; web UI + deploy; live Stripe API. These are Plans 2–5.

**Placeholder scan:** none — every step has concrete code/commands. ✅

**Type consistency:** `PayoutLine.ref` / `OrderLine.order_id` used consistently across parse, matching, core, evaluation; `ReconcileReport.matched` is `list[tuple[OrderLine, PayoutLine]]` everywhere; eval `truth` keys `order_id`/`payout_ref` match the fixture JSON. ✅
