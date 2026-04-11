"""Tests for audit-pass-23 fixes in core/learning.

  FeedbackStore:
    1. feedback_id used millisecond timestamp + last 6 chars of
       task_id — collided whenever two engines ran with the same
       (or empty) task_id within the same millisecond.
    2. record() called `(input_summary or {}).keys()` and
       `[s["step_name"] for s in step_results ...]` without
       isinstance checks — non-dict input or step entries crashed.
    3. _persist_engine wrote directly to the destination file
       (no atomic rename). A process crash mid-write left the
       file half-written and the next _load_engine returned [].
    4. _load_engine silently returned [] on JSON parse errors,
       leaving the corrupted file in place. The next persist
       overwrote it with empty data — total data loss.
    5. get_stats / _calculate_trend used direct h["status"]
       access — KeyError on malformed entries.
    6. get_history returned slice references — caller mutation
       poisoned the in-memory store.

  LearningEngine:
    7. _detect_patterns / _generate_recommendations / _assess_risk
       / _system_success_rate / analyze_system used direct
       `h[k]` and `stats[k]` access — KeyError or TypeError on
       malformed feedback rows.
"""
import json
import os
import threading

import pytest


@pytest.fixture
def store_dir(tmp_path):
    return str(tmp_path / "feedback")


def _store(store_dir):
    from core.learning.feedback_store import FeedbackStore
    return FeedbackStore(store_dir=store_dir)


# ── feedback_id uniqueness ──────────────────────────────────


class TestFeedbackIdUnique:
    def test_two_records_same_task_id_unique_ids(self, store_dir):
        s = _store(store_dir)
        a = s.record("eng", "task_123", "completed", 0.1)
        b = s.record("eng", "task_123", "completed", 0.1)
        assert a != b
        assert a.startswith("fb_")
        assert b.startswith("fb_")

    def test_empty_task_id_does_not_crash(self, store_dir):
        s = _store(store_dir)
        # Previously `task_id[-6:]` on an empty string returned ""
        # but the millisecond timestamp could still collide. Now
        # uuid is independent of task_id.
        a = s.record("eng", "", "completed", 0.1)
        b = s.record("eng", "", "completed", 0.1)
        assert a != b


# ── record() defensive isinstance ───────────────────────────


class TestRecordDefensive:
    def test_non_dict_input_summary_does_not_crash(self, store_dir):
        s = _store(store_dir)
        # Previously `(value or {}).keys()` crashed when value was
        # a string or list (truthy non-dict).
        s.record("eng", "t1", "completed", 0.5,
                 input_summary="raw response", output_summary=["a", "b"])
        history = s.get_history("eng")
        assert history[0]["input_keys"] == []
        assert history[0]["output_keys"] == []

    def test_non_dict_step_entry_skipped(self, store_dir):
        s = _store(store_dir)
        s.record("eng", "t1", "completed", 0.1, step_results=[
            {"step_name": "good", "status": "failed"},
            "bad",   # not a dict — must not crash
            None,
            {"name": "alt", "status": "failed"},  # uses 'name' fallback
        ])
        history = s.get_history("eng")
        # 'good' from step_name + 'alt' from name fallback
        assert history[0]["failed_steps"] == ["good", "alt"]
        # step_count uses len(list) defensive
        assert history[0]["step_count"] == 4

    def test_non_list_step_results(self, store_dir):
        s = _store(store_dir)
        s.record("eng", "t1", "completed", 0.1, step_results="not a list")
        history = s.get_history("eng")
        assert history[0]["step_count"] == 0
        assert history[0]["failed_steps"] == []


# ── Atomic persist + corrupted-file backup ──────────────────


class TestPersistAtomic:
    def test_persist_uses_atomic_rename(self, store_dir):
        s = _store(store_dir)
        s.record("eng", "t1", "completed", 0.1)
        # The .tmp sibling should not linger after a successful persist.
        path = os.path.join(store_dir, "eng.json")
        tmp = path + ".tmp"
        assert os.path.exists(path)
        assert not os.path.exists(tmp)

    def test_corrupt_file_moved_aside_on_load(self, store_dir):
        os.makedirs(store_dir, exist_ok=True)
        path = os.path.join(store_dir, "eng.json")
        with open(path, "w") as f:
            f.write("not valid json {{{")
        s = _store(store_dir)
        # _load_engine fires when first record() touches the engine
        s.record("eng", "t1", "completed", 0.1)
        # Original corrupted file moved aside
        backups = [f for f in os.listdir(store_dir) if "corrupted" in f]
        assert len(backups) == 1
        # New persist still wrote a clean file
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_wrong_shape_treated_as_corrupt(self, store_dir):
        os.makedirs(store_dir, exist_ok=True)
        path = os.path.join(store_dir, "eng.json")
        with open(path, "w") as f:
            json.dump({"not": "a list"}, f)
        s = _store(store_dir)
        s.record("eng", "t1", "completed", 0.1)
        backups = [f for f in os.listdir(store_dir) if "corrupted" in f]
        assert len(backups) == 1


# ── Persist error tracking ──────────────────────────────────


