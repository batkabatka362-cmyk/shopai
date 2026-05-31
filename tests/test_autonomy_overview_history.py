"""Tests for autonomy_overview_history (Wave 900)."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.automation.autonomy_overview import OverviewSnapshot
from core.automation.autonomy_overview_history import (
    OverviewHistoryEntry,
    history_size,
    recent_entries,
    record_snapshot,
    verdict_transitions,
)


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    with patch(
        "core.automation.autonomy_overview_history."
        "_is_test_environment",
        return_value=False,
    ):
        yield


def _snap(**kw):
    s = OverviewSnapshot()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class TestRecordSnapshot:

    def test_writes_one_entry(self, tmp_path):
        p = tmp_path / "h.json"
        record_snapshot(_snap(), path=p)
        assert history_size(path=p) == 1

    def test_appends_across_calls(self, tmp_path):
        p = tmp_path / "h.json"
        for _ in range(3):
            record_snapshot(_snap(), path=p)
        assert history_size(path=p) == 3

    def test_bounded_at_500(self, tmp_path):
        p = tmp_path / "h.json"
        from core.automation import autonomy_overview_history
        original = autonomy_overview_history._MAX_ENTRIES
        try:
            autonomy_overview_history._MAX_ENTRIES = 5
            for _ in range(10):
                record_snapshot(_snap(), path=p)
            assert history_size(path=p) == 5
        finally:
            autonomy_overview_history._MAX_ENTRIES = original


class TestRecentEntries:

    def test_returns_newest_first(self, tmp_path):
        p = tmp_path / "h.json"
        for i in range(3):
            s = _snap(armed_total=i)
            s.captured_at = 1000 + i
            record_snapshot(s, path=p)
        entries = recent_entries(path=p)
        assert entries[0].armed_total == 2
        assert entries[-1].armed_total == 0

    def test_limit_caps(self, tmp_path):
        p = tmp_path / "h.json"
        for _ in range(10):
            record_snapshot(_snap(), path=p)
        assert len(recent_entries(path=p, limit=3)) == 3

    def test_store_filter(self, tmp_path):
        p = tmp_path / "h.json"
        record_snapshot(_snap(store_id="a"), path=p)
        record_snapshot(_snap(store_id="b"), path=p)
        record_snapshot(_snap(store_id="a"), path=p)
        only_a = recent_entries(path=p, store_id="a")
        assert len(only_a) == 2

    def test_window_filter(self, tmp_path):
        p = tmp_path / "h.json"
        old = _snap()
        old.captured_at = time.time() - 7200  # 2h ago
        record_snapshot(old, path=p)
        new = _snap()
        new.captured_at = time.time()
        record_snapshot(new, path=p)
        # 1h window excludes old
        within_1h = recent_entries(
            path=p, window_hours=1.0,
        )
        assert len(within_1h) == 1

    def test_empty_file(self, tmp_path):
        p = tmp_path / "missing.json"
        assert recent_entries(path=p) == []


class TestVerdictTransitions:

    def test_first_entry_is_transition(self, tmp_path):
        p = tmp_path / "h.json"
        record_snapshot(_snap(), path=p)  # idle
        trans = verdict_transitions(path=p)
        assert len(trans) == 1
        assert trans[0]["from"] is None
        assert trans[0]["to"] == "idle"

    def test_only_changes_recorded(self, tmp_path):
        p = tmp_path / "h.json"
        for _ in range(3):
            record_snapshot(_snap(), path=p)  # all idle
        record_snapshot(_snap(armed_total=2), path=p)  # armed
        record_snapshot(_snap(armed_total=2), path=p)  # armed
        record_snapshot(
            _snap(armed_total=2, alerts_critical=1), path=p,
        )  # degraded
        trans = verdict_transitions(path=p)
        # idle -> armed -> degraded = 3 transitions
        # (first idle counts as None -> idle)
        assert len(trans) == 3
        assert [t["to"] for t in trans] == [
            "idle", "armed", "degraded",
        ]

    def test_store_scope(self, tmp_path):
        p = tmp_path / "h.json"
        record_snapshot(_snap(store_id="a"), path=p)
        record_snapshot(
            _snap(store_id="b", armed_total=1), path=p,
        )
        trans_a = verdict_transitions(path=p, store_id="a")
        assert len(trans_a) == 1
        assert trans_a[0]["to"] == "idle"

    def test_window_hours_filter(self, tmp_path):
        """W937 bugfix: window_hours must filter transitions."""
        p = tmp_path / "h.json"
        old = _snap()
        old.captured_at = time.time() - 7200  # 2h ago
        record_snapshot(old, path=p)
        new = _snap(armed_total=2)  # different verdict
        new.captured_at = time.time()
        record_snapshot(new, path=p)
        # Full history: 2 transitions (None->idle, idle->armed)
        trans_full = verdict_transitions(path=p)
        assert len(trans_full) == 2
        # 1h window excludes old idle entry
        trans_window = verdict_transitions(
            path=p, window_hours=1.0,
        )
        assert len(trans_window) == 1
        assert trans_window[0]["to"] == "armed"

    def test_limit_caps_transitions(self, tmp_path):
        """W937 bugfix: limit must cap transitions."""
        p = tmp_path / "h.json"
        verdicts = ["idle", "armed", "active",
                    "armed", "idle"]
        for v in verdicts:
            s = _snap()
            if v == "armed":
                s.armed_total = 1
            elif v == "active":
                s.armed_total = 1
                s.fires_invoked = 1
            record_snapshot(s, path=p)
        # 5 transitions total (None->idle + 4 flips)
        assert len(verdict_transitions(path=p)) == 5
        # limit=2 takes the 2 most recent
        last2 = verdict_transitions(path=p, limit=2)
        assert len(last2) == 2
        assert last2[-1]["to"] == "idle"


class TestEntryFromSnapshot:

    def test_carries_all_fields(self):
        s = _snap(
            armed_total=5, fires_invoked=3, fires_errors=1,
            alerts_critical=2,
        )
        e = OverviewHistoryEntry.from_snapshot(s)
        assert e.armed_total == 5
        assert e.fires_invoked == 3
        assert e.fires_errors == 1
        assert e.alerts_critical == 2

    def test_to_dict_roundtrips(self):
        s = _snap(armed_total=7)
        d = OverviewHistoryEntry.from_snapshot(s).to_dict()
        assert d["armed_total"] == 7
        assert "verdict" in d


class TestPytestGuard:

    def test_short_circuits_under_pytest(self, tmp_path):
        # Re-enable the guard
        from core.automation import autonomy_overview_history
        p = tmp_path / "h.json"
        with patch.object(
            autonomy_overview_history,
            "_is_test_environment",
            return_value=True,
        ):
            record_snapshot(_snap(), path=p)
        assert not p.exists()
