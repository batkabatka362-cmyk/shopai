"""Tests for engines.strategist_memory — W963-43."""
from __future__ import annotations

from unittest.mock import patch

from engines.strategist_memory import StrategistMemoryEngine
from engines.strategist_memory import store as store_mod


# ── store module ──────────────────────────────────────────


class TestStore:
    def test_empty_default(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        assert store_mod.entry_count() == 0
        assert store_mod.stores_with_entries() == []

    def test_record_blocked_in_test_env(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        ok = store_mod.record(
            store_id="s1", signal="funnel",
            action="x",
        )
        assert ok is False

    def test_record_invalid_input_blocked(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            assert store_mod.record(
                store_id="", signal="funnel", action="x",
            ) is False
            assert store_mod.record(
                store_id="s1", signal="", action="x",
            ) is False
            assert store_mod.record(
                store_id="s1", signal="x", action="",
            ) is False

    def test_record_persists(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            ok = store_mod.record(
                store_id="s1", signal="funnel",
                action="run CRO",
                confidence=0.85, impact="high",
                priority_score=0.85,
            )
            assert ok is True
            assert store_mod.entry_count() == 1
            assert store_mod.stores_with_entries() == ["s1"]

    def test_recall_filters(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record(
                store_id="s1", signal="funnel", action="a",
            )
            store_mod.record(
                store_id="s2", signal="funnel", action="b",
            )
            store_mod.record(
                store_id="s1", signal="checkup", action="c",
            )
            assert (
                len(store_mod.recall(store_id="s1")) == 2
            )
            assert (
                len(store_mod.recall(signal="funnel")) == 2
            )
            assert (
                len(store_mod.recall(
                    store_id="s1", signal="funnel",
                )) == 1
            )

    def test_recall_returns_newest_first(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record(
                store_id="s1", signal="x", action="first",
            )
            store_mod.record(
                store_id="s1", signal="x", action="second",
            )
            store_mod.record(
                store_id="s1", signal="x", action="third",
            )
            out = store_mod.recall(store_id="s1", k=2)
        # k=2 returns last 2 entries, newest first
        assert out[0]["action"] == "third"
        assert out[1]["action"] == "second"

    def test_signal_stats(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record(
                store_id="s1", signal="x", action="a",
                outcome="positive",
            )
            store_mod.record(
                store_id="s1", signal="x", action="b",
                outcome="positive",
            )
            store_mod.record(
                store_id="s1", signal="x", action="c",
                outcome="negative",
            )
            stats = store_mod.signal_stats(
                store_id="s1", signal="x",
            )
        assert stats["positive"] == 2
        assert stats["negative"] == 1
        assert stats["total"] == 3

    def test_update_outcome_blocked_in_test_env(
        self, tmp_path,
    ):
        store_mod.reset_path(tmp_path / "sm.json")
        assert store_mod.update_outcome(
            entry_index=0, outcome="positive",
        ) is False

    def test_update_outcome_invalid_index(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            assert store_mod.update_outcome(
                entry_index=99, outcome="positive",
            ) is False

    def test_update_outcome_invalid_value(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record(
                store_id="s1", signal="x", action="a",
            )
            assert store_mod.update_outcome(
                entry_index=0, outcome="weird",
            ) is False

    def test_update_outcome_persists(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record(
                store_id="s1", signal="x", action="a",
            )
            ok = store_mod.update_outcome(
                entry_index=0, outcome="positive",
            )
        assert ok is True
        entries = store_mod.recall(store_id="s1")
        assert entries[0]["outcome"] == "positive"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        # Default action is "recall"
        r = StrategistMemoryEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = StrategistMemoryEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = StrategistMemoryEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = StrategistMemoryEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_unknown_action_error(self):
        r = StrategistMemoryEngine().run({
            "data": {"action": "blast"},
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = StrategistMemoryEngine().run({})
        assert r["meta"]["engine"] == "strategist_memory"


class TestActions:
    def test_summary_action(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        r = StrategistMemoryEngine().run({
            "data": {"action": "summary"},
        })
        d = r["data"]
        assert d["total_entries"] == 0
        assert d["stores_with_entries"] == []

    def test_record_action_blocked_in_test_env(
        self, tmp_path,
    ):
        store_mod.reset_path(tmp_path / "sm.json")
        r = StrategistMemoryEngine().run({
            "data": {
                "action": "record",
                "store_id": "s1",
                "signal": "funnel",
                "recommendation": "x",
            },
        })
        assert r["data"]["wrote"] is False

    def test_recall_action_filters(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record(
                store_id="s1", signal="funnel", action="a",
            )
            store_mod.record(
                store_id="s2", signal="funnel", action="b",
            )
        r = StrategistMemoryEngine().run({
            "data": {
                "action": "recall",
                "store_id": "s1",
                "k": 5,
            },
        })
        entries = r["data"]["entries"]
        assert len(entries) == 1

    def test_stats_action(self, tmp_path):
        store_mod.reset_path(tmp_path / "sm.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record(
                store_id="s1", signal="x", action="a",
                outcome="positive",
            )
            store_mod.record(
                store_id="s1", signal="x", action="b",
                outcome="negative",
            )
        r = StrategistMemoryEngine().run({
            "data": {
                "action": "stats",
                "store_id": "s1",
                "signal": "x",
            },
        })
        s = r["data"]["stats"]
        assert s["positive"] == 1
        assert s["negative"] == 1

    def test_invalid_k_falls_back(self):
        r = StrategistMemoryEngine().run({
            "data": {
                "action": "recall", "k": "abc",
            },
        })
        assert r["data"]["k"] == 10

    def test_update_outcome_blocked_in_test_env(
        self, tmp_path,
    ):
        store_mod.reset_path(tmp_path / "sm.json")
        r = StrategistMemoryEngine().run({
            "data": {
                "action": "update_outcome",
                "entry_index": 0,
                "outcome": "positive",
            },
        })
        assert r["data"]["wrote"] is False
