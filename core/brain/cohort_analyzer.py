"""Cohort analyzer — retention rates by signup month / source / ad.

LTV (v14-D4) estimates a single customer's lifetime value. Cohort
analysis aggregates: "customers who signed up in March retained
at 62% in month 1, 41% in month 3; those from organic retained
better than those from Meta ads." Without cohorts the owner
can't compare acquisition channels and time-in-business trends.

CohortAnalyzer takes a stream of customer records and emits a
retention grid:

  cohort_key × month_offset → fraction_retained

Cohort keys default to "YYYY-MM" of the first purchase ts but
can be overridden (e.g. first acquisition source). Retention is
defined as: customer placed ≥1 order in month N after first order.

APIs:

  build(records, max_months=12, cohort_key=None)
      → RetentionGrid
  compare(grid, cohort_a, cohort_b, at_month)
      → delta in retention
  best_and_worst(grid, at_month) → top and bottom cohorts

No numpy. Deterministic. Zero LLM. Designed to run against v14
session tracker + LTV records.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class OrderRecord:
    customer_id: str
    order_ts: float
    cohort_hint: str = ""       # source / channel / niche — optional

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "order_ts": self.order_ts,
            "cohort_hint": self.cohort_hint,
        }


@dataclass
class RetentionGrid:
    cohorts: list[str] = field(default_factory=list)
    max_months: int = 12
    # rows[cohort][month_offset] = (retained, cohort_size)
    rows: dict[str, dict[int, tuple[int, int]]] = field(
        default_factory=dict,
    )

    def retention(self, cohort: str, month: int) -> float:
        if cohort not in self.rows:
            return 0.0
        retained, size = self.rows[cohort].get(month, (0, 0))
        if size <= 0:
            return 0.0
        return retained / size

    def cohort_size(self, cohort: str) -> int:
        row = self.rows.get(cohort)
        if not row:
            return 0
        # size is constant across columns — take the first non-zero
        for _, (_, size) in row.items():
            if size > 0:
                return size
        return 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cohorts": self.cohorts,
            "max_months": self.max_months,
            "rows": {
                c: {
                    str(m): {
                        "retained": r,
                        "cohort_size": s,
                        "retention": (
                            round(r / s, 3) if s > 0 else 0.0
                        ),
                    }
                    for m, (r, s) in rows.items()
                }
                for c, rows in self.rows.items()
            },
        }


# ── Build ───────────────────────────────────────────────────

def _month_key(ts: float) -> str:
    d = dt.datetime.utcfromtimestamp(ts)
    return f"{d.year:04d}-{d.month:02d}"


def _months_between(first_ts: float, later_ts: float) -> int:
    """Integer month offset (0 = same month, 1 = next month, ...)."""
    d1 = dt.datetime.utcfromtimestamp(first_ts)
    d2 = dt.datetime.utcfromtimestamp(later_ts)
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def build(
    records: Iterable[OrderRecord | dict[str, Any]],
    *,
    max_months: int = 12,
    cohort_key: Callable[[OrderRecord], str] | None = None,
) -> RetentionGrid:
    coerced: list[OrderRecord] = []
    for r in records:
        if isinstance(r, OrderRecord):
            coerced.append(r)
        else:
            coerced.append(OrderRecord(
                customer_id=str(r.get("customer_id", "")),
                order_ts=float(r.get("order_ts", 0)),
                cohort_hint=str(r.get("cohort_hint", "")),
            ))
    coerced = [r for r in coerced if r.customer_id and r.order_ts > 0]
    coerced.sort(key=lambda r: r.order_ts)

    # Group orders by customer
    by_customer: dict[str, list[OrderRecord]] = defaultdict(list)
    for r in coerced:
        by_customer[r.customer_id].append(r)

    # Cohort assignment via first order
    cohort_of: dict[str, str] = {}
    first_ts: dict[str, float] = {}
    for cid, orders in by_customer.items():
        first = orders[0]
        first_ts[cid] = first.order_ts
        if cohort_key:
            try:
                cohort_of[cid] = str(cohort_key(first))
            except Exception:
                cohort_of[cid] = _month_key(first.order_ts)
        else:
            cohort_of[cid] = _month_key(first.order_ts)

    # Cohort sizes
    sizes: dict[str, int] = defaultdict(int)
    for cid, cohort in cohort_of.items():
        sizes[cohort] += 1

    # Per-cohort per-month retained customers
    retained: dict[str, dict[int, set[str]]] = defaultdict(
        lambda: defaultdict(set),
    )
    for cid, orders in by_customer.items():
        cohort = cohort_of[cid]
        first = first_ts[cid]
        for order in orders:
            m = _months_between(first, order.order_ts)
            if 0 <= m <= max_months:
                retained[cohort][m].add(cid)

    # Build grid
    rows: dict[str, dict[int, tuple[int, int]]] = {}
    for cohort, size in sizes.items():
        rows[cohort] = {}
        for m in range(max_months + 1):
            rows[cohort][m] = (
                len(retained[cohort].get(m, set())),
                size,
            )

    return RetentionGrid(
        cohorts=sorted(sizes.keys()),
        max_months=max_months,
        rows=rows,
    )


# ── Comparison helpers ──────────────────────────────────────

def compare(
    grid: RetentionGrid, cohort_a: str, cohort_b: str,
    at_month: int,
) -> float:
    return grid.retention(cohort_a, at_month) - grid.retention(cohort_b, at_month)


def best_and_worst(
    grid: RetentionGrid, at_month: int, min_cohort_size: int = 5,
) -> tuple[tuple[str, float] | None, tuple[str, float] | None]:
    entries = [
        (c, grid.retention(c, at_month))
        for c in grid.cohorts
        if grid.cohort_size(c) >= min_cohort_size
    ]
    if not entries:
        return None, None
    entries.sort(key=lambda kv: kv[1])
    return entries[-1], entries[0]


# ── Averaging ────────────────────────────────────────────────

def average_curve(
    grid: RetentionGrid, min_cohort_size: int = 5,
) -> list[tuple[int, float]]:
    """Mean retention at each month, weighted by cohort size."""
    out: list[tuple[int, float]] = []
    for m in range(grid.max_months + 1):
        total = 0
        retained = 0
        for c in grid.cohorts:
            size = grid.cohort_size(c)
            if size < min_cohort_size:
                continue
            r, _ = grid.rows[c].get(m, (0, 0))
            total += size
            retained += r
        fraction = retained / total if total > 0 else 0.0
        out.append((m, fraction))
    return out
