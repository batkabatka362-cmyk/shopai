"""Tests for audit-pass-22 fixes in core/orchestrator/cycle_journal.

  1. _load() wrapped the entire load in try/except and silently
     reset _entries to []. The next _persist() then overwrote the
     corrupted-but-recoverable file with empty data, destroying
     ALL audit history forever — same data-loss bug pattern fixed
     in StoreSnapshot.load() in pass 20.
  2. _load() didn't validate that json.load() returned a list.
     Wrong-shape JSON (e.g. dict at top level) silently corrupted
     self._entries with a bad type.
  3. _persist() failures were logged-and-forgotten with no
     instance-state tracking.
  4. get_recent / get_decisions / get_by_goal returned slice
     references — caller mutation poisoned the in-memory journal.
  5. get_recent() crashed with TypeError when an entry's
     timestamp was None or non-numeric (the previous
     `e.get("timestamp", 0) > cutoff` comparison did `None >
     float`).
"""
import json
import os
import threading

import pytest


@pytest.fixture
def journal_dir(tmp_path):
    return str(tmp_path / "journal")


def _journal(journal_dir):
    from core.orchestrator.cycle_journal import CycleJournal
    return CycleJournal(journal_dir=journal_dir)


# ── _load() corrupted file backup ────────────────────────────


class TestLoadCorruptedBackup:
    def test_corrupt_json_moved_aside(self, journal_dir):
        """Regression: previously corrupted JSON was silently
        ignored and the next _persist overwrote it with []."""
        os.makedirs(journal_dir, exist_ok=True)
        path = os.path.join(journal_dir, "journal.json")
        with open(path, "w") as f:
            f.write("not valid {{{")

        j = _journal(journal_dir)
        assert j._entries == []
        # Original file moved aside, NOT just left for the next
        # _persist() to overwrite
        assert not os.path.exists(path)
        backups = [f for f in os.listdir(journal_dir) if "corrupted" in f]
        assert len(backups) == 1

    def test_wrong_shape_json_treated_as_corrupt(self, journal_dir):
        """A dict at top level is valid JSON but the wrong shape
        for a journal — should be treated as corruption."""
        os.makedirs(journal_dir, exist_ok=True)
        path = os.path.join(journal_dir, "journal.json")
        with open(path, "w") as f:
            json.dump({"not": "a list"}, f)

        j = _journal(journal_dir)
        assert j._entries == []
        backups = [f for f in os.listdir(journal_dir) if "corrupted" in f]
        assert len(backups) == 1

    def test_missing_file_starts_empty(self, journal_dir):
        j = _journal(journal_dir)
        assert j._entries == []

    def test_valid_journal_round_trips(self, journal_dir):
        j = _journal(journal_dir)
        j.record_cycle({
            "cycle_id": "c1",
            "summary": {"decision": "raise", "confidence_score": 80},
            "timestamp": 1000,
        })
        # Reload
        j2 = _journal(journal_dir)
        assert len(j2._entries) == 1
        assert j2._entries[0]["cycle_id"] == "c1"


# ── persist error tracking ──────────────────────────────────


class TestPersistErrorTracking:
    def test_persist_failure_recorded(self, journal_dir, monkeypatch):
        j = _journal(journal_dir)
        # Force open() to fail when persist tries to write
        import builtins
        original_open = builtins.open

        def _boom(path, *args, **kwargs):
            if "tmp" in str(path):
                raise OSError("disk full")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", _boom)
        j.record_cycle({"cycle_id": "x", "summary": {}})
        err = j.get_persist_error()
        assert "OSError" in err
        assert "disk full" in err

    def test_successful_persist_clears_error(self, journal_dir):
        j = _journal(journal_dir)
        j._last_persist_error = "stale"
        j.record_cycle({"cycle_id": "y", "summary": {}})
        assert j.get_persist_error() == ""


# ── Defensive copies in getters ─────────────────────────────


class TestGetterDefensiveCopies:
    def test_get_recent_returns_copies(self, journal_dir):
        j = _journal(journal_dir)
        j.record_cycle({
            "cycle_id": "c1",
            "summary": {"decision": "raise"},
            "timestamp": 9_999_999_999,  # very recent
        })
        recent = j.get_recent(hours=24)
        recent[0]["mutated"] = "yes"
        # Original entry untouched
        again = j.get_recent(hours=24)
        assert "mutated" not in again[0]

    def test_get_decisions_returns_copies(self, journal_dir):
        j = _journal(journal_dir)
        j.record_cycle({
            "cycle_id": "c1",
            "summary": {"decision": "raise"},
        })
        decisions = j.get_decisions()
        decisions[0]["poison"] = True
        again = j.get_decisions()
        assert "poison" not in again[0]

    def test_get_by_goal_returns_copies(self, journal_dir):
        j = _journal(journal_dir)
        j.record_cycle({
            "cycle_id": "c1",
            "goal": "maximize_profit",
            "summary": {},
        })
        goal_results = j.get_by_goal("maximize_profit")
        goal_results[0]["mutated"] = "yes"
        again = j.get_by_goal("maximize_profit")
        assert "mutated" not in again[0]


# ── Timestamp coercion ──────────────────────────────────────


class TestTimestampCoercion:
    def test_none_timestamp_does_not_crash_get_recent(self, journal_dir):
        """Regression: previously `e.get("timestamp", 0) > cutoff`
        crashed with `TypeError: '>' not supported between
        instances of 'NoneType' and 'float'`."""
        j = _journal(journal_dir)
        # Inject a malformed entry directly
        with j._lock:
            j._entries.append({"cycle_id": "broken", "timestamp": None})
        # Must not raise
        recent = j.get_recent(hours=24)
        assert isinstance(recent, list)

    def test_string_timestamp_does_not_crash(self, journal_dir):
        j = _journal(journal_dir)
        with j._lock:
            j._entries.append({"cycle_id": "broken", "timestamp": "yesterday"})
        recent = j.get_recent(hours=24)
        assert isinstance(recent, list)

    def test_numeric_string_timestamp_parsed(self, journal_dir):
        """A timestamp stored as a numeric string should be
        coerced via float() and respected."""
        import time as _t
        j = _journal(journal_dir)
        with j._lock:
            j._entries.append({
                "cycle_id": "ok",
                "timestamp": str(_t.time()),
            })
        recent = j.get_recent(hours=24)
        assert any(e["cycle_id"] == "ok" for e in recent)
