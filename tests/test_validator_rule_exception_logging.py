"""Tests for ``data_pipeline.quality.validator`` -- silent
rule-exception fix.

Before: a business-rule function raising on a record (e.g.
KeyError on a missing field) was silently caught with
``except Exception: pass``. The rule's pass count stayed
unchanged AND the record could still be counted as valid
even if a critical rule had effectively been skipped.
Operators couldn't tell ""rule passing"" from ""rule broken"".

After: the exception is logged at debug with the rule name
and exception. Behavior contract preserved -- the rule is
still treated as not-pass for that record (status quo from
the original code path).
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from data_pipeline.quality import validator as _validator_mod  # noqa: F401


_LOGGER = "shopai.data_quality"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def quality_log() -> _ListHandler:
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


class TestRuleExceptionLogging:

    def test_raising_rule_logged_with_name(self, quality_log):
        from data_pipeline.quality.validator import (
            DataQualityPipeline,
        )

        def bad_rule(rec):
            raise KeyError("missing_field")

        def good_rule(rec):
            return True

        pipeline = DataQualityPipeline()
        result = pipeline._validate_records(
            records=[{"id": 1}],
            required=["id"],
            rules={
                "bad_rule": bad_rule,
                "good_rule": good_rule,
            },
            record_type="test",
        )
        # Behavior contract preserved: good rule passes, bad
        # rule didn't crash, record was still considered valid
        # (the bad_rule was not a critical_rule).
        assert result["valid_count"] == 1
        # Log fired for the raising rule
        msgs = _messages(quality_log)
        assert any(
            "rule bad_rule raised" in m
            and "missing_field" in m
            for m in msgs
        )

    def test_passing_rules_no_log(self, quality_log):
        from data_pipeline.quality.validator import (
            DataQualityPipeline,
        )
        pipeline = DataQualityPipeline()
        result = pipeline._validate_records(
            records=[{"id": 1, "title": "ok"}],
            required=["id"],
            rules={
                "always_pass": lambda r: True,
            },
            record_type="test",
        )
        assert result["valid_count"] == 1
        # No debug logs about rules raising
        msgs = _messages(quality_log)
        assert not any("raised" in m for m in msgs)

    def test_multiple_rules_raising_each_logged(
        self, quality_log,
    ):
        from data_pipeline.quality.validator import (
            DataQualityPipeline,
        )
        pipeline = DataQualityPipeline()
        pipeline._validate_records(
            records=[{"id": 1}],
            required=["id"],
            rules={
                "rule_a": lambda r: (_ for _ in ()).throw(
                    ValueError("a")
                ),
                "rule_b": lambda r: (_ for _ in ()).throw(
                    TypeError("b")
                ),
            },
            record_type="test",
        )
        msgs = _messages(quality_log)
        assert any("rule rule_a raised" in m for m in msgs)
        assert any("rule rule_b raised" in m for m in msgs)
