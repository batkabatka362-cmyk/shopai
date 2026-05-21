"""Tests for ``brain.global_brain.memory`` -- silent-failure
fix on ``_persist`` + ``_load``.

Mirrors the profit_tracker pattern (PR #475): silent file-IO
failures meant global brain knowledge could be lost for weeks
before anyone noticed the JSON was stale. The fix preserves
the return contract (empty start on load failure; no raise
from persist) but adds warning-level logs with the file path
so the data-loss signal is debuggable.
"""
from __future__ import annotations

import json
import logging

import pytest


@pytest.fixture
def make_brain(tmp_path):
    """Build a GlobalBrainMemory rooted at a tmp path so tests
    can simulate file-IO failures without touching production
    data."""

    def _make():
        from brain.global_brain.memory import GlobalBrainMemory
        return GlobalBrainMemory(brain_dir=str(tmp_path))

    return _make


class TestPersistLogging:

    def test_persist_failure_logs_warning_with_path(
        self, tmp_path, caplog,
    ):
        """Replace the target path with a directory of the same
        name -- the json.dump open() fails with IsADirectoryError /
        PermissionError."""
        from brain.global_brain.memory import GlobalBrainMemory
        brain = GlobalBrainMemory(brain_dir=str(tmp_path))
        target = tmp_path / "knowledge.json"
        target.mkdir()

        brain._knowledge = [{"k": 1}]
        brain._patterns = [{"p": 1}]
        with caplog.at_level(logging.WARNING):
            brain._persist()
        log_messages = [r.message for r in caplog.records]
        assert any(
            "GlobalBrainMemory._persist failed" in m
            and "knowledge.json" in m
            for m in log_messages
        )

    def test_persist_success_no_log(self, make_brain, caplog):
        brain = make_brain()
        brain._knowledge = [{"k": 1}]
        with caplog.at_level(logging.WARNING):
            brain._persist()
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []

    def test_persist_truncates_at_10k(self, make_brain):
        brain = make_brain()
        brain._knowledge = [{"k": i} for i in range(10500)]
        brain._persist()
        assert len(brain._knowledge) == 10000


class TestLoadLogging:

    def test_corrupt_file_logs_and_starts_empty(
        self, tmp_path, caplog,
    ):
        from brain.global_brain.memory import GlobalBrainMemory
        bad = tmp_path / "knowledge.json"
        bad.write_text("not valid json {{{")
        with caplog.at_level(logging.WARNING):
            brain = GlobalBrainMemory(brain_dir=str(tmp_path))
        assert brain._knowledge == []
        assert brain._patterns == []
        log_messages = [r.message for r in caplog.records]
        assert any(
            "GlobalBrainMemory._load failed" in m
            and "knowledge.json" in m
            for m in log_messages
        )

    def test_missing_file_silent_first_run(
        self, tmp_path, caplog,
    ):
        """Missing file is the normal first-run case -- no log."""
        from brain.global_brain.memory import GlobalBrainMemory
        with caplog.at_level(logging.DEBUG):
            brain = GlobalBrainMemory(brain_dir=str(tmp_path))
        assert brain._knowledge == []
        assert caplog.records == []


class TestRoundTrip:

    def test_persist_then_load(self, tmp_path):
        from brain.global_brain.memory import GlobalBrainMemory
        b1 = GlobalBrainMemory(brain_dir=str(tmp_path))
        b1._knowledge = [{"k": "v"}]
        b1._patterns = [{"p": "q"}]
        b1._persist()
        b2 = GlobalBrainMemory(brain_dir=str(tmp_path))
        assert b2._knowledge == [{"k": "v"}]
        assert b2._patterns == [{"p": "q"}]
