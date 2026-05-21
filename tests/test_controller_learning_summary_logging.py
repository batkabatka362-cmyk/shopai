"""Tests for ``core.autonomous.controller`` -- silent-failure
fixes on ``_update_weights_from_rules`` + ``get_learning_summary``.

These are static (one classmethod, one instance method) so the
tests don't need a full AutonomousController setup -- they
exercise the methods directly.

Before:
- ``_update_weights_from_rules`` returned 0 on any exception
  with no log. ""0 updates"" was indistinguishable from ""MI
  call broken"".
- ``get_learning_summary``'s weights subsection silently
  dropped to {} on weight_manager import failure. Same
  ambiguity.

After: both paths log + behavior contract preserved (still
return 0 / {}).
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from core.autonomous import controller as _controller_module  # noqa: F401


_LOGGER = "shopai.autonomous"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def ctrl_log() -> _ListHandler:
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


class TestUpdateWeightsFromRulesLogging:
    """The static fallback that walks MemoryIntelligence rules
    and counts the ones with success_count>0."""

    def _call(self):
        # Re-resolve through the controller module so any patch
        # at the outer module path takes effect.
        from core.autonomous.controller import LearningPipeline
        return LearningPipeline._update_weights_from_rules()

    def test_mi_failure_logs_and_returns_zero(self, ctrl_log):
        with patch(
            "core.memory.unified_memory.get_unified_memory",
            side_effect=RuntimeError("mi import broken"),
        ):
            result = self._call()
        # Behavior contract: 0 on any failure
        assert result == 0
        # New: log shows the actual cause
        msgs = _messages(ctrl_log)
        assert any(
            "_update_weights_from_rules failed" in m
            and "mi import broken" in m
            for m in msgs
        )

    def test_no_rules_returns_zero_quietly(self, ctrl_log):
        """An empty rules list is the normal first-run case --
        return 0 with no warning."""
        mi = type("MI", (), {"get_rules": lambda self: []})()
        unified = type("U", (), {
            "get_memory_intelligence": lambda self: mi,
        })()
        with patch(
            "core.memory.unified_memory.get_unified_memory",
            return_value=unified,
        ):
            result = self._call()
        assert result == 0
        # No warning -- normal path
        warnings = [
            r for r in ctrl_log.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []

    def test_counts_rules_with_success(self, ctrl_log):
        rules = [
            {"success_count": 5},
            {"success_count": 0},
            {"success_count": 1},
            {},
        ]
        mi = type("MI", (), {
            "get_rules": lambda self: rules,
        })()
        unified = type("U", (), {
            "get_memory_intelligence": lambda self: mi,
        })()
        with patch(
            "core.memory.unified_memory.get_unified_memory",
            return_value=unified,
        ):
            result = self._call()
        assert result == 2  # the two with success_count > 0


class TestLearningSummaryWeightsLogging:
    """The weight_manager import inside get_learning_summary
    silently set weights={} on failure. Now it logs at debug."""

    def test_weight_manager_import_failure_logs(
        self, ctrl_log,
    ):
        from core.autonomous.controller import LearningPipeline
        with patch.dict(
            "sys.modules",
            # Force ImportError by stubbing the module to None
            {"core.intelligence.loop.weight_manager": None},
        ):
            # The orchestrator needs an init() that doesn't crash
            # -- use a real instance with stubbed components
            instance = LearningPipeline()
            # Skip _init_components by patching it
            with patch.object(
                instance, "_init_components", lambda: None,
            ):
                result = instance.get_learning_summary()
        # Behavior contract: weights is an empty dict
        assert result["weights"] == {}
        # New: a debug log fired
        debug_msgs = [
            r.message for r in ctrl_log.records
            if r.levelno == logging.DEBUG
        ]
        assert any(
            "weight_manager import for summary failed" in m
            for m in debug_msgs
        )
