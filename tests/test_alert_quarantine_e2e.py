"""End-to-end integration test for the auto-quarantine chain.

Proves the full loop works against a REAL SQLite-backed
ApprovalQueue:

  1. Engine fires degradation alerts on 3 consecutive days
     -> ``alert_history.record_alerts`` persists each firing
  2. ``alert_quarantine.maybe_auto_quarantine_from_alerts``
     reads the consecutive-day count, sees 3 >= threshold,
     and adds the engine to ``quarantine_state.alert_paused``
  3. A new ``ApprovalQueue.enqueue`` for that engine triggers
     the standard ``maybe_quarantine`` path, which calls
     ``evaluate()``, which short-circuits to should_quarantine
     because the engine is alert_paused
  4. The just-enqueued action transitions PENDING -> REJECTED
     with ``decided_by="auto_quarantine"`` and a reason
     containing ``"auto_quarantine_from_alerts"``

The unit tests for each layer mock the next. This test
exercises real persistence + real queue + real evaluator
end-to-end. If any of those layers regresses, this test
breaks first.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def queue(tmp_path: Path):
    from core.approval.queue import ApprovalQueue
    q = ApprovalQueue(db_path=tmp_path / "approval.db")
    yield q
    q._conn.close()


@pytest.fixture(autouse=True)
def _disable_alert_history_test_guard():
    """Pattern J guards in alert_history + alert_quarantine
    must both be lifted for this E2E test to work."""
    with patch(
        "core.approval.alert_history._is_test_environment",
        return_value=False,
    ), patch(
        "core.approval.alert_quarantine._is_test_environment",
        return_value=False,
    ), patch(
        "core.approval.quarantine._is_test_environment",
        return_value=False,
    ):
        yield


class _FakeAlert:
    def __init__(self, engine):
        self.engine = engine
        self.drop = 0.65
        self.recent_score = 0.2
        self.baseline_score = 0.85


def _seed_alert_firings(
    *, engine: str, days: int, now: float | None = None,
) -> None:
    """Record one alert per day for ``days`` distinct days."""
    from core.approval import alert_history
    now = now if now is not None else time.time()
    day = 86400.0
    for i in range(days):
        # Stagger each firing by a full day so each lands in a
        # distinct bucket
        alert_history.record_alerts(
            [_FakeAlert(engine)], now=now - day * (days - i - 1),
        )


# ─── End-to-end ──────────────────────────────────────────────


class TestAutoQuarantineE2E:

    def test_full_chain_quarantines_new_enqueue(
        self, data_dir, queue, monkeypatch,
    ):
        """Three days of alert firings -> bridge fires ->
        next enqueue gets REJECTED via the standard
        quarantine path."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")

        # Step 1: record alert firings
        _seed_alert_firings(engine="loyalty", days=3)

        # Step 2: run the bridge
        from core.approval import alert_quarantine
        paused = alert_quarantine.maybe_auto_quarantine_from_alerts()
        assert "loyalty" in paused

        # Step 3 (verify): state is persisted
        from core.approval import quarantine
        assert quarantine.load_state().is_alert_paused("loyalty")

        # Step 4: enqueue an action for the now-paused engine
        action = queue.enqueue(
            engine="loyalty", action_type="mint_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={}, narrative="",
        )

        # Step 5: action got rejected via the standard
        # quarantine path
        from core.approval.queue import ApprovalStatus
        assert action.status == ApprovalStatus.REJECTED
        assert action.decided_by == "auto_quarantine"
        assert (
            "auto_quarantine_from_alerts" in action.decision_reason
        )

    def test_two_days_not_enough(
        self, data_dir, queue, monkeypatch,
    ):
        """Only 2 distinct days of firings -- below the
        3-day threshold -- means NO auto-pause."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")

        _seed_alert_firings(engine="loyalty", days=2)

        from core.approval import alert_quarantine, quarantine
        paused = alert_quarantine.maybe_auto_quarantine_from_alerts()
        assert paused == []
        assert not (
            quarantine.load_state().is_alert_paused("loyalty")
        )

        # New enqueue stays PENDING (no auto-pause was triggered)
        action = queue.enqueue(
            engine="loyalty", action_type="mint_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={}, narrative="",
        )
        from core.approval.queue import ApprovalStatus
        assert action.status == ApprovalStatus.PENDING

    def test_bridge_disabled_means_no_quarantine(
        self, data_dir, queue, monkeypatch,
    ):
        """Without the env var, alerts pile up but the bridge
        doesn't act on them. Engines stay healthy."""
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", raising=False,
        )

        _seed_alert_firings(engine="loyalty", days=10)

        from core.approval import alert_quarantine, quarantine
        paused = alert_quarantine.maybe_auto_quarantine_from_alerts()
        assert paused == []
        assert not (
            quarantine.load_state().is_alert_paused("loyalty")
        )

        action = queue.enqueue(
            engine="loyalty", action_type="mint_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={}, narrative="",
        )
        from core.approval.queue import ApprovalStatus
        assert action.status == ApprovalStatus.PENDING

    def test_release_alert_unlocks_engine(
        self, data_dir, queue, monkeypatch,
    ):
        """Operator clears the alert-pause -> next enqueue
        flows normally again."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")

        _seed_alert_firings(engine="loyalty", days=3)
        from core.approval import alert_quarantine, quarantine
        alert_quarantine.maybe_auto_quarantine_from_alerts()
        assert quarantine.load_state().is_alert_paused("loyalty")

        # Operator releases
        quarantine.clear_alert_pause("loyalty")
        assert not (
            quarantine.load_state().is_alert_paused("loyalty")
        )

        # Next enqueue is clean
        action = queue.enqueue(
            engine="loyalty", action_type="mint_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={}, narrative="",
        )
        from core.approval.queue import ApprovalStatus
        assert action.status == ApprovalStatus.PENDING

    def test_decision_log_carries_alert_reason(
        self, data_dir, queue, monkeypatch,
    ):
        """Audit trail: the decision_log row for the
        auto-rejected action carries the
        ``auto_quarantine_from_alerts`` reason so post-hoc
        forensics can distinguish alert-based from outcome-
        based quarantine."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")

        _seed_alert_firings(engine="loyalty", days=3)
        from core.approval import alert_quarantine
        alert_quarantine.maybe_auto_quarantine_from_alerts()

        action = queue.enqueue(
            engine="loyalty", action_type="mint_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={}, narrative="",
        )

        rows = queue.list_decisions(action_id=action.id)
        assert len(rows) >= 1
        # Find the auto_quarantine decision row
        aq_rows = [
            r for r in rows
            if (r.get("decided_by") or "") == "auto_quarantine"
        ]
        assert len(aq_rows) == 1
        reason = aq_rows[0].get("reason") or ""
        assert "auto_quarantine_from_alerts" in reason

    def test_exempt_overrides_alert_pause(
        self, data_dir, queue, monkeypatch,
    ):
        """An operator-exempted engine stays PENDING even
        when the bridge has alert-paused it. Operator intent
        beats automation."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS", "1",
        )
        monkeypatch.setenv("SHOPAI_AUTO_QUARANTINE_DAYS", "3")

        # Pre-exempt before any alerts -- engine should never
        # show up in the engines_to_pause output, so no need
        # to release it explicitly.
        from core.approval import quarantine
        quarantine.exempt_engine("loyalty")

        _seed_alert_firings(engine="loyalty", days=3)
        from core.approval import alert_quarantine
        paused = alert_quarantine.maybe_auto_quarantine_from_alerts()
        # exempt engines are filtered out of the recommendation
        assert "loyalty" not in paused

        action = queue.enqueue(
            engine="loyalty", action_type="mint_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={}, narrative="",
        )
        from core.approval.queue import ApprovalStatus
        assert action.status == ApprovalStatus.PENDING
