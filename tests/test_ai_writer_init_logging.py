"""Tests for ``execution.content.ai_writer`` -- silent-fail
fix on lazy-init imports and outcome recording.

Same shape as #476 (SmartExecutor): lazy imports for optional
dependencies were silently swallowed. The writer then ran in
""template mode"" or ""no outcome recording"" mode forever without
operator signal.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from execution.content import ai_writer as _ai_writer_mod  # noqa: F401


_LOGGER = "shopai.ai_writer"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def aw_log() -> _ListHandler:
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


class TestInitLogging:

    def test_llm_init_failure_logs(self, aw_log):
        from execution.content.ai_writer import AIWriter
        writer = AIWriter()
        with patch(
            "core.system.llm_adapter.get_llm",
            side_effect=RuntimeError("llm broken"),
        ):
            writer._init()
        msgs = _messages(aw_log)
        assert any(
            "ai_writer llm_adapter init failed" in m
            and "llm broken" in m
            for m in msgs
        )
        # Behavior contract: _llm stays None, writer keeps
        # running in template-fallback mode
        assert writer._llm is None

    def test_experience_init_failure_logs(self, aw_log):
        from execution.content.ai_writer import AIWriter
        writer = AIWriter()
        with patch(
            "core.ai.experience.get_experience",
            side_effect=RuntimeError("exp broken"),
        ):
            writer._init()
        msgs = _messages(aw_log)
        assert any(
            "ai_writer experience init failed" in m
            and "exp broken" in m
            for m in msgs
        )

    def test_record_decision_outcome_failure_logs(
        self, aw_log,
    ):
        """The 3rd silent site -- record_decision_outcome call
        inside generation. Test the helper directly with a
        mock experience that raises."""
        from execution.content.ai_writer import AIWriter
        writer = AIWriter()
        # Stub a fake experience that raises on the call we
        # exercise
        bad_exp = type("E", (), {
            "record_decision_outcome": lambda self, *a, **k: (
                _ for _ in ()
            ).throw(RuntimeError("xp record broken")),
        })()
        writer._experience = bad_exp
        # The silent site lives inside the body of one of the
        # generation methods. We'll trigger it by calling
        # generate_description which goes through the recorder
        # path at line ~290.
        with patch.object(
            writer, "_llm", None,
        ):
            writer.generate_description(
                {"name": "X", "price": 10},
                style="professional",
            )
        msgs = _messages(aw_log)
        # The record_decision_outcome failure surfaced
        assert any(
            "experience.record_decision_outcome" in m
            and "xp record broken" in m
            and "X" in m
            for m in msgs
        )
