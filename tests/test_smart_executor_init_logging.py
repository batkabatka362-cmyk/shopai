"""Tests for ``execution.smart_executor`` -- init-fallback
logging fix.

Before: 4 of the 5 ``_ensure_init`` import-fallback try/except
blocks were ``except Exception: pass`` -- silent failure. The
5th (promotion_tracker) was already logging at debug. This
inconsistency meant operators saw exactly ONE init-failure
signal (promotion_tracker) but never the other 4
(memory_intel, data_arch, learning_loop, ab_testing).

After: all 5 init-fallback paths log at debug with a hint
about what capability is degraded. Behavior contract preserved
-- the executor still runs without these dependencies (in
""dumb mode""), but operators now have a diagnostic signal.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

# Import the module at top of file so its module-level
# ``utils.logger.get_logger("smart_executor")`` call has
# already configured the logger before our fixture attaches.
# If we let the executor import lazily inside each test, the
# get_logger call would reset the level to WARNING AFTER our
# fixture set it to DEBUG, and the debug records would be
# silently dropped.
from execution import smart_executor as _smart_executor_module  # noqa: F401


_LOGGER = "shopai.smart_executor"


class _ListHandler(logging.Handler):
    """utils.logger pins propagate=False on shopai.* loggers
    so caplog doesn't see them. Attach a list handler directly."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def exec_log() -> _ListHandler:
    handler = _ListHandler()
    target = logging.getLogger(_LOGGER)
    original_level = target.level
    target.setLevel(logging.DEBUG)
    target.addHandler(handler)
    try:
        yield handler
    finally:
        target.removeHandler(handler)
        target.setLevel(original_level)


def _messages(handler: _ListHandler) -> list[str]:
    return [r.getMessage() for r in handler.records]


class TestEnsureInitLogging:
    """Each of the 5 dependency imports must log at debug when
    it fails. The executor itself keeps running (behavior
    contract)."""

    def test_memory_intelligence_failure_logs(
        self, exec_log,
    ):
        from execution.smart_executor import SmartExecutor
        with patch(
            "core.memory.intelligence.get_memory_intelligence",
            side_effect=RuntimeError("mi broken"),
        ):
            executor = SmartExecutor()
            executor._ensure_init()
        msgs = _messages(exec_log)
        assert any(
            "memory_intelligence init failed" in m
            and "mi broken" in m
            for m in msgs
        )
        # And the executor's state reflects the missing dep
        assert executor._memory_intel is None

    def test_data_architecture_failure_logs(self, exec_log):
        from execution.smart_executor import SmartExecutor
        with patch(
            "core.data.architecture.get_data_architecture",
            side_effect=RuntimeError("da broken"),
        ):
            executor = SmartExecutor()
            executor._ensure_init()
        msgs = _messages(exec_log)
        assert any(
            "data_architecture init failed" in m
            and "da broken" in m
            for m in msgs
        )
        assert executor._data_arch is None

    def test_learning_loop_failure_logs(self, exec_log):
        from execution.smart_executor import SmartExecutor
        with patch(
            "core.brain.learning_loop.LearningLoop",
            side_effect=RuntimeError("ll broken"),
        ):
            executor = SmartExecutor()
            executor._ensure_init()
        msgs = _messages(exec_log)
        assert any(
            "learning_loop init failed" in m
            and "ll broken" in m
            for m in msgs
        )
        assert executor._learning_loop is None

    def test_ab_testing_failure_logs(self, exec_log):
        from execution.smart_executor import SmartExecutor
        with patch(
            "core.system.ab_testing.get_ab_testing",
            side_effect=RuntimeError("ab broken"),
        ):
            executor = SmartExecutor()
            executor._ensure_init()
        msgs = _messages(exec_log)
        assert any(
            "ab_testing init failed" in m
            and "ab broken" in m
            for m in msgs
        )
        assert executor._ab_testing is None

    def test_promotion_tracker_failure_logs(self, exec_log):
        """The 5th path was already logging in the original code;
        this guards the regression."""
        from execution.smart_executor import SmartExecutor
        with patch(
            "execution.promotion_tracker.get_promotion_tracker",
            side_effect=RuntimeError("pt broken"),
        ):
            executor = SmartExecutor()
            executor._ensure_init()
        msgs = _messages(exec_log)
        assert any(
            "promotion_tracker init failed" in m
            and "pt broken" in m
            for m in msgs
        )
        assert executor._promotion_tracker is None

    def test_happy_path_no_warnings(self, exec_log):
        """When all imports succeed, no warning-level logs fire.
        Debug-level may fire if the underlying singletons log,
        but no warnings."""
        from execution.smart_executor import SmartExecutor
        executor = SmartExecutor()
        executor._ensure_init()
        warnings = [
            r for r in exec_log.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []
