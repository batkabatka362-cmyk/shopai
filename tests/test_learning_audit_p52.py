"""Tests for audit-pass-52 fixes — defensive + security
hardening across ``core/learning/*``.

Real bugs fixed:

  * SECURITY: OutcomeTracker._save_unlocked / _load_unlocked
    and FeedbackStore._persist_engine / _load_engine did
    ``os.path.join(store_dir, f"{engine}.json")`` with no
    engine_name validation. A caller with partial control
    over the engine parameter could write to / read from
    arbitrary filesystem paths via ``"../../etc/passwd"``.
    Same path-traversal class fixed in pass 50 for
    feature_store.delete.

  * OutcomeTracker._load_unlocked silently returned [] on a
    corrupted outcomes file — the next ``_save_unlocked``
    call then overwrote it with fresh data, destroying the
    engine's entire learning history forever. Same data-loss
    pattern as pass 48 (feedback_store) and pass 20
    (StoreSnapshot). Now the corrupted file is moved to
    ``<path>.corrupted.<ts>`` before fallback.

  * OutcomeTracker.should_proceed crashed with AttributeError
    on a non-dict decision argument because of the chained
    ``decision.get(...)`` calls.

  * ImprovementTracker.propose used
    ``improvement_id = f"imp_{int(time.time() * 1000)}"``
    which collided whenever two proposals landed in the same
    millisecond. Now uses uuid4 for guaranteed uniqueness.

  * ImprovementTracker._persist wrote directly to the
    destination path without ``.tmp`` + ``os.replace``. A
    crash mid-write left a half-written file, and the next
    ``_load()`` silently returned an empty list, destroying
    the entire improvement history. Now atomic.

  * ImprovementTracker._load silently overwrote a corrupted
    file on the next persist — same data-loss bug as
    outcome_tracker / feedback_store. Now backs up first.

  * ImprovementTracker.mark_applied / record_impact /
    list_proposed / list_applied / get_improvement_history /
    _count_by_type all did direct ``imp["key"]`` subscripts
    which crashed with KeyError if an entry from an older
    schema version was missing a field. Now ``.get()``.

  * RootCauseAnalyzer.analyze_failure crashed on non-dict
    failed_episode (``if not failed_episode`` passed string /
    list / int through to the ``.get()`` call).

  * RootCauseAnalyzer._factor_attribution /
    analyze_pattern crashed on non-dict context values from
    a misbehaving memory backend.

  * RootCauseAnalyzer._factor_attribution checked
    ``isinstance(v, bool)`` AFTER
    ``isinstance(v, (int, float))``, so bool values
    (which are a subclass of int) were counted as raw
    numerics rather than converted to 1.0 / 0.0. Same
    bool-subclass-of-int class fixed in passes 41 / 45 / 51.
"""
from __future__ import annotations

import json
import os
import threading

import pytest

from core.learning.feedback_store import (
    FeedbackStore,
    _valid_engine_name as _valid_fs,
)
from core.learning.improvement_tracker import ImprovementTracker
from core.learning.outcome_tracker import (
    OutcomeTracker,
    _valid_engine_name as _valid_ot,
)
from core.learning.root_cause_analyzer import RootCauseAnalyzer


# ═══════════════════════════════════════════════════════════
# Path-traversal guard
# ═══════════════════════════════════════════════════════════


class TestEngineNameValidation:
    def test_valid_names(self):
        assert _valid_ot("test_engine")
        assert _valid_ot("engine-1")
        assert _valid_ot("ABC_123")
        assert _valid_fs("test_engine")

    def test_path_traversal_rejected(self):
        assert not _valid_ot("../etc/passwd")
        assert not _valid_ot("..")
        assert not _valid_ot("a/b")
        assert not _valid_ot("a\\b")
        assert not _valid_fs("../etc/passwd")

    def test_none_and_empty(self):
        assert not _valid_ot(None)
        assert not _valid_ot("")
        assert not _valid_ot(42)
        assert not _valid_fs(None)

    def test_special_chars_rejected(self):
        assert not _valid_ot("engine.json")
        assert not _valid_ot("engine$")
        assert not _valid_ot("engine ")


# ═══════════════════════════════════════════════════════════
# OutcomeTracker
# ═══════════════════════════════════════════════════════════


class TestOutcomeTrackerPass52:
    @pytest.fixture
    def tracker(self, tmp_path, monkeypatch):
        import core.learning.outcome_tracker as mod
        monkeypatch.setattr(mod, "_OUTCOME_DIR", str(tmp_path))
        return OutcomeTracker()

    def test_record_decision_invalid_engine(self, tracker, tmp_path):
        """Path traversal rejected at the public entry."""
        tracker.record_decision("d1", "../etc/passwd", {"x": 1})
        files = os.listdir(str(tmp_path))
        assert "passwd.json" not in files
        assert not any(".." in f for f in files)

    def test_record_decision_none_engine(self, tracker):
        tracker.record_decision("d1", None, {})  # type: ignore[arg-type]

    def test_record_outcome_non_dict(self, tracker):
        tracker.record_decision("d1", "test", {})
        assert tracker.record_outcome("d1", "test", "raw string") is True  # type: ignore[arg-type]

    def test_record_outcome_none_outcome(self, tracker):
        tracker.record_decision("d1", "test", {})
        assert tracker.record_outcome("d1", "test", None) is True  # type: ignore[arg-type]

    def test_record_outcome_invalid_engine(self, tracker):
        assert tracker.record_outcome("d1", "../etc", {"ok": True}) is False

    def test_should_proceed_non_dict(self, tracker):
        """Regression: pre-audit ``decision.get(...)`` crashed."""
        r = tracker.should_proceed("test", None)  # type: ignore[arg-type]
        assert "proceed" in r
        r2 = tracker.should_proceed("test", "raw")  # type: ignore[arg-type]
        assert "proceed" in r2

    def test_corrupted_outcome_file_backed_up(self, tracker, tmp_path):
        """Regression: pre-audit silently returned []; next
        save overwrote the corrupted file, destroying history."""
        tracker.record_decision("d1", "test", {"a": 1})
        path = os.path.join(str(tmp_path), "test.json")
        with open(path, "w") as f:
            f.write("{not json")
        result = tracker._load("test")
        assert result == []
        backups = [
            f for f in os.listdir(str(tmp_path))
            if f.startswith("test.json.corrupted.")
        ]
        assert len(backups) >= 1

    def test_non_list_json_backed_up(self, tracker, tmp_path):
        path = os.path.join(str(tmp_path), "test.json")
        with open(path, "w") as f:
            json.dump({"not": "a list"}, f)
        result = tracker._load("test")
        assert result == []
        backups = [
            f for f in os.listdir(str(tmp_path))
            if f.startswith("test.json.corrupted.")
        ]
        assert len(backups) >= 1


# ═══════════════════════════════════════════════════════════
# FeedbackStore — pass 52 additions
# ═══════════════════════════════════════════════════════════


class TestFeedbackStorePass52:
    def test_invalid_engine_rejected(self, tmp_path):
        fs = FeedbackStore(store_dir=str(tmp_path))
        fid = fs.record("../etc/passwd", "t1", "completed", 1.0)
        assert fid == ""
        assert not any(".." in f for f in os.listdir(str(tmp_path)))

    def test_none_engine_rejected(self, tmp_path):
        fs = FeedbackStore(store_dir=str(tmp_path))
        assert fs.record(None, "t1", "completed", 1.0) == ""  # type: ignore[arg-type]

    def test_valid_record_works(self, tmp_path):
        fs = FeedbackStore(store_dir=str(tmp_path))
        fid = fs.record("test", "t1", "completed", 1.0)
        assert fid.startswith("fb_")
        assert len(fs.get_history("test")) == 1

    def test_get_history_invalid_engine(self, tmp_path):
        fs = FeedbackStore(store_dir=str(tmp_path))
        assert fs.get_history("../etc/passwd") == []

    def test_get_all_stats_filters_corrupted_backups(self, tmp_path):
        fs = FeedbackStore(store_dir=str(tmp_path))
        fs.record("good_engine", "t1", "completed", 1.0)
        # Drop a corrupted backup alongside the real file.
        (tmp_path / "good_engine.json.corrupted.123.json").write_text("[]")
        stats = fs.get_all_stats()
        assert "good_engine" in stats
        # Backup stem has dots in it → invalid engine name → skipped.
        assert not any("." in k for k in stats)


# ═══════════════════════════════════════════════════════════
# ImprovementTracker
# ═══════════════════════════════════════════════════════════


class TestImprovementTrackerPass52:
    @pytest.fixture
    def tracker(self, tmp_path):
        return ImprovementTracker(tracker_path=str(tmp_path / "imp.json"))

    def test_uuid_ids_unique(self, tracker):
        """Regression: millisecond-based ids collided."""
        ids = set()
        for _ in range(100):
            ids.add(tracker.propose("e1", "fix", "d", "i"))
        assert len(ids) == 100

    def test_concurrent_propose_unique(self, tracker):
        ids: list[str] = []
        barrier = threading.Barrier(8)

        def fire():
            barrier.wait()
            for _ in range(10):
                ids.append(tracker.propose("e1", "fix", "d", "i"))

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(ids) == 80
        assert len(set(ids)) == 80

    def test_propose_none_engine_rejected(self, tracker):
        assert tracker.propose(None, "fix", "d", "i") == ""  # type: ignore[arg-type]

    def test_atomic_persist(self, tracker, tmp_path):
        tracker.propose("e1", "fix", "d", "i")
        path = tmp_path / "imp.json"
        assert path.exists()
        assert not (tmp_path / "imp.json.tmp").exists()

    def test_corrupted_file_backup_on_load(self, tmp_path):
        """A corrupted improvements file is moved to a
        ``.corrupted.<ts>`` backup before the next persist
        overwrites it."""
        path = tmp_path / "imp.json"
        path.write_text("{not json")
        tracker = ImprovementTracker(tracker_path=str(path))
        assert tracker._improvements == []
        backups = [
            f for f in os.listdir(str(tmp_path))
            if f.startswith("imp.json.corrupted.")
        ]
        assert len(backups) >= 1

    def test_non_list_json_backed_up(self, tmp_path):
        path = tmp_path / "imp.json"
        path.write_text('{"not": "a list"}')
        tracker = ImprovementTracker(tracker_path=str(path))
        assert tracker._improvements == []
        backups = [
            f for f in os.listdir(str(tmp_path))
            if f.startswith("imp.json.corrupted.")
        ]
        assert len(backups) >= 1

    def test_mark_applied_entry_missing_id_field(self, tracker):
        """Direct ``imp["id"]`` crashed on older-schema entries."""
        tracker._improvements.append({"status": "proposed"})
        assert tracker.mark_applied("nonexistent") is False

    def test_record_impact_non_dict_coerced(self, tracker):
        iid = tracker.propose("e1", "fix", "d", "i")
        assert tracker.record_impact(iid, "just a string") is True  # type: ignore[arg-type]

    def test_record_impact_invalid_id(self, tracker):
        assert tracker.record_impact(None, {"ok": True}) is False  # type: ignore[arg-type]

    def test_count_by_type_missing_type_field(self, tracker):
        tracker._improvements.append({"id": "x", "status": "proposed"})
        summary = tracker.summary()
        assert "by_type" in summary


# ═══════════════════════════════════════════════════════════
# RootCauseAnalyzer
# ═══════════════════════════════════════════════════════════


class TestRootCauseAnalyzerPass52:
    def test_analyze_failure_non_dict(self):
        rca = RootCauseAnalyzer()
        r = rca.analyze_failure("not a dict")  # type: ignore[arg-type]
        assert r["root_causes"] == []

    def test_analyze_failure_int(self):
        rca = RootCauseAnalyzer()
        r = rca.analyze_failure(42)  # type: ignore[arg-type]
        assert r["root_causes"] == []

    def test_analyze_failure_null_context(self):
        """Regression: ``failed_context.get(factor)`` crashed
        on context=None."""
        rca = RootCauseAnalyzer()
        r = rca.analyze_failure({"decision_type": "pricing", "context": None})
        assert "lesson" in r

    def test_analyze_failure_non_dict_context(self):
        rca = RootCauseAnalyzer()
        r = rca.analyze_failure({"decision_type": "pricing", "context": "raw"})
        assert "lesson" in r

    def test_analyze_pattern_no_memory(self):
        rca = RootCauseAnalyzer()
        r = rca.analyze_pattern("pricing")
        assert r["status"] == "no_memory"

    def test_analyze_pattern_mixed_memory_return(self):
        class MixedMemory:
            def get_failures(self, decision_type=None):
                return [
                    None,
                    "not a dict",
                    {"context": None},
                    {"context": "also not a dict"},
                    {"context": {"health_grade": "F"}},
                ]

        rca = RootCauseAnalyzer(episodic_memory=MixedMemory())
        r = rca.analyze_pattern("pricing")
        # Should not crash; only the well-formed entry counts.
        assert "common_conditions" in r

    def test_factor_attribution_bool_treated_as_01(self):
        """Regression: bool check happened AFTER (int, float)
        check, so True was silently counted as the int 1.
        Now checked first."""
        rca = RootCauseAnalyzer()
        successes = [
            {"context": {"stockout_risk": True}},
            {"context": {"stockout_risk": True}},
            {"context": {"stockout_risk": True}},
        ]
        r = rca._factor_attribution({"stockout_risk": False}, successes)
        stockout = [f for f in r if f.get("factor") == "stockout_risk"]
        assert stockout, f"stockout_risk not flagged: {r}"
