"""Tests for core/system/approval_notifier.py + queue hook wiring.

Design invariant: **the notifier must NEVER block or raise**.
Every test verifies a failure path returns False cleanly
instead of propagating to the caller.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from core.contracts import RiskLevel
from core.system import approval_notifier as mod
from core.system.approval_queue import (
    ApprovalQueue, ApprovalRequest,
    reset_singleton_for_tests,
)


def _fake_req(
    level: RiskLevel = RiskLevel.HIGH,
    action_type: str = "ad_campaign_create",
    payload: dict | None = None,
) -> ApprovalRequest:
    now = time.time()
    return ApprovalRequest(
        request_id="abc123def4567890",
        action_type=action_type,
        payload=dict(payload or {"daily_budget_usd": 20}),
        risk_level=level,
        status="pending",
        requested_at=now,
        expires_at=now + 1800,
    )


class _FakeAdapter:
    """Minimal commodity-layer stand-in. Records send_message
    calls + whether is_available was probed."""

    def __init__(self, available: bool = True, result: int | None = 42):
        self._available = available
        self._result = result
        self.calls: list[str] = []
        self.availability_checks = 0

    def is_available(self) -> bool:
        self.availability_checks += 1
        return self._available

    def send_message(self, text: str, **_kwargs) -> int | None:
        self.calls.append(text)
        return self._result


# ── render_message ─────────────────────────────────────


class TestRenderMessage:
    def test_high_renders_with_emoji(self):
        msg = mod.render_message(_fake_req(RiskLevel.HIGH))
        assert "HIGH approval needed" in msg
        assert "🚨" in msg

    def test_critical_renders_with_emoji(self):
        msg = mod.render_message(_fake_req(RiskLevel.CRITICAL))
        assert "CRITICAL approval needed" in msg
        assert "🆘" in msg

    def test_includes_request_id(self):
        msg = mod.render_message(_fake_req())
        assert "abc123def4567890" in msg

    def test_includes_action_type(self):
        msg = mod.render_message(_fake_req(
            action_type="supplier_order_place",
        ))
        assert "supplier_order_place" in msg

    def test_includes_reply_instructions(self):
        msg = mod.render_message(_fake_req())
        assert "approve abc123def4567890" in msg
        assert "deny abc123def4567890" in msg

    def test_payload_rendered_as_json(self):
        msg = mod.render_message(_fake_req(
            payload={"daily_budget_usd": 20, "store": "deguar"},
        ))
        assert '"daily_budget_usd": 20' in msg
        assert '"store": "deguar"' in msg

    def test_giant_payload_truncated(self):
        big = {"key": "x" * 1000}
        msg = mod.render_message(_fake_req(payload=big))
        # Payload line should be capped at 300 chars
        payload_line = [l for l in msg.splitlines()
                        if "payload" in l.lower()][0]
        assert len(payload_line) < 400  # line wrapper + truncated
        assert "…" in payload_line

    def test_unserialisable_payload_falls_back(self):
        """A non-JSON-serialisable payload (e.g. a raw object)
        shouldn't crash — fall back to str()."""
        class NotJSON:
            def __repr__(self) -> str:
                return "<raw>"

        msg = mod.render_message(_fake_req(
            payload={"bad": NotJSON()},
        ))
        assert "payload" in msg.lower()


# ── ApprovalNotifier ───────────────────────────────────


