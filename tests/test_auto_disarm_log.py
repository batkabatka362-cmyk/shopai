"""Tests for engines.agi_arm_recommender.auto_disarm_log — W963-84."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from engines.agi_arm_recommender import auto_disarm_log as log


@pytest.fixture(autouse=True)
def _disable_pytest_guard():
    """Lift the Pattern J guard for these tests so they can
    actually exercise the record/load paths. tmp_path
    fixture (below) keeps the live file untouched."""
    with patch.object(
        log, "_is_test_environment", return_value=False,
    ):
        yield


@pytest.fixture
def _tmp_log(tmp_path):
    p = tmp_path / "auto_disarm_log.json"
    with patch.object(log, "_DATA_PATH", p):
        yield p


# ── record_event ──────────────────────────────────────────


class TestRecord:
    def test_writes_when_valid(self, _tmp_log):
        ok = log.record_event(
            override_reason="critical_loss_streak",
            domains_disarmed=["marketing"],
            engines_recommended=["ads_launcher"],
        )
        assert ok is True
        assert log.entry_count() == 1

    def test_rejects_empty_reason(self, _tmp_log):
        ok = log.record_event(
            override_reason="",
            domains_disarmed=["marketing"],
        )
        assert ok is False
        assert log.entry_count() == 0

    def test_rejects_empty_domains(self, _tmp_log):
        ok = log.record_event(
            override_reason="x",
            domains_disarmed=[],
        )
        assert ok is False
        assert log.entry_count() == 0

    def test_engines_default_empty(self, _tmp_log):
        ok = log.record_event(
            override_reason="x",
            domains_disarmed=["marketing"],
        )
        assert ok is True
        events = log.recent_events()
        assert events[0]["engines_recommended"] == []

    def test_string_coerces(self, _tmp_log):
        """Ensure non-str entries get stringified."""
        ok = log.record_event(
            override_reason="x",
            domains_disarmed=[123, "marketing"],
            engines_recommended=[None, "ads_launcher"],
        )
        assert ok is True
        events = log.recent_events()
        assert events[0]["domains_disarmed"] == [
            "123", "marketing",
        ]
        assert events[0]["engines_recommended"] == [
            "None", "ads_launcher",
        ]

    def test_bounded_at_max_entries(self, _tmp_log):
        with patch.object(log, "_MAX_ENTRIES", 3):
            for i in range(5):
                log.record_event(
                    override_reason=f"r{i}",
                    domains_disarmed=["d"],
                )
            assert log.entry_count() == 3
            events = log.recent_events()
            # Bounded to last 3
            reasons = [e["override_reason"] for e in events]
            assert "r2" in reasons
            assert "r3" in reasons
            assert "r4" in reasons


# ── recent_events ─────────────────────────────────────────


class TestRecentEvents:
    def test_empty(self, _tmp_log):
        assert log.recent_events() == []

    def test_newest_first(self, _tmp_log):
        # Write 3 events; recent_events orders newest-first
        log.record_event(
            override_reason="r0", domains_disarmed=["d"],
        )
        log.record_event(
            override_reason="r1", domains_disarmed=["d"],
        )
        log.record_event(
            override_reason="r2", domains_disarmed=["d"],
        )
        events = log.recent_events()
        assert events[0]["override_reason"] == "r2"
        assert events[2]["override_reason"] == "r0"

    def test_window_filter(self, _tmp_log):
        # Manually inject old + new events
        log.record_event(
            override_reason="old", domains_disarmed=["d"],
        )
        # Patch in old ts
        with log._DATA_PATH.open("r", encoding="utf-8") as f:
            import json
            entries = json.load(f)
        entries[0]["ts"] = time.time() - 10 * 86400.0
        with log._DATA_PATH.open("w", encoding="utf-8") as f:
            json.dump(entries, f)
        log.record_event(
            override_reason="new", domains_disarmed=["d"],
        )
        # 24h window: only "new" should appear
        events = log.recent_events(hours=24.0)
        assert len(events) == 1
        assert events[0]["override_reason"] == "new"

    def test_limit_applied(self, _tmp_log):
        for i in range(10):
            log.record_event(
                override_reason=f"r{i}",
                domains_disarmed=["d"],
            )
        events = log.recent_events(limit=3)
        assert len(events) == 3


# ── latest_event ──────────────────────────────────────────


class TestLatest:
    def test_empty_returns_none(self, _tmp_log):
        assert log.latest_event() is None

    def test_returns_newest(self, _tmp_log):
        log.record_event(
            override_reason="old", domains_disarmed=["d"],
        )
        log.record_event(
            override_reason="new", domains_disarmed=["d"],
        )
        latest = log.latest_event()
        assert latest["override_reason"] == "new"


# ── Pattern J guard ───────────────────────────────────────


class TestPatternJGuard:
    def test_pytest_short_circuits(self, _tmp_log):
        # Specifically test the guard
        with patch.object(
            log, "_is_test_environment",
            return_value=True,
        ):
            ok = log.record_event(
                override_reason="r",
                domains_disarmed=["d"],
            )
        assert ok is False
        assert log.entry_count() == 0

    def test_force_production_env_override(
        self, _tmp_log,
    ):
        """SHOPAI_FORCE_PRODUCTION_WRITES=1 lifts the
        guard."""
        import os
        with patch.dict(
            os.environ,
            {
                "SHOPAI_FORCE_PRODUCTION_WRITES": "1",
                "PYTEST_CURRENT_TEST": "fake",
            },
        ):
            assert log._is_test_environment() is False


# ── Corrupt JSON ──────────────────────────────────────────


class TestCorruptHandling:
    def test_corrupt_json_returns_empty(self, _tmp_log):
        _tmp_log.write_text("{not valid json", encoding="utf-8")
        assert log._load_raw() == []
        assert log.entry_count() == 0
        assert log.recent_events() == []
