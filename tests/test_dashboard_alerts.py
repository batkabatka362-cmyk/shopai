"""Dashboard adapter alerts — Option L.

Drives ``_collect_adapter_alerts`` and ``GET /api/alerts`` against a
fake registry so we can assert exact alert shapes without having to
boot the real adapter bootstrap chain.

Coverage:

* Critical category with zero configured adapters → red error alert.
* Critical category with at least one adapter online → no error alert
  for the category, warnings only for the offline members.
* Non-critical category never produces an error alert.
* One warning per offline adapter — configured adapters are silent.
* ``is_configured`` raising is treated as offline (we must surface
  half-initialised adapters, not hide them).
* Registry failure soft-fails into an error envelope rather than a 500.
* Endpoint honours the error envelope shape.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from dashboard.app import (
    DashboardAPIHandler,
    _collect_adapter_alerts,
)


def _handler() -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h._captured = []
    h._json = lambda status, data: h._captured.append((status, data))
    h.path = "/api/alerts"
    return h


class _FakeAdapter:
    """Tiny stand-in for a real adapter — only the fields the alerts
    collector touches."""

    def __init__(
        self,
        name: str,
        category: str = "llm",
        configured: bool = True,
        *,
        raises: bool = False,
    ) -> None:
        self.name = name
        # Use a SimpleNamespace so ``category.value`` works like the real
        # enum without importing it.
        self.category = SimpleNamespace(value=category)
        self._configured = configured
        self._raises = raises

    def is_configured(self) -> bool:
        if self._raises:
            raise RuntimeError("bootstrap incomplete")
        return self._configured


class _FakeRegistry:
    def __init__(self, adapters: list[_FakeAdapter]) -> None:
        self._adapters = {a.name: a for a in adapters}

    def names(self) -> list[str]:
        return list(self._adapters.keys())

    def get(self, name: str):
        return self._adapters.get(name)


@pytest.fixture
def patched_registry(monkeypatch):
    """Stub out ``get_registry`` so tests can inject an exact adapter set."""
    state: dict = {"adapters": []}

    def _install(adapters: list[_FakeAdapter]) -> None:
        state["adapters"] = adapters

    def _fake_get_registry():
        return _FakeRegistry(state["adapters"])

    monkeypatch.setattr("core.adapters.get_registry", _fake_get_registry)
    return _install


# ---------------------------------------------------------------------------
# Critical-category error alerts
# ---------------------------------------------------------------------------


class TestCriticalCategory:
    def test_all_llm_offline_is_error(self, patched_registry):
        patched_registry([
            _FakeAdapter("openai", "llm", configured=False),
            _FakeAdapter("anthropic", "llm", configured=False),
        ])
        data = _collect_adapter_alerts()
        errors = [a for a in data["alerts"] if a["level"] == "error"]
        assert len(errors) == 1
        assert errors[0]["category"] == "llm"
        assert "openai" in errors[0]["adapters"]
        assert "anthropic" in errors[0]["adapters"]
        assert data["counts"]["error"] == 1

    def test_one_configured_llm_clears_category_error(self, patched_registry):
        patched_registry([
            _FakeAdapter("openai", "llm", configured=True),
            _FakeAdapter("anthropic", "llm", configured=False),
        ])
        data = _collect_adapter_alerts()
        errors = [a for a in data["alerts"] if a["level"] == "error"]
        assert errors == []
        # But we still warn about the offline one.
        warnings = [a for a in data["alerts"] if a["level"] == "warning"]
        assert len(warnings) == 1
        assert warnings[0]["adapter"] == "anthropic"

    def test_non_critical_category_never_errors(self, patched_registry):
        patched_registry([
            _FakeAdapter("sendgrid", "email", configured=False),
            _FakeAdapter("postmark", "email", configured=False),
        ])
        data = _collect_adapter_alerts()
        errors = [a for a in data["alerts"] if a["level"] == "error"]
        assert errors == []
        # Just per-adapter warnings.
        assert data["counts"]["warning"] == 2


# ---------------------------------------------------------------------------
# Per-adapter warnings
# ---------------------------------------------------------------------------


class TestPerAdapterWarnings:
    def test_one_warning_per_offline_adapter(self, patched_registry):
        patched_registry([
            _FakeAdapter("stripe", "payment", configured=True),
            _FakeAdapter("paypal", "payment", configured=False),
            _FakeAdapter("square", "payment", configured=False),
        ])
        data = _collect_adapter_alerts()
        warnings = [a for a in data["alerts"] if a["level"] == "warning"]
        assert len(warnings) == 2
        names = {w["adapter"] for w in warnings}
        assert names == {"paypal", "square"}

    def test_configured_adapters_are_silent(self, patched_registry):
        patched_registry([
            _FakeAdapter("a", "search", configured=True),
            _FakeAdapter("b", "search", configured=True),
        ])
        data = _collect_adapter_alerts()
        assert data["alerts"] == []
        assert data["counts"]["total"] == 0

    def test_warning_carries_category_and_detail(self, patched_registry):
        patched_registry([_FakeAdapter("postmark", "email", configured=False)])
        data = _collect_adapter_alerts()
        w = data["alerts"][0]
        assert w["level"] == "warning"
        assert w["category"] == "email"
        assert w["adapter"] == "postmark"
        assert "environment" in w["detail"].lower()

    def test_error_listed_before_warning(self, patched_registry):
        patched_registry([
            _FakeAdapter("openai", "llm", configured=False),
            _FakeAdapter("postmark", "email", configured=False),
        ])
        alerts = _collect_adapter_alerts()["alerts"]
        assert alerts[0]["level"] == "error"
        assert alerts[-1]["level"] == "warning"


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


class TestResilience:
    def test_is_configured_raises_counts_as_offline(self, patched_registry):
        patched_registry([
            _FakeAdapter("broken", "llm", raises=True),
            _FakeAdapter("ok", "llm", configured=True),
        ])
        data = _collect_adapter_alerts()
        warnings = [a for a in data["alerts"] if a["level"] == "warning"]
        assert any(w["adapter"] == "broken" for w in warnings)

    def test_registry_failure_returns_soft_envelope(self, monkeypatch):
        def _boom():
            raise RuntimeError("registry exploded")
        monkeypatch.setattr("core.adapters.get_registry", _boom)
        data = _collect_adapter_alerts()
        assert data["alerts"] == []
        assert data["counts"]["total"] == 0
        assert "registry exploded" in data.get("error", "")

    def test_alerts_carry_timestamp(self, patched_registry):
        patched_registry([_FakeAdapter("x", "llm", configured=False)])
        data = _collect_adapter_alerts()
        assert isinstance(data["timestamp"], float)
        for alert in data["alerts"]:
            assert "timestamp" in alert


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class TestAlertsEndpoint:
    def test_returns_200(self, patched_registry):
        patched_registry([_FakeAdapter("openai", "llm", configured=True)])
        h = _handler()
        h._api_alerts()
        status, data = h._captured[-1]
        assert status == 200
        assert data["alerts"] == []
        assert data["counts"]["total"] == 0

    def test_returns_payload_with_counts(self, patched_registry):
        patched_registry([
            _FakeAdapter("a", "llm", configured=False),
            _FakeAdapter("b", "email", configured=False),
        ])
        h = _handler()
        h._api_alerts()
        _, data = h._captured[-1]
        # 1 error (llm category offline) + 2 warnings (each offline adapter).
        assert data["counts"]["error"] == 1
        assert data["counts"]["warning"] == 2
        assert data["counts"]["total"] == 3

    def test_registry_failure_does_not_500(self, monkeypatch):
        def _boom():
            raise RuntimeError("disaster")
        monkeypatch.setattr("core.adapters.get_registry", _boom)
        h = _handler()
        h._api_alerts()
        status, data = h._captured[-1]
        assert status == 200
        assert data["alerts"] == []
        assert "disaster" in data.get("error", "")
