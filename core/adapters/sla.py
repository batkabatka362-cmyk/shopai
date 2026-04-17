"""Adapter latency / success SLA monitor — Option S.

The metrics collector already records p50/p95/p99 latency and
success-rate per adapter. What was missing is a declarative budget
that says "this adapter should respond in under X ms at p95" and
a monitor that flags violations.

This module supplies two small primitives:

* ``SLABudget`` — per-adapter thresholds: max p95 latency, max p99
  latency, minimum success rate, minimum sample count before the
  budget counts (avoids flapping on the first slow call).
* ``SLAMonitor`` — runs a snapshot of the metrics collector against
  a dict of budgets, returns a list of ``SLAStatus`` rows the UI
  can render directly. Fail-soft: a missing adapter / empty sample
  window returns ``grade="ok"`` with ``evaluated=False`` so the
  dashboard never shows false alarms.

The default budget catalog is deliberately conservative — the
operator can override per-adapter values via constructor or a
``budgets_from_dict`` factory when they're read from config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Budget ─────────────────────────────────────────────────────


@dataclass
class SLABudget:
    """Latency + success-rate thresholds for one adapter.

    Every field is optional — leave a threshold at ``None`` to
    skip that check. ``min_samples`` suppresses evaluation until
    enough data has accumulated so the monitor doesn't scream
    after the first slow call in a fresh process.
    """

    max_p95_ms: float | None = None
    max_p99_ms: float | None = None
    min_success_rate: float | None = None  # 0.0-1.0
    min_samples: int = 5

    def __post_init__(self) -> None:
        if self.max_p95_ms is not None and self.max_p95_ms < 0:
            raise ValueError("max_p95_ms must be >= 0")
        if self.max_p99_ms is not None and self.max_p99_ms < 0:
            raise ValueError("max_p99_ms must be >= 0")
        if self.min_success_rate is not None and not 0.0 <= self.min_success_rate <= 1.0:
            raise ValueError("min_success_rate must be in [0, 1]")
        if self.min_samples < 0:
            raise ValueError("min_samples must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_p95_ms": self.max_p95_ms,
            "max_p99_ms": self.max_p99_ms,
            "min_success_rate": self.min_success_rate,
            "min_samples": self.min_samples,
        }


# ── Evaluation result ──────────────────────────────────────────


@dataclass
class SLAStatus:
    """Per-adapter evaluation result.

    ``grade`` is one of:
      * ``"ok"``     — every configured threshold met (or skipped)
      * ``"warn"``   — within 20% of a threshold (early warning)
      * ``"breach"`` — at least one threshold exceeded

    ``violations`` lists the specific thresholds that tripped so
    the UI can highlight exactly what's slow without re-computing.
    """

    adapter: str
    grade: str
    evaluated: bool
    samples: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    success_rate: float
    budget: SLABudget | None
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "grade": self.grade,
            "evaluated": self.evaluated,
            "samples": self.samples,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "success_rate": self.success_rate,
            "budget": self.budget.to_dict() if self.budget else None,
            "violations": list(self.violations),
            "warnings": list(self.warnings),
        }


# ── Default budgets ────────────────────────────────────────────


#: Conservative default budgets for well-known adapter categories.
#: Operators override per-adapter via ``SLAMonitor(budgets=...)``.
DEFAULT_BUDGETS: dict[str, SLABudget] = {
    # LLM vendors — streaming latency matters, end-to-end matters more.
    "openai": SLABudget(max_p95_ms=15000, max_p99_ms=30000, min_success_rate=0.95),
    "anthropic": SLABudget(max_p95_ms=15000, max_p99_ms=30000, min_success_rate=0.95),
    "groq": SLABudget(max_p95_ms=5000, max_p99_ms=10000, min_success_rate=0.95),
    "gemini": SLABudget(max_p95_ms=10000, max_p99_ms=20000, min_success_rate=0.90),
    "ollama": SLABudget(max_p95_ms=20000, max_p99_ms=40000, min_success_rate=0.90),
    # Shopify + ads — REST calls, much tighter budget.
    "shopify_products": SLABudget(max_p95_ms=2000, max_p99_ms=5000, min_success_rate=0.98),
    "shopify_orders": SLABudget(max_p95_ms=2000, max_p99_ms=5000, min_success_rate=0.98),
    # Email / messaging — should be instant, allow for occasional retries.
    "postmark": SLABudget(max_p95_ms=3000, max_p99_ms=6000, min_success_rate=0.97),
    "sendgrid": SLABudget(max_p95_ms=3000, max_p99_ms=6000, min_success_rate=0.97),
}


def budgets_from_dict(raw: dict[str, dict[str, Any]]) -> dict[str, SLABudget]:
    """Build a budget map from a plain dict (e.g. config.yaml).

    Unknown keys on the inner dict are ignored so the config file
    can grow new knobs without breaking older code paths.
    """
    out: dict[str, SLABudget] = {}
    for name, row in (raw or {}).items():
        out[name] = SLABudget(
            max_p95_ms=row.get("max_p95_ms"),
            max_p99_ms=row.get("max_p99_ms"),
            min_success_rate=row.get("min_success_rate"),
            min_samples=int(row.get("min_samples", 5)),
        )
    return out


# ── Monitor ────────────────────────────────────────────────────


#: Ratio at which "close to the budget" flips from ``ok`` → ``warn``.
#: 0.8 means "within 80% of the threshold". Kept as a module constant
#: so tests can override and dashboards can document the boundary.
WARN_RATIO = 0.8


class SLAMonitor:
    """Evaluate a metrics snapshot against a per-adapter budget map."""

    def __init__(
        self,
        budgets: dict[str, SLABudget] | None = None,
    ) -> None:
        self._budgets: dict[str, SLABudget] = dict(
            budgets if budgets is not None else DEFAULT_BUDGETS
        )

    # ── Budget management ────────────────────────────────

    def get_budget(self, adapter: str) -> SLABudget | None:
        return self._budgets.get(adapter)

    def set_budget(self, adapter: str, budget: SLABudget) -> None:
        self._budgets[adapter] = budget

    def budgets(self) -> dict[str, SLABudget]:
        return dict(self._budgets)

    # ── Evaluation ───────────────────────────────────────

    def evaluate(self, adapter: str, stats: dict[str, Any]) -> SLAStatus:
        """Grade one adapter against its budget.

        ``stats`` is the dict returned by
        ``AdapterMetricsCollector.stats_for`` / ``snapshot``.
        """
        budget = self._budgets.get(adapter)
        samples = int(stats.get("calls_total", 0))
        p50 = float(stats.get("latency_p50_ms", 0.0))
        p95 = float(stats.get("latency_p95_ms", 0.0))
        p99 = float(stats.get("latency_p99_ms", 0.0))
        sr = float(stats.get("success_rate", 1.0))

        if budget is None or samples < budget.min_samples:
            return SLAStatus(
                adapter=adapter,
                grade="ok",
                evaluated=False,
                samples=samples,
                p50_ms=p50,
                p95_ms=p95,
                p99_ms=p99,
                success_rate=sr,
                budget=budget,
            )

        violations: list[str] = []
        warnings: list[str] = []

        if budget.max_p95_ms is not None:
            if p95 > budget.max_p95_ms:
                violations.append(
                    f"p95 {p95:.0f}ms > budget {budget.max_p95_ms:.0f}ms",
                )
            elif p95 > budget.max_p95_ms * WARN_RATIO:
                warnings.append(
                    f"p95 {p95:.0f}ms near budget {budget.max_p95_ms:.0f}ms",
                )

        if budget.max_p99_ms is not None:
            if p99 > budget.max_p99_ms:
                violations.append(
                    f"p99 {p99:.0f}ms > budget {budget.max_p99_ms:.0f}ms",
                )
            elif p99 > budget.max_p99_ms * WARN_RATIO:
                warnings.append(
                    f"p99 {p99:.0f}ms near budget {budget.max_p99_ms:.0f}ms",
                )

        if budget.min_success_rate is not None:
            if sr < budget.min_success_rate:
                violations.append(
                    f"success {sr:.2%} < budget {budget.min_success_rate:.2%}",
                )
            elif sr < budget.min_success_rate + (1.0 - budget.min_success_rate) * (1.0 - WARN_RATIO):
                # e.g. budget 0.95 → warn zone [0.95, 0.96)
                # small band — only warn if we're genuinely close
                warnings.append(
                    f"success {sr:.2%} near budget {budget.min_success_rate:.2%}",
                )

        grade = "breach" if violations else ("warn" if warnings else "ok")
        return SLAStatus(
            adapter=adapter,
            grade=grade,
            evaluated=True,
            samples=samples,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            success_rate=sr,
            budget=budget,
            violations=violations,
            warnings=warnings,
        )

    def evaluate_all(
        self,
        snapshot: dict[str, dict[str, Any]],
    ) -> list[SLAStatus]:
        """Grade every adapter in a metrics snapshot.

        The output is sorted so breaches lead, then warnings, then
        OKs — the UI can slice off the top-N for an at-a-glance
        "what's on fire" view.
        """
        rows = [self.evaluate(name, stats) for name, stats in snapshot.items()]
        grade_rank = {"breach": 0, "warn": 1, "ok": 2}
        rows.sort(key=lambda r: (grade_rank.get(r.grade, 3), r.adapter))
        return rows

    def totals(self, rows: list[SLAStatus]) -> dict[str, int]:
        """Return ``{"breach": n, "warn": n, "ok": n}`` — a tiny
        rollup the dashboard header can show next to the tab name.
        """
        out = {"breach": 0, "warn": 0, "ok": 0}
        for r in rows:
            if not r.evaluated:
                continue
            out[r.grade] = out.get(r.grade, 0) + 1
        return out
