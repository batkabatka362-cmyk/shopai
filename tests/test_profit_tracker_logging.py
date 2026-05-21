"""Tests for ``brain.profit_optimization.tracker`` -- silent-
failure fix.

Before: ``_persist()`` swallowed all write failures with
``except Exception: pass``. A stuck disk / permission error
silently lost profit data for weeks until someone audited the
tracker and noticed it was empty. Same shape on ``_load()``.

After: each path logs a warning with the file path so the
data-loss signal is visible. The return contract (None /
empty list) is preserved.
"""
from __future__ import annotations

import json
import logging
import os

import pytest


@pytest.fixture
def tracker_factory(tmp_path):
    """Build a ProfitTracker rooted at a tmp dir we control."""

    def _make():
        from brain.profit_optimization.tracker import (
            ProfitTracker,
        )
        return ProfitTracker(profit_dir=str(tmp_path))

    return _make


class TestPersistLogging:

    def test_persist_failure_logs_warning_with_path(
        self, tmp_path, caplog,
    ):
        """When the write fails (e.g. the dir is replaced with a
        read-only file), the warning must include the target
        path so operators can find the broken mount."""
        from brain.profit_optimization.tracker import (
            ProfitTracker,
        )
        # Build a tracker pointing at a path where mkdir works
        # but writing the json fails.
        tracker = ProfitTracker(profit_dir=str(tmp_path))

        # Make the json file path unwritable by turning it into
        # a directory of the same name.
        target_dir = (
            tmp_path / "profit_tracking.json"
        )
        target_dir.mkdir()

        tracker._actions = [
            {"action": "test", "profit": 1.0},
        ]
        with caplog.at_level(logging.WARNING):
            tracker._persist()
        log_messages = [r.message for r in caplog.records]
        assert any(
            "ProfitTracker._persist failed" in m
            and "profit_tracking.json" in m
            for m in log_messages
        )

    def test_persist_success_does_not_log(
        self, tracker_factory, caplog,
    ):
        tracker = tracker_factory()
        tracker._actions = [
            {"action": "test", "profit": 1.0},
        ]
        with caplog.at_level(logging.WARNING):
            tracker._persist()
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []

    def test_persist_truncates_at_10k_before_writing(
        self, tracker_factory,
    ):
        """Behavior contract preserved: list size is still
        capped at 10000."""
        tracker = tracker_factory()
        tracker._actions = [
            {"action": "x", "profit": 0.0}
            for _ in range(10500)
        ]
        tracker._persist()
        assert len(tracker._actions) == 10000


class TestLoadLogging:

    def test_corrupt_file_logs_and_starts_empty(
        self, tmp_path, caplog,
    ):
        """A corrupt existing file -> log warning + start empty.
        Don't raise (tracker is non-critical at startup)."""
        from brain.profit_optimization.tracker import (
            ProfitTracker,
        )
        bad_path = tmp_path / "profit_tracking.json"
        bad_path.write_text("not valid json {{{")

        with caplog.at_level(logging.WARNING):
            tracker = ProfitTracker(profit_dir=str(tmp_path))
        # Behavior contract: empty actions, no crash
        assert tracker._actions == []
        # Log fired with the path
        log_messages = [r.message for r in caplog.records]
        assert any(
            "ProfitTracker._load failed" in m
            and "profit_tracking.json" in m
            for m in log_messages
        )

    def test_load_success_does_not_log(
        self, tmp_path, caplog,
    ):
        from brain.profit_optimization.tracker import (
            ProfitTracker,
        )
        good_path = tmp_path / "profit_tracking.json"
        good_path.write_text(json.dumps([
            {"action": "x", "profit": 5.0},
        ]))
        with caplog.at_level(logging.WARNING):
            tracker = ProfitTracker(profit_dir=str(tmp_path))
        assert len(tracker._actions) == 1
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []

    def test_load_missing_file_silent(
        self, tmp_path, caplog,
    ):
        """A missing file is the normal first-run case --
        should NOT log."""
        from brain.profit_optimization.tracker import (
            ProfitTracker,
        )
        with caplog.at_level(logging.DEBUG):
            tracker = ProfitTracker(profit_dir=str(tmp_path))
        assert tracker._actions == []
        # No warnings (or info or debug) for the normal path
        assert caplog.records == []


class TestRoundTrip:

    def test_persist_then_load_round_trip(
        self, tmp_path,
    ):
        """Sanity: writes survive a save/load cycle. This guards
        the behavior contract while we're touching the file."""
        from brain.profit_optimization.tracker import (
            ProfitTracker,
        )
        t1 = ProfitTracker(profit_dir=str(tmp_path))
        t1.record_action(
            action_type="discount",
            engine="loyalty",
            revenue=100.0,
            cost=20.0,
        )
        # Second tracker reads what the first wrote
        t2 = ProfitTracker(profit_dir=str(tmp_path))
        assert len(t2._actions) == 1
        assert t2._actions[0]["action_type"] == "discount"
        assert t2._actions[0]["profit"] == pytest.approx(80.0)
