"""Tests for ``execution.continuous_optimizer`` -- 4 silent
Pattern S sites.

The continuous optimizer auto-fixes store issues each cycle.
Before this PR, when a fix attempt failed (store_optimizer
crashed, shopify_automation down, telemetry broken) the
optimizer silently returned None / [] and the operator
had no signal -- ""why didn't this product get its description
generated?"" had no breadcrumb.

After: each path logs at debug with the relevant context.
Behavior contracts preserved.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from execution import continuous_optimizer as _co_mod  # noqa: F401


_LOGGER = "shopai.optimizer.continuous"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def co_log() -> _ListHandler:
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


class TestFixHandlersLogging:

    def test_fix_description_failure_logs_with_pid(
        self, co_log,
    ):
        from execution.continuous_optimizer import (
            ContinuousOptimizer,
        )
        opt = ContinuousOptimizer()
        with patch(
            "execution.store_optimizer.get_store_optimizer",
            side_effect=RuntimeError("optimizer down"),
        ):
            result = opt._fix_description(
                {"id": "P1"}, "shop.com", "tok",
            )
        # Behavior contract: returns None on failure
        assert result is None
        msgs = _messages(co_log)
        assert any(
            "_fix_description failed" in m
            and "P1" in m
            and "optimizer down" in m
            for m in msgs
        )

    def test_fix_tags_failure_logs_with_pid(self, co_log):
        from execution.continuous_optimizer import (
            ContinuousOptimizer,
        )
        opt = ContinuousOptimizer()
        with patch(
            "execution.store_optimizer.get_store_optimizer",
            side_effect=RuntimeError("optimizer down"),
        ):
            result = opt._fix_tags(
                {"id": "P2"}, "shop.com", "tok",
            )
        assert result is None
        msgs = _messages(co_log)
        assert any(
            "_fix_tags failed" in m and "P2" in m for m in msgs
        )


class TestUpdateSegmentsLogging:

    def test_segments_update_failure_logs_count(self, co_log):
        from execution.continuous_optimizer import (
            ContinuousOptimizer,
        )
        with patch(
            "execution.shopify_automation.get_shopify_automation",
            side_effect=RuntimeError("automation down"),
        ):
            result = ContinuousOptimizer._update_segments(
                [{"id": 1}, {"id": 2}, {"id": 3}],
                "shop.com", "tok",
            )
        assert result == []
        msgs = _messages(co_log)
        assert any(
            "_update_segments failed" in m
            and "3 customers" in m
            and "automation down" in m
            for m in msgs
        )

    def test_no_credentials_no_log(self, co_log):
        from execution.continuous_optimizer import (
            ContinuousOptimizer,
        )
        # No shop_url / token -- early-return no log
        result = ContinuousOptimizer._update_segments(
            [{"id": 1}], "", "",
        )
        assert result == []
        assert co_log.records == []


class TestRecordTelemetryLogging:

    def test_telemetry_failure_logs_with_fix_count(
        self, co_log,
    ):
        from execution.continuous_optimizer import (
            ContinuousOptimizer,
        )
        with patch(
            "core.data.architecture.get_data_architecture",
            side_effect=RuntimeError("da down"),
        ):
            ContinuousOptimizer._record(
                [{"type": "description", "product": "p1"}],
                "store-a",
            )
        msgs = _messages(co_log)
        assert any(
            "_record telemetry write failed" in m
            and "store=store-a" in m
            and "da down" in m
            for m in msgs
        )

    def test_empty_fixes_no_log(self, co_log):
        from execution.continuous_optimizer import (
            ContinuousOptimizer,
        )
        ContinuousOptimizer._record([], "store-a")
        assert co_log.records == []