class TestPersistErrorTracking:
    def test_persist_failure_recorded(self, store_dir, monkeypatch):
        s = _store(store_dir)
        # Force the open() inside _persist_engine to raise
        import builtins
        real_open = builtins.open

        def _boom(path, *args, **kwargs):
            if path.endswith(".tmp"):
                raise OSError("disk full")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", _boom)
        s.record("eng", "t1", "completed", 0.1)
        errors = s.get_persist_errors()
        assert "eng" in errors
        assert "OSError" in errors["eng"]
        assert "disk full" in errors["eng"]

    def test_successful_persist_clears_error(self, store_dir):
        s = _store(store_dir)
        s._persist_errors["eng"] = "stale"
        s.record("eng", "t1", "completed", 0.1)
        # Persist succeeded → error cleared
        assert "eng" not in s.get_persist_errors()


# ── Defensive .get() in stats / trend ───────────────────────


class TestStatsDefensive:
    def test_missing_status_does_not_crash(self, store_dir):
        s = _store(store_dir)
        # Inject a malformed entry
        s._memory["eng"] = [
            {"timestamp": 0},  # no status, no elapsed_seconds
            {"status": "completed", "elapsed_seconds": 0.5},
        ]
        stats = s.get_stats("eng")
        assert stats["total_runs"] == 2
        assert stats["completed"] == 1

    def test_string_elapsed_seconds_skipped(self, store_dir):
        s = _store(store_dir)
        s._memory["eng"] = [
            {"status": "completed", "elapsed_seconds": "fast"},
            {"status": "completed", "elapsed_seconds": 0.5},
        ]
        # `sum() / len()` would crash on string. Now type-checked.
        stats = s.get_stats("eng")
        assert stats["avg_elapsed"] == 0.5

    def test_get_history_returns_deep_copies(self, store_dir):
        s = _store(store_dir)
        s.record("eng", "t1", "completed", 0.1)
        h1 = s.get_history("eng")
        h1[0]["mutated"] = "yes"
        h1[0]["input_keys"].append("leak")
        h2 = s.get_history("eng")
        assert "mutated" not in h2[0]
        assert "leak" not in h2[0]["input_keys"]


# ── LearningEngine defensive .get() ─────────────────────────


class TestLearningEngineDefensive:
    def _engine(self, store_dir):
        from core.learning.learning_engine import LearningEngine
        return LearningEngine(_store(store_dir))

    def test_analyze_handles_missing_status_in_history(self, store_dir):
        from core.learning.feedback_store import FeedbackStore
        s = FeedbackStore(store_dir=store_dir)
        # Inject malformed history
        s._memory["eng"] = [
            {"timestamp": 1.0, "elapsed_seconds": 0.5},  # no status
            {"status": "failed", "timestamp": 2.0, "elapsed_seconds": None},  # None elapsed
            {"status": "failed", "timestamp": "bad"},  # string ts
        ]
        from core.learning.learning_engine import LearningEngine
        eng = LearningEngine(s)
        # Must not raise
        result = eng.analyze("eng")
        assert "patterns" in result
        assert "recommendations" in result

    def test_analyze_handles_none_elapsed_in_pattern_detection(self, store_dir):
        from core.learning.feedback_store import FeedbackStore
        from core.learning.learning_engine import LearningEngine
        s = FeedbackStore(store_dir=store_dir)
        # 20 entries with mixed-type elapsed_seconds — pattern
        # detection should not crash on the None / string ones.
        s._memory["eng"] = []
        for i in range(20):
            s._memory["eng"].append({
                "status": "completed",
                "timestamp": float(i),
                "elapsed_seconds": (None if i % 2 == 0 else 0.5),
            })
        eng = LearningEngine(s)
        result = eng.analyze("eng")
        assert isinstance(result["patterns"], list)

    def test_analyze_system_handles_malformed_stats(self, store_dir):
        """analyze_system used direct s["total_runs"] / s["completed"]
        access — a malformed stats dict crashed the whole call."""
        from core.learning.feedback_store import FeedbackStore
        from core.learning.learning_engine import LearningEngine

        class _BrokenStore(FeedbackStore):
            def get_all_stats(self):
                return {
                    "good": {"total_runs": 5, "completed": 4, "success_rate": 0.8, "avg_elapsed": 1.0},
                    "broken": {},  # missing every field
                    "wrong_type": "not a dict",
                }

        eng = LearningEngine(_BrokenStore(store_dir=store_dir))
        # Must not raise
        result = eng.analyze_system()
        assert result["status"] == "analyzed"
        assert result["engines_analyzed"] == 2  # wrong_type filtered out
        assert result["total_runs"] == 5

    def test_assess_risk_handles_missing_fields(self, store_dir):
        from core.learning.learning_engine import LearningEngine
        eng = LearningEngine(_store(store_dir))
        assert eng._assess_risk({}) == "unknown"
        assert eng._assess_risk({"total_runs": 1, "success_rate": 0.5}) == "critical"
        assert eng._assess_risk({"total_runs": 1, "success_rate": 0.85}) == "warning"
        assert eng._assess_risk({"total_runs": 1, "success_rate": 0.95, "trend": "declining"}) == "watch"
        assert eng._assess_risk({"total_runs": 1, "success_rate": 0.95}) == "healthy"
