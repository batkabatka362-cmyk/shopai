"""Adapter SLA monitor — Option S.

Exercises the primitives in ``core.adapters.sla``:

* ``SLABudget`` — validation on construction
* ``SLAMonitor.evaluate`` — grading, min-samples gate, warn band
* ``SLAMonitor.evaluate_all`` — sort order (breach → warn → ok)
* ``SLAMonitor.totals`` — rollup counters
* ``budgets_from_dict`` — config loader
"""
from __future__ import annotations

import pytest

from core.adapters.sla import (
    DEFAULT_BUDGETS,
    SLABudget,
    SLAMonitor,
    SLAStatus,
    WARN_RATIO,
    budgets_from_dict,
)


# ---------------------------------------------------------------------------
# SLABudget
# ---------------------------------------------------------------------------


class TestSLABudget:
    def test_defaults_are_none(self):
        b = SLABudget()
        assert b.max_p95_ms is None
        assert b.max_p99_ms is None
        assert b.min_success_rate is None
        assert b.min_samples == 5

    def test_rejects_negative_p95(self):
        with pytest.raises(ValueError):
            SLABudget(max_p95_ms=-1.0)

    def test_rejects_out_of_range_success_rate(self):
        with pytest.raises(ValueError):
            SLABudget(min_success_rate=1.5)

    def test_rejects_negative_min_samples(self):
        with pytest.raises(ValueError):
            SLABudget(min_samples=-1)

    def test_to_dict_roundtrip(self):
        b = SLABudget(max_p95_ms=100, max_p99_ms=200, min_success_rate=0.9)
        d = b.to_dict()
        assert d["max_p95_ms"] == 100
        assert d["max_p99_ms"] == 200
        assert d["min_success_rate"] == 0.9


# ---------------------------------------------------------------------------
# SLAMonitor.evaluate
# ---------------------------------------------------------------------------


def _stats(calls=10, p50=100, p95=200, p99=300, sr=1.0):
    return {
        "calls_total": calls,
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "latency_p99_ms": p99,
        "success_rate": sr,
    }


class TestEvaluate:
    def test_no_budget_returns_unevaluated(self):
        mon = SLAMonitor(budgets={})
        out = mon.evaluate("anything", _stats())
        assert out.grade == "ok"
        assert out.evaluated is False
        assert out.violations == []

    def test_under_budget_is_ok(self):
        mon = SLAMonitor(budgets={
            "x": SLABudget(max_p95_ms=1000, min_samples=3),
        })
        out = mon.evaluate("x", _stats(calls=10, p95=100))
        assert out.grade == "ok"
        assert out.evaluated is True

    def test_near_budget_flags_warn(self):
        mon = SLAMonitor(budgets={
            "x": SLABudget(max_p95_ms=1000, min_samples=3),
        })
        # p95 = 850ms, budget = 1000ms, WARN_RATIO = 0.8 → 800ms warn floor
        out = mon.evaluate("x", _stats(calls=10, p95=850))
        assert out.grade == "warn"
        assert out.warnings
        assert not out.violations

    def test_over_budget_is_breach(self):
        mon = SLAMonitor(budgets={
            "x": SLABudget(max_p95_ms=1000, min_samples=3),
        })
        out = mon.evaluate("x", _stats(calls=10, p95=1500))
        assert out.grade == "breach"
        assert out.violations
        assert "p95" in out.violations[0]

    def test_min_samples_suppresses_evaluation(self):
        mon = SLAMonitor(budgets={
            "x": SLABudget(max_p95_ms=100, min_samples=20),
        })
        # Only 5 calls recorded — budget says wait until 20
        out = mon.evaluate("x", _stats(calls=5, p95=9999))
        assert out.evaluated is False
        assert out.grade == "ok"

    def test_success_rate_breach(self):
        mon = SLAMonitor(budgets={
            "x": SLABudget(min_success_rate=0.95, min_samples=3),
        })
        out = mon.evaluate("x", _stats(calls=10, sr=0.80))
        assert out.grade == "breach"
        assert any("success" in v for v in out.violations)

    def test_p99_breach_when_only_p99_budgeted(self):
        mon = SLAMonitor(budgets={
            "x": SLABudget(max_p99_ms=500, min_samples=3),
        })
        out = mon.evaluate("x", _stats(calls=10, p95=100, p99=800))
        assert out.grade == "breach"
        assert any("p99" in v for v in out.violations)

    def test_multiple_violations_listed(self):
        mon = SLAMonitor(budgets={
            "x": SLABudget(
                max_p95_ms=100, max_p99_ms=200,
                min_success_rate=0.99, min_samples=3,
            ),
        })
        out = mon.evaluate("x", _stats(calls=10, p95=500, p99=900, sr=0.5))
        assert out.grade == "breach"
        assert len(out.violations) == 3


# ---------------------------------------------------------------------------
# evaluate_all + totals
# ---------------------------------------------------------------------------


class TestEvaluateAll:
    def test_sort_order_breach_warn_ok(self):
        mon = SLAMonitor(budgets={
            "fast": SLABudget(max_p95_ms=1000, min_samples=3),
            "slow": SLABudget(max_p95_ms=1000, min_samples=3),
            "warm": SLABudget(max_p95_ms=1000, min_samples=3),
        })
        snap = {
            "fast": _stats(calls=10, p95=100),   # ok
            "slow": _stats(calls=10, p95=2000),  # breach
            "warm": _stats(calls=10, p95=900),   # warn
        }
        rows = mon.evaluate_all(snap)
        names = [r.adapter for r in rows]
        # breach first, then warn, then ok (alphabetical tiebreaker)
        assert names == ["slow", "warm", "fast"]

    def test_totals_counts_only_evaluated(self):
        mon = SLAMonitor(budgets={
            "a": SLABudget(max_p95_ms=100, min_samples=3),
            "b": SLABudget(max_p95_ms=100, min_samples=100),  # won't evaluate
        })
        snap = {
            "a": _stats(calls=10, p95=50),   # ok
            "b": _stats(calls=10, p95=50),   # min_samples blocks evaluation
        }
        rows = mon.evaluate_all(snap)
        totals = mon.totals(rows)
        assert totals["ok"] == 1
        assert totals["breach"] == 0
        assert totals["warn"] == 0


# ---------------------------------------------------------------------------
# Factory + catalog
# ---------------------------------------------------------------------------


class TestBudgetsFromDict:
    def test_parses_known_keys(self):
        raw = {
            "groq": {
                "max_p95_ms": 5000,
                "max_p99_ms": 10000,
                "min_success_rate": 0.97,
                "min_samples": 10,
            },
        }
        out = budgets_from_dict(raw)
        b = out["groq"]
        assert b.max_p95_ms == 5000
        assert b.max_p99_ms == 10000
        assert b.min_success_rate == 0.97
        assert b.min_samples == 10

    def test_ignores_unknown_keys(self):
        out = budgets_from_dict({"x": {"max_p95_ms": 100, "future": "ignored"}})
        assert out["x"].max_p95_ms == 100

    def test_empty_input(self):
        assert budgets_from_dict({}) == {}
        assert budgets_from_dict(None) == {}


class TestDefaultCatalog:
    def test_llm_budgets_present(self):
        assert "openai" in DEFAULT_BUDGETS
        assert DEFAULT_BUDGETS["openai"].max_p95_ms is not None

    def test_no_negative_budgets(self):
        for name, b in DEFAULT_BUDGETS.items():
            if b.max_p95_ms is not None:
                assert b.max_p95_ms > 0, name
            if b.max_p99_ms is not None:
                assert b.max_p99_ms > 0, name
