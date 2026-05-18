"""Tests for ``core.approval.alert_quarantine`` -- the bridge
from alert_history to quarantine.

Covers:
  - env-var gates (enabled / threshold_days / window_days)
  - ``engines_to_pause`` filters by threshold + state lists
  - ``apply_pauses`` persists into the alert_paused set
  - ``maybe_auto_quarantine_from_alerts`` end-to-end:
      * disabled → []
      * Pattern J pytest guard → []
      * enabled + threshold met → engine added
  - ``QuarantineState.alert_paused`` round-trips through
    ``save_state`` / ``load_state``
  - ``evaluate()`` returns should_quarantine=True for alert-
    paused engines
  - Backwards-compat: old quarantine_state.json without
    alert_paused key loads cleanly
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _disable_alert_history_test_guard():
    """Pattern J guard in alert_history is on under pytest;
    flip it off so we can seed events."""
    with patch(
        "core.approval.alert_history._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture
def _disable_alert_quarantine_test_guard():
    """Per-test fixture (not autouse) -- some tests want the
    guard ON to verify Pattern J behaviour."""
    with patch(
        "core.approval.alert_quarantine._is_test_environment",
        return_value=False,
    ):
        yield


class _FakeAlert:
    def __init__(self, engine):
        self.engine = engine
        self.drop = 0.3
        self.recent_score = 0.4
        self.baseline_score = 0.7


# ─── env-var gates ───────────────────────────────────────────


class TestEnvVarGates:

    def test_is_enabled_default_off(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", raising=False,
        )
        from core.approval import alert_quarantine
        assert alert_quarantine.is_enabled() is False

    def test_is_enabled_with_var(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        from core.approval import alert_quarantine
        assert alert_quarantine.is_enabled() is True

    def test_is_enabled_other_values_off(self, monkeypatch):
        # Only "1" enables.
        for v in ("0", "true", "yes", ""):
            monkeypatch.setenv(
                "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", v,
            )
            from core.approval import alert_quarantine
            assert alert_quarantine.is_enabled() is False

    def test_threshold_days_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_DAYS", raising=False,
        )
        from core.approval import alert_quarantine
        assert alert_quarantine.threshold_days() == 3

    def test_threshold_days_override(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "5")
        from core.approval import alert_quarantine
        assert alert_quarantine.threshold_days() == 5

    def test_threshold_days_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_DAYS", "not_a_number",
        )
        from core.approval import alert_quarantine
        assert alert_quarantine.threshold_days() == 3

    def test_threshold_days_min_floor(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "0")
        from core.approval import alert_quarantine
        assert alert_quarantine.threshold_days() == 1

    def test_window_days_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_WINDOW_DAYS", raising=False,
        )
        from core.approval import alert_quarantine
        assert alert_quarantine.window_days() == 7


# ─── engines_to_pause ────────────────────────────────────────


class TestEnginesToPause:

    def test_disabled_returns_empty(self, data_dir, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", raising=False,
        )
        from core.approval import alert_quarantine, alert_history
        # Seed plenty of history -- doesn't matter, gate is off.
        day = 86400.0
        for i in range(5):
            alert_history.record_alerts(
                [_FakeAlert("loyalty")], now=day * i,
            )
        out = alert_quarantine.engines_to_pause(now=day * 6)
        assert out == []

    def test_above_threshold_returned(
        self, data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")
        from core.approval import alert_quarantine, alert_history
        day = 86400.0
        # 3 distinct days
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=day * 0 + 1,
        )
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=day * 1 + 1,
        )
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=day * 2 + 1,
        )
        out = alert_quarantine.engines_to_pause(now=day * 3)
        assert out == ["loyalty"]

    def test_below_threshold_excluded(
        self, data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")
        from core.approval import alert_quarantine, alert_history
        day = 86400.0
        # Only 2 distinct days -- below threshold of 3
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=day * 0 + 1,
        )
        alert_history.record_alerts(
            [_FakeAlert("loyalty")], now=day * 1 + 1,
        )
        out = alert_quarantine.engines_to_pause(now=day * 2)
        assert out == []

    def test_already_paused_excluded(
        self, data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")
        from core.approval import (
            alert_quarantine, alert_history, quarantine,
        )
        # Pre-pause loyalty -- shouldn't be re-recommended.
        quarantine.add_alert_pause("loyalty")
        day = 86400.0
        for i in range(3):
            alert_history.record_alerts(
                [_FakeAlert("loyalty")], now=day * i + 1,
            )
        out = alert_quarantine.engines_to_pause(now=day * 3)
        assert out == []

    def test_exempt_excluded(self, data_dir, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")
        from core.approval import (
            alert_quarantine, alert_history, quarantine,
        )
        quarantine.exempt_engine("loyalty")
        day = 86400.0
        for i in range(3):
            alert_history.record_alerts(
                [_FakeAlert("loyalty")], now=day * i + 1,
            )
        out = alert_quarantine.engines_to_pause(now=day * 3)
        assert out == []

    def test_multi_engine_independent(
        self, data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")
        from core.approval import alert_quarantine, alert_history
        day = 86400.0
        # loyalty over threshold, affiliate just below
        for i in range(3):
            alert_history.record_alerts(
                [_FakeAlert("loyalty")], now=day * i + 1,
            )
        for i in range(2):
            alert_history.record_alerts(
                [_FakeAlert("affiliate")], now=day * i + 1,
            )
        out = alert_quarantine.engines_to_pause(now=day * 3)
        assert out == ["loyalty"]

    def test_sorted_for_determinism(
        self, data_dir, monkeypatch,
    ):
        """Output sorted -- multiple engines crossing threshold
        on the same run come back in a deterministic order."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")
        from core.approval import alert_quarantine, alert_history
        day = 86400.0
        for engine in ("zebra", "alpha", "loyalty"):
            for i in range(3):
                alert_history.record_alerts(
                    [_FakeAlert(engine)], now=day * i + 1,
                )
        out = alert_quarantine.engines_to_pause(now=day * 3)
        assert out == ["alpha", "loyalty", "zebra"]