class TestApprovalNotifier:
    def test_push_levels_default_to_high_critical(self):
        n = mod.ApprovalNotifier(lambda: None)
        assert n.should_push(_fake_req(RiskLevel.HIGH))
        assert n.should_push(_fake_req(RiskLevel.CRITICAL))
        assert not n.should_push(_fake_req(RiskLevel.MEDIUM))
        assert not n.should_push(_fake_req(RiskLevel.LOW))

    def test_notify_success(self):
        adapter = _FakeAdapter()
        n = mod.ApprovalNotifier(lambda: adapter)
        assert n.notify(_fake_req(RiskLevel.HIGH))
        assert len(adapter.calls) == 1

    def test_notify_low_skipped(self):
        adapter = _FakeAdapter()
        n = mod.ApprovalNotifier(lambda: adapter)
        assert not n.notify(_fake_req(RiskLevel.LOW))
        # Not even is_available is probed — level check short
        # circuits first.
        assert adapter.availability_checks == 0

    def test_adapter_unavailable_returns_false(self):
        adapter = _FakeAdapter(available=False)
        n = mod.ApprovalNotifier(lambda: adapter)
        assert not n.notify(_fake_req(RiskLevel.HIGH))
        assert adapter.calls == []

    def test_adapter_factory_returns_none(self):
        n = mod.ApprovalNotifier(lambda: None)
        assert not n.notify(_fake_req(RiskLevel.HIGH))

    def test_factory_raises_no_crash(self):
        def boom():
            raise RuntimeError("telegram_bot missing")
        n = mod.ApprovalNotifier(boom)
        # Must NOT propagate
        assert not n.notify(_fake_req(RiskLevel.HIGH))

    def test_send_raises_no_crash(self):
        adapter = MagicMock()
        adapter.is_available.return_value = True
        adapter.send_message.side_effect = RuntimeError("net fail")
        n = mod.ApprovalNotifier(lambda: adapter)
        assert not n.notify(_fake_req(RiskLevel.HIGH))

    def test_send_returns_none_is_failure(self):
        """send_message returns None when adapter declines (e.g.
        empty text) — treat as send failure."""
        adapter = _FakeAdapter(result=None)
        n = mod.ApprovalNotifier(lambda: adapter)
        assert not n.notify(_fake_req(RiskLevel.HIGH))

    def test_custom_push_levels(self):
        """Owner might want MEDIUM pushes too — constructor
        accepts override."""
        adapter = _FakeAdapter()
        n = mod.ApprovalNotifier(
            lambda: adapter,
            push_levels={RiskLevel.MEDIUM, RiskLevel.HIGH,
                         RiskLevel.CRITICAL},
        )
        assert n.notify(_fake_req(RiskLevel.MEDIUM))


# ── Queue hook integration ─────────────────────────────


class TestEnqueueHook:
    def test_hook_fires_on_enqueue(self, tmp_path):
        q = ApprovalQueue(db_path=str(tmp_path / "q.db"))
        captured: list[ApprovalRequest] = []
        q.on_enqueue(captured.append)
        q.enqueue("x", {}, RiskLevel.HIGH)
        assert len(captured) == 1
        assert captured[0].action_type == "x"

    def test_hook_error_does_not_block_enqueue(self, tmp_path):
        q = ApprovalQueue(db_path=str(tmp_path / "q.db"))

        def crash(req):
            raise RuntimeError("bad")
        q.on_enqueue(crash)
        # Must NOT propagate
        req = q.enqueue("x", {}, RiskLevel.HIGH)
        assert req.request_id
        # Row persisted
        assert q.get(req.request_id) is not None

    def test_multiple_hooks_all_called(self, tmp_path):
        q = ApprovalQueue(db_path=str(tmp_path / "q.db"))
        hook_a_calls = []
        hook_b_calls = []
        q.on_enqueue(hook_a_calls.append)
        q.on_enqueue(hook_b_calls.append)
        q.enqueue("x", {}, RiskLevel.HIGH)
        assert len(hook_a_calls) == 1
        assert len(hook_b_calls) == 1

    def test_notifier_wires_via_get_queue(self, tmp_path, monkeypatch):
        """Singleton get_queue() should auto-register a notifier.
        The default Telegram factory returns None when adapter
        isn't configured — end-to-end result is no crash, notify
        returns False."""
        reset_singleton_for_tests()
        mod.reset_singleton_for_tests()
        from core.system import approval_queue as aq
        monkeypatch.setattr(
            aq, "_DEFAULT_DB_PATH",
            str(tmp_path / "singleton.db"),
        )
        # First access triggers init + hook registration
        q = aq.get_queue()
        # Enqueue should complete cleanly even with the hook
        # that calls a possibly-missing Telegram adapter.
        req = q.enqueue("x", {}, RiskLevel.HIGH)
        assert req.request_id
        reset_singleton_for_tests()
        mod.reset_singleton_for_tests()

    def test_notifier_singleton_identity(self):
        mod.reset_singleton_for_tests()
        n1 = mod.get_notifier()
        n2 = mod.get_notifier()
        assert n1 is n2
        mod.reset_singleton_for_tests()
