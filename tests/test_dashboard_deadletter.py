"""Dashboard dead-letter endpoint — Option Y phase 3.

Tests the ``_collect_deadletter_snapshot`` rollup and the
``/api/deadletter`` handler wiring.
"""
from __future__ import annotations

import pytest

from core.adapters.deadletter import (
    DeadLetterLedger,
    reset_dead_letter_ledger,
)
import core.adapters.deadletter as _dl_mod
from dashboard import app as dash
from dashboard.app import (
    DashboardAPIHandler,
    _collect_deadletter_snapshot,
)


def _handler() -> DashboardAPIHandler:
    return object.__new__(DashboardAPIHandler)


def _install_ledger(monkeypatch, ledger):
    """Swap the process-wide singleton to a known in-memory ledger."""
    monkeypatch.setattr(_dl_mod, "_default_ledger", ledger)


@pytest.fixture(autouse=True)
def _reset():
    reset_dead_letter_ledger()
    yield
    reset_dead_letter_ledger()


class TestCollectDeadletterSnapshot:
    def test_empty_ledger_empty_feed(self, monkeypatch):
        _install_ledger(monkeypatch, DeadLetterLedger(path=None))
        snap = _collect_deadletter_snapshot()
        assert snap["size"] == 0
        assert snap["recent"] == []
        assert snap["per_adapter"] == {}

    def test_populated_ledger_rolls_up(self, monkeypatch):
        lg = DeadLetterLedger(path=None)
        lg.record(
            adapter="openai", capability="chat_complete",
            params_hash="h1", error_type="Timeout",
            error_message="boom", attempts=3,
        )
        lg.record(
            adapter="openai", capability="chat_complete",
            params_hash="h2", error_type="Timeout",
            error_message="boom", attempts=3,
        )
        lg.record(
            adapter="anthropic", capability="chat_complete",
            params_hash="h3", error_type="Auth",
            error_message="bad key", attempts=1,
        )
        _install_ledger(monkeypatch, lg)
        snap = _collect_deadletter_snapshot()
        assert snap["size"] == 3
        assert snap["total_records"] == 3
        assert snap["per_adapter"] == {"openai": 2, "anthropic": 1}
        assert snap["per_capability"] == {"chat_complete": 3}
        # Recent feed is newest-first and dict-shaped.
        assert len(snap["recent"]) == 3
        assert snap["recent"][0]["adapter"] == "anthropic"
        assert "id" in snap["recent"][0]

    def test_snapshot_exposes_write_failures(self, monkeypatch):
        lg = DeadLetterLedger(path=None)
        _install_ledger(monkeypatch, lg)
        snap = _collect_deadletter_snapshot()
        assert snap["write_failures"] == 0


class TestDeadletterEndpoint:
    def test_api_deadletter_wraps_snapshot(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)
        monkeypatch.setattr(
            dash, "_collect_deadletter_snapshot",
            lambda: {
                "timestamp": 1.0,
                "size": 2,
                "total_records": 2,
                "per_adapter": {"openai": 2},
                "per_capability": {"chat_complete": 2},
                "recent": [{"id": "dl-1", "adapter": "openai"}],
            },
        )
        h._api_deadletter()
        assert captured["status"] == 200
        assert captured["payload"]["size"] == 2
        assert captured["payload"]["recent"][0]["adapter"] == "openai"

    def test_api_deadletter_handles_collector_failure(self, monkeypatch):
        h = _handler()
        captured: dict = {}

        def _json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        monkeypatch.setattr(h, "_json", _json)

        def _boom():
            raise RuntimeError("ledger gone")

        monkeypatch.setattr(dash, "_collect_deadletter_snapshot", _boom)
        h._api_deadletter()
        assert captured["status"] == 200
        assert captured["payload"]["size"] == 0
        assert captured["payload"]["recent"] == []
        assert "error" in captured["payload"]
