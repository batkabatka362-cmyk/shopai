"""Dashboard cost tracker — Option M.

Exercises ``_collect_cost_snapshot`` + ``GET /api/cost``. We drive the
real ``AdapterMetricsCollector`` so the aggregation math matches what
the router actually writes.

Coverage:

* Empty state — no adapters called yet returns a well-formed zeroed
  envelope (so the UI renders $0.00 rather than NaN).
* Per-adapter rows are sorted by cost desc and carry category +
  per-call average.
* Category rollup sums correctly across adapters with the same
  category.
* Budget cap honours ``SHOPAI_MONTHLY_BUDGET_USD`` override and flags
  over-budget runs.
* Registered-but-never-called adapters surface as $0 rows — avoids
  "where did my adapter go?" confusion.
* Endpoint envelope + resilience on a metrics failure.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from dashboard.app import (
    DashboardAPIHandler,
    _collect_cost_snapshot,
)
from core.adapters.metrics import get_metrics, reset_metrics


def _handler() -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h._captured = []
    h._json = lambda status, data: h._captured.append((status, data))
    h.path = "/api/cost"
    return h


class _FakeAdapter:
    def __init__(self, name: str, category: str = "llm") -> None:
        self.name = name
        self.category = SimpleNamespace(value=category)


class _FakeRegistry:
    def __init__(self, adapters: list[_FakeAdapter]) -> None:
        self._adapters = {a.name: a for a in adapters}

    def names(self) -> list[str]:
        return list(self._adapters.keys())

    def get(self, name: str):
        return self._adapters.get(name)


@pytest.fixture
def fresh_metrics():
    """Wipe the module-level metrics collector between tests."""
    reset_metrics()
    yield get_metrics()
    reset_metrics()


@pytest.fixture
def patched_registry(monkeypatch):
    state: dict = {"adapters": []}

    def _install(adapters: list[_FakeAdapter]) -> None:
        state["adapters"] = adapters

    def _fake_get_registry():
        return _FakeRegistry(state["adapters"])

    monkeypatch.setattr("core.adapters.get_registry", _fake_get_registry)
    return _install


# ---------------------------------------------------------------------------
# Aggregation math
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_empty_snapshot_is_well_formed(
        self, fresh_metrics, patched_registry,
    ):
        patched_registry([])
        data = _collect_cost_snapshot()
        assert data["total_usd"] == 0
        assert data["per_adapter"] == []
        assert data["per_category"] == {}
        assert data["budget"]["spent_usd"] == 0
        assert data["budget"]["over_budget"] is False

    def test_single_adapter_spend(self, fresh_metrics, patched_registry):
        patched_registry([_FakeAdapter("openai", "llm")])
        fresh_metrics.record(
            "openai", success=True, latency_ms=100,
            cost_usd=0.25, tokens_in=100, tokens_out=50,
        )
        data = _collect_cost_snapshot()
        assert data["total_usd"] == 0.25
        row = data["per_adapter"][0]
        assert row["name"] == "openai"
        assert row["category"] == "llm"
        assert row["cost_usd"] == 0.25
        assert row["calls"] == 1
        assert row["avg_cost_usd"] == 0.25

    def test_per_adapter_sorted_by_cost_desc(
        self, fresh_metrics, patched_registry,
    ):
        patched_registry([
            _FakeAdapter("cheap", "llm"),
            _FakeAdapter("expensive", "llm"),
            _FakeAdapter("medium", "llm"),
        ])
        fresh_metrics.record("cheap", success=True, cost_usd=0.01)
        fresh_metrics.record("expensive", success=True, cost_usd=5.00)
        fresh_metrics.record("medium", success=True, cost_usd=0.50)
        data = _collect_cost_snapshot()
        names = [r["name"] for r in data["per_adapter"]]
        assert names[:3] == ["expensive", "medium", "cheap"]
        assert data["top_spender"] == "expensive"

    def test_category_rollup_sums_correctly(
        self, fresh_metrics, patched_registry,
    ):
        patched_registry([
            _FakeAdapter("openai", "llm"),
            _FakeAdapter("anthropic", "llm"),
            _FakeAdapter("stability", "image"),
        ])
        fresh_metrics.record("openai", success=True, cost_usd=1.00)
        fresh_metrics.record("anthropic", success=True, cost_usd=0.75)
        fresh_metrics.record("stability", success=True, cost_usd=0.20)
        data = _collect_cost_snapshot()
        assert data["per_category"]["llm"] == 1.75
        assert data["per_category"]["image"] == 0.20

    def test_avg_cost_uses_calls_total(self, fresh_metrics, patched_registry):
        patched_registry([_FakeAdapter("openai", "llm")])
        for _ in range(4):
            fresh_metrics.record("openai", success=True, cost_usd=0.25)
        data = _collect_cost_snapshot()
        row = data["per_adapter"][0]
        assert row["calls"] == 4
        assert row["avg_cost_usd"] == 0.25

    def test_registered_but_never_called_appears_as_zero(
        self, fresh_metrics, patched_registry,
    ):
        patched_registry([
            _FakeAdapter("openai", "llm"),
            _FakeAdapter("never_called", "search"),
        ])
        fresh_metrics.record("openai", success=True, cost_usd=1.00)
        data = _collect_cost_snapshot()
        names = [r["name"] for r in data["per_adapter"]]
        assert "never_called" in names
        never = next(r for r in data["per_adapter"] if r["name"] == "never_called")
        assert never["cost_usd"] == 0
        assert never["calls"] == 0

    def test_uncategorised_adapter_bucketed_as_other(
        self, fresh_metrics, patched_registry,
    ):
        # Adapter recorded in metrics but absent from registry ⇒ "other".
        patched_registry([])
        fresh_metrics.record("ghost", success=True, cost_usd=0.10)
        data = _collect_cost_snapshot()
        assert data["per_category"]["other"] == 0.10


# ---------------------------------------------------------------------------
# Budget cap
# ---------------------------------------------------------------------------


class TestBudget:
    def test_default_cap_is_100(
        self, fresh_metrics, patched_registry, monkeypatch,
    ):
        monkeypatch.delenv("SHOPAI_MONTHLY_BUDGET_USD", raising=False)
        patched_registry([])
        data = _collect_cost_snapshot()
        assert data["budget"]["cap_usd"] == 100

    def test_env_override(
        self, fresh_metrics, patched_registry, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_MONTHLY_BUDGET_USD", "50")
        patched_registry([_FakeAdapter("openai", "llm")])
        fresh_metrics.record("openai", success=True, cost_usd=25.00)
        data = _collect_cost_snapshot()
        assert data["budget"]["cap_usd"] == 50
        assert data["budget"]["pct_used"] == 50.0

    def test_over_budget_flag(
        self, fresh_metrics, patched_registry, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_MONTHLY_BUDGET_USD", "5")
        patched_registry([_FakeAdapter("openai", "llm")])
        fresh_metrics.record("openai", success=True, cost_usd=10.00)
        data = _collect_cost_snapshot()
        assert data["budget"]["over_budget"] is True
        assert data["budget"]["pct_used"] == 100.0  # clamped at 100

    def test_invalid_env_falls_back_to_default(
        self, fresh_metrics, patched_registry, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_MONTHLY_BUDGET_USD", "not-a-number")
        patched_registry([])
        data = _collect_cost_snapshot()
        assert data["budget"]["cap_usd"] == 100

    def test_zero_cap_does_not_divide_by_zero(
        self, fresh_metrics, patched_registry, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_MONTHLY_BUDGET_USD", "0")
        patched_registry([_FakeAdapter("openai", "llm")])
        fresh_metrics.record("openai", success=True, cost_usd=1.00)
        data = _collect_cost_snapshot()
        assert data["budget"]["cap_usd"] == 0
        assert data["budget"]["pct_used"] == 0


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class TestCostEndpoint:
    def test_returns_200(self, fresh_metrics, patched_registry):
        patched_registry([])
        h = _handler()
        h._api_cost()
        status, data = h._captured[-1]
        assert status == 200
        assert "total_usd" in data
        assert "budget" in data

    def test_envelope_on_metrics_failure(self, monkeypatch):
        def _boom():
            raise RuntimeError("metrics gone")
        monkeypatch.setattr(
            "core.adapters.metrics.get_metrics", _boom,
        )
        h = _handler()
        h._api_cost()
        status, data = h._captured[-1]
        # Soft envelope rather than 500 — the tab never blanks.
        assert status == 200
        assert data["total_usd"] == 0
        assert "error" in data

    def test_returns_top_spender(self, fresh_metrics, patched_registry):
        patched_registry([_FakeAdapter("openai", "llm")])
        fresh_metrics.record("openai", success=True, cost_usd=1.23)
        h = _handler()
        h._api_cost()
        _, data = h._captured[-1]
        assert data["top_spender"] == "openai"