# ─── apply_pauses ────────────────────────────────────────────


class TestApplyPauses:

    def test_persists_into_alert_paused(self, data_dir):
        from core.approval import alert_quarantine, quarantine
        out = alert_quarantine.apply_pauses(["loyalty", "affiliate"])
        assert sorted(out) == ["affiliate", "loyalty"]
        s = quarantine.load_state()
        assert s.is_alert_paused("loyalty")
        assert s.is_alert_paused("affiliate")

    def test_returns_only_persisted(
        self, data_dir, monkeypatch,
    ):
        from core.approval import alert_quarantine

        # Force one to fail via patched add_alert_pause.
        original = __import__(
            "core.approval.quarantine", fromlist=["add_alert_pause"],
        ).add_alert_pause

        def maybe_raise(name):
            if name == "broken":
                raise OSError("disk full")
            return original(name)

        with patch(
            "core.approval.quarantine.add_alert_pause",
            side_effect=maybe_raise,
        ):
            out = alert_quarantine.apply_pauses(
                ["loyalty", "broken", "affiliate"],
            )
        # broken should be skipped; the rest persist.
        assert set(out) == {"loyalty", "affiliate"}


# ─── maybe_auto_quarantine_from_alerts ───────────────────────


class TestMaybeAutoQuarantine:

    def test_disabled_no_action(self, data_dir, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", raising=False,
        )
        from core.approval import alert_quarantine
        with patch(
            "core.approval.alert_quarantine._is_test_environment",
            return_value=False,
        ):
            out = alert_quarantine.maybe_auto_quarantine_from_alerts(
                now=86400.0 * 3,
            )
        assert out == []

    def test_pytest_guard_returns_empty(
        self, data_dir, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        from core.approval import alert_quarantine, alert_history
        day = 86400.0
        for i in range(5):
            alert_history.record_alerts(
                [_FakeAlert("loyalty")], now=day * i + 1,
            )
        # Default: _is_test_environment returns True under pytest
        with patch(
            "core.approval.alert_quarantine._is_test_environment",
            return_value=True,
        ):
            out = alert_quarantine.maybe_auto_quarantine_from_alerts(
                now=day * 6,
            )
        assert out == []

    def test_enabled_threshold_met(
        self,
        data_dir,
        monkeypatch,
        _disable_alert_quarantine_test_guard,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")
        from core.approval import (
            alert_quarantine, alert_history, quarantine,
        )
        day = 86400.0
        for i in range(3):
            alert_history.record_alerts(
                [_FakeAlert("loyalty")], now=day * i + 1,
            )
        out = alert_quarantine.maybe_auto_quarantine_from_alerts(
            now=day * 3,
        )
        assert out == ["loyalty"]
        # Persisted: loyalty is now alert_paused
        s = quarantine.load_state()
        assert s.is_alert_paused("loyalty")

    def test_enabled_but_below_threshold(
        self,
        data_dir,
        monkeypatch,
        _disable_alert_quarantine_test_guard,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")
        from core.approval import (
            alert_quarantine, alert_history, quarantine,
        )
        day = 86400.0
        # Only 2 distinct days -- below threshold
        for i in range(2):
            alert_history.record_alerts(
                [_FakeAlert("loyalty")], now=day * i + 1,
            )
        out = alert_quarantine.maybe_auto_quarantine_from_alerts(
            now=day * 3,
        )
        assert out == []
        s = quarantine.load_state()
        assert not s.is_alert_paused("loyalty")


# ─── QuarantineState alert_paused field ──────────────────────


class TestQuarantineStateAlertPaused:

    def test_default_empty(self, data_dir):
        from core.approval.quarantine import QuarantineState
        s = QuarantineState(
            exemptions=frozenset(), released=frozenset(),
        )
        assert s.alert_paused == frozenset()
        assert s.is_alert_paused("anything") is False

    def test_round_trip_save_load(self, data_dir):
        from core.approval.quarantine import (
            QuarantineState, save_state, load_state,
        )
        s = QuarantineState(
            exemptions=frozenset({"e1"}),
            released=frozenset({"r1"}),
            alert_paused=frozenset({
                ("p1", None),
                ("p2", None),
                ("p3", "store_a"),
            }),
        )
        save_state(s)
        loaded = load_state()
        assert loaded.exemptions == frozenset({"e1"})
        assert loaded.released == frozenset({"r1"})
        assert loaded.alert_paused == frozenset({
            ("p1", None),
            ("p2", None),
            ("p3", "store_a"),
        })

    def test_legacy_state_file_loads_with_empty_alert_paused(
        self, data_dir,
    ):
        """Backwards compat: old quarantine_state.json without
        the alert_paused key still loads."""
        from core.approval.quarantine import load_state
        legacy = {
            "exemptions": ["e1"],
            "released": ["r1"],
            # no "alert_paused" key
        }
        (data_dir / "quarantine_state.json").write_text(
            json.dumps(legacy), encoding="utf-8",
        )
        s = load_state()
        assert s.exemptions == frozenset({"e1"})
        assert s.released == frozenset({"r1"})
        assert s.alert_paused == frozenset()

    def test_add_alert_pause_then_clear(self, data_dir):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        assert quarantine.load_state().is_alert_paused("loyalty")
        quarantine.clear_alert_pause("loyalty")
        assert not (
            quarantine.load_state().is_alert_paused("loyalty")
        )

    def test_add_alert_pause_empty_raises(self, data_dir):
        from core.approval import quarantine
        with pytest.raises(ValueError):
            quarantine.add_alert_pause("")

    def test_per_store_pause_only_matches_that_store(
        self, data_dir,
    ):
        """``add_alert_pause(engine, store_id='a')`` pauses ONLY
        for store_a. Other stores stay unblocked."""
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty", store_id="store_a")
        s = quarantine.load_state()
        assert s.is_alert_paused("loyalty", store_id="store_a")
        assert not s.is_alert_paused(
            "loyalty", store_id="store_b",
        )
        # Implicit fleet check (no store_id) should NOT match
        # a per-store pause.
        assert not s.is_alert_paused("loyalty")

    def test_fleet_pause_matches_every_store(self, data_dir):
        """Fleet-wide ``(engine, None)`` matches ANY store."""
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")  # fleet-wide
        s = quarantine.load_state()
        assert s.is_alert_paused("loyalty")
        assert s.is_alert_paused("loyalty", store_id="any")
        assert s.is_alert_paused("loyalty", store_id="other")

    def test_clear_per_store_keeps_fleet(self, data_dir):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        quarantine.add_alert_pause("loyalty", store_id="store_a")
        quarantine.clear_alert_pause(
            "loyalty", store_id="store_a",
        )
        s = quarantine.load_state()
        assert s.is_alert_paused("loyalty")  # fleet still on
        assert ("loyalty", "store_a") not in s.alert_paused

    def test_clear_all_drops_every_pause_for_engine(
        self, data_dir,
    ):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        quarantine.add_alert_pause("loyalty", store_id="a")
        quarantine.add_alert_pause("loyalty", store_id="b")
        quarantine.add_alert_pause("affiliate")
        quarantine.clear_all_alert_pauses_for_engine("loyalty")
        s = quarantine.load_state()
        assert not any(
            engine == "loyalty"
            for (engine, _store) in s.alert_paused
        )
        # Untouched
        assert s.is_alert_paused("affiliate")

    def test_legacy_string_load_migrates_to_fleet_pair(
        self, data_dir,
    ):
        """Old quarantine_state.json with string entries should
        load as (engine, None) fleet-wide pauses."""
        import json as _json
        legacy = {
            "exemptions": [],
            "released": [],
            "alert_paused": ["loyalty", "affiliate"],
        }
        (data_dir / "quarantine_state.json").write_text(
            _json.dumps(legacy), encoding="utf-8",
        )
        from core.approval import quarantine
        s = quarantine.load_state()
        assert ("loyalty", None) in s.alert_paused
        assert ("affiliate", None) in s.alert_paused
        # Should match implicit and explicit-store checks
        assert s.is_alert_paused("loyalty")
        assert s.is_alert_paused(
            "affiliate", store_id="any_store",
        )

    def test_alert_paused_engines_helper(self, data_dir):
        """``alert_paused_engines()`` returns distinct engine
        names across both fleet + per-store entries."""
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        quarantine.add_alert_pause("loyalty", store_id="a")
        quarantine.add_alert_pause("affiliate", store_id="b")
        s = quarantine.load_state()
        assert s.alert_paused_engines() == frozenset({
            "loyalty", "affiliate",
        })

    def test_exempt_preserves_alert_paused(self, data_dir):
        """Operator running exempt_engine on a different engine
        shouldn't accidentally wipe the alert_paused set."""
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        quarantine.exempt_engine("affiliate")
        s = quarantine.load_state()
        assert s.is_alert_paused("loyalty")
        assert s.is_exempt("affiliate")


# ─── evaluate() picks up alert_paused ────────────────────────


class TestEvaluateAlertPaused:

    def test_alert_paused_engine_is_quarantined(self, data_dir):
        """Standalone evaluate() returns should_quarantine=True
        for an engine on the alert_paused list, even without
        any outcome history."""
        from core.approval import quarantine

        quarantine.add_alert_pause("loyalty")
        # No queue activity needed -- alert_paused short-
        # circuits before the outcome-based path.
        fake_queue = MagicMock()
        decision = quarantine.evaluate(
            engine="loyalty", queue=fake_queue,
        )
        assert decision.should_quarantine is True
        # Reason carries scope qualifier (fleet vs per-store)
        assert decision.reason.startswith(
            "auto_quarantine_from_alerts",
        )

    def test_exempt_beats_alert_paused(self, data_dir):
        """If an engine is BOTH exempted and alert_paused, the
        exempt list wins -- operator intent overrides
        automation."""
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        quarantine.exempt_engine("loyalty")
        decision = quarantine.evaluate(
            engine="loyalty", queue=MagicMock(),
        )
        assert decision.should_quarantine is False
        assert decision.reason == "engine_exempt"

    def test_released_beats_alert_paused(self, data_dir):
        """An operator manual release should beat the
        alert-pause -- the operator just took action."""
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        quarantine.release_engine("loyalty")
        decision = quarantine.evaluate(
            engine="loyalty", queue=MagicMock(),
        )
        assert decision.should_quarantine is False
        assert decision.reason == "engine_released_by_operator"
