"""Tests for ``api.dashboard_ui`` -- silent-fail fix on the
``_get_data()`` probes.

Before: both the memory + data probes silently swallowed
exceptions, so a dashboard rendering with empty memory /
rules / data sections was indistinguishable from a healthy
first-run with no data yet.

After: each probe logs at debug with the exception. Return
contract preserved (the result dict still has whatever keys
the successful path populated; missing keys carry the same
""section not yet populated"" semantics they always did).
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

# Import the module at top so utils.logger has configured the
# named logger before fixtures attach (the level-reset issue
# documented in #475's test fixture).
from api import dashboard_ui as _dashboard_ui_mod  # noqa: F401


_LOGGER = "shopai.dashboard.ui"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def dash_log() -> _ListHandler:
    handler = _ListHandler()
    target = logging.getLogger(_LOGGER)
    original = target.level
    target.setLevel(logging.DEBUG)
    target.addHandler(handler)
    try:
        yield handler
    finally:
        target.removeHandler(handler)
        target.setLevel(original)


def _messages(handler: _ListHandler) -> list[str]:
    return [r.getMessage() for r in handler.records]


class TestMemoryProbeLogging:

    def test_memory_failure_logs_debug(self, dash_log):
        from api.dashboard_ui import DashboardUI
        with patch(
            "core.memory.intelligence.get_memory_intelligence",
            side_effect=RuntimeError("mi broken"),
        ):
            result = DashboardUI._get_data()
        # Behavior contract: result still has the other keys
        assert "phases" in result
        assert "memory" not in result  # probe failed -> key absent
        # Log fired at debug
        msgs = _messages(dash_log)
        assert any(
            "dashboard memory probe failed" in m
            and "mi broken" in m
            for m in msgs
        )

    def test_memory_success_no_log(self, dash_log):
        from api.dashboard_ui import DashboardUI
        # Stub the memory intelligence singleton
        mi = type("MI", (), {
            "get_stats": lambda self: {"total": 5},
            "get_rules": lambda self: [
                {"category": "p", "action": "a", "use_count": 3},
            ],
            "get_strategies": lambda self: [
                {"category": "s"},
            ],
        })()
        with patch(
            "core.memory.intelligence.get_memory_intelligence",
            return_value=mi,
        ), patch(
            "core.data.architecture.get_data_architecture",
            side_effect=RuntimeError("not under test"),
        ), patch(
            "core.system.alerts.get_alert_system",
            side_effect=RuntimeError("not under test"),
        ):
            result = DashboardUI._get_data()
        assert result["memory"] == {"total": 5}
        assert len(result["rules"]) == 1
        # No warnings (data + alerts will fire debug but those
        # are separate probes, not regressions of the memory
        # probe path under test)


class TestDataProbeLogging:

    def test_data_failure_logs_debug(self, dash_log):
        from api.dashboard_ui import DashboardUI
        with patch(
            "core.data.architecture.get_data_architecture",
            side_effect=RuntimeError("da broken"),
        ):
            result = DashboardUI._get_data()
        assert "data" not in result
        msgs = _messages(dash_log)
        assert any(
            "dashboard data probe failed" in m
            and "da broken" in m
            for m in msgs
        )

    def test_data_success_no_data_warning(self, dash_log):
        from api.dashboard_ui import DashboardUI
        da = type("DA", (), {
            "get_stats": lambda self: {
                "total_records": 42,
                "domains": {"a": 1, "b": 2},
                "result_rate": 0.95,
            },
        })()
        with patch(
            "core.data.architecture.get_data_architecture",
            return_value=da,
        ), patch(
            "core.memory.intelligence.get_memory_intelligence",
            side_effect=RuntimeError("not under test"),
        ), patch(
            "core.system.alerts.get_alert_system",
            side_effect=RuntimeError("not under test"),
        ):
            result = DashboardUI._get_data()
        assert result["data"]["total_records"] == 42
        assert result["data"]["domains"] == 2
        # The DATA probe didn't log a failure
        msgs = _messages(dash_log)
        assert not any(
            "dashboard data probe failed" in m
            for m in msgs
        )


class TestReturnContractPreserved:

    def test_phases_and_health_always_present(self, dash_log):
        """Even when every probe fails, the result dict still
        carries the always-present keys (phases, health,
        alerts=[])."""
        from api.dashboard_ui import DashboardUI
        with patch(
            "core.memory.intelligence.get_memory_intelligence",
            side_effect=RuntimeError("x"),
        ), patch(
            "core.data.architecture.get_data_architecture",
            side_effect=RuntimeError("y"),
        ), patch(
            "core.system.alerts.get_alert_system",
            side_effect=RuntimeError("z"),
        ):
            result = DashboardUI._get_data()
        assert result["phases"] == 32
        assert result["alerts"] == []
        assert "health" in result
