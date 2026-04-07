"""Tests for audit-pass-19 fixes in core/orchestrator/action_coordinator.

  1. start_action() unconditionally overwrote any existing
     in_flight entry sharing the same flight_key. Two concurrent
     starters silently shared the same key, and the first
     finish_action removed BOTH entries' tracking. The whole
     point of in-flight bookkeeping was broken.
  2. The check() → start_action() pattern had a TOCTOU race: two
     threads could both pass check() before either called
     start_action(), then both proceed with the same target.
  3. get_stats / get_recent_actions / _find_last_action /
     _find_conflict used direct `entry["action_type"]` access —
     a malformed ledger entry crashed the whole stats / lookup
     call with KeyError.
"""
import threading

import pytest


def _coord():
    from core.orchestrator.action_coordinator import ActionCoordinator
    return ActionCoordinator()


# ── start_action no-overwrite ───────────────────────────────


class TestStartActionNoOverwrite:
    def test_second_start_returns_none(self):
        c = _coord()
        a1 = c.start_action("price_increase", "p1")
        a2 = c.start_action("price_increase", "p1")
        assert a1 is not None
        assert a2 is None

    def test_different_targets_both_start(self):
        c = _coord()
        a1 = c.start_action("price_increase", "p1")
        a2 = c.start_action("price_increase", "p2")
        assert a1 is not None
        assert a2 is not None
        assert a1 != a2
        assert len(c.get_in_flight()) == 2

    def test_finish_then_restart_works(self):
        c = _coord()
        # Use a low-cooldown action to avoid the cooldown gate
        a1 = c.start_action("ad_pause", "camp1")
        c.record("ad_pause", "camp1")
        # After finishing, we can start the same action again
        a2 = c.start_action("ad_pause", "camp1")
        assert a2 is not None
        assert a1 != a2


# ── try_start atomic check + reservation ────────────────────


class TestTryStartAtomic:
    def test_first_caller_wins(self):
        c = _coord()
        v1 = c.try_start("ad_launch", "camp1")
        v2 = c.try_start("ad_launch", "camp1")
        assert v1["allowed"] is True
        assert "action_id" in v1
        assert v2["allowed"] is False  # in_flight conflict

    def test_concurrent_try_start_only_one_wins(self):
        """Regression: previously two threads could both pass
        check() before either called start_action(). With
        try_start the entire check + reserve happens under one
        lock acquire, so exactly one wins."""
        c = _coord()
        winners: list[bool] = []

        def worker():
            v = c.try_start("ad_launch", "shared_camp")
            winners.append(v["allowed"])

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one of the 20 concurrent callers wins
        assert sum(1 for w in winners if w) == 1
        assert sum(1 for w in winners if not w) == 19
        # And exactly one in-flight entry exists
        assert len(c.get_in_flight()) == 1

    def test_try_start_blocked_when_cooldown_active(self):
        c = _coord()
        c.record("price_increase", "p1")  # marks last action
        # Cooldown is 12h → next try_start should be blocked
        v = c.try_start("price_increase", "p1")
        assert v["allowed"] is False
        assert "Cooldown" in v["reason"]
        # And nothing reserved in_flight
        assert len(c.get_in_flight()) == 0


# ── Defensive .get on ledger entries ────────────────────────


class TestDefensiveGetOnLedger:
    def test_get_stats_handles_missing_keys(self):
        c = _coord()
        # Inject a malformed entry directly
        with c._lock:
            c._ledger.append({"action_id": "broken"})  # no action_type, no result
        stats = c.get_stats()
        assert stats["total_actions"] == 1
        # Missing fields bucket as "unknown"
        assert stats["by_type"]["unknown"] == 1
        assert stats["by_result"]["unknown"] == 1

    def test_get_recent_actions_returns_copies(self):
        c = _coord()
        c.record("ad_launch", "camp1")
        recent = c.get_recent_actions()
        recent[0]["mutated"] = "yes"
        # Original ledger entry untouched
        again = c.get_recent_actions()
        assert "mutated" not in again[0]

    def test_find_last_action_handles_missing_target_id(self):
        c = _coord()
        with c._lock:
            c._ledger.append({
                "action_type": "ad_launch",
                "timestamp": 0,
                # No target_id
            })
        # Looking for any ad_launch (target_id="") should still
        # find this without crashing
        result = c._find_last_action("ad_launch", "")
        assert result is not None


# ── Existing check() still works ────────────────────────────


class TestCheckRegression:
    def test_check_passes_on_clean_state(self):
        c = _coord()
        v = c.check("ad_launch", "camp1")
        assert v["allowed"] is True

    def test_check_blocks_on_in_flight(self):
        c = _coord()
        c.start_action("ad_launch", "camp1")
        v = c.check("ad_launch", "camp1")
        assert v["allowed"] is False
        assert "in-flight" in v["reason"]

    def test_check_blocks_on_cooldown(self):
        c = _coord()
        c.record("price_increase", "p1")
        v = c.check("price_increase", "p1")
        assert v["allowed"] is False
        assert "Cooldown" in v["reason"]
