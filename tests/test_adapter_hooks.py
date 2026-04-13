"""Tests for the autonomous controller's adapter-hook bridge.

These tests verify that ``run_post_cycle_hooks`` correctly routes
cycle data into the adapter layer — analytics events, CRM upserts,
helpdesk tickets, automation webhooks — without ever raising.

The tests stub the router's ``execute`` method rather than
registering real adapters, because we're testing the bridge, not
the adapters themselves (those have their own test files).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.adapters.base import AdapterResult, Capability
from core.autonomous.adapter_hooks import (
    create_helpdesk_ticket_for_errors,
    emit_analytics_events,
    run_post_cycle_hooks,
    sync_crm_contacts,
    trigger_automation_webhook,
)


def _ok(capability: str = "x") -> AdapterResult:
    return AdapterResult(
        ok=True, adapter="stub", capability=capability,
        data={"ok": True},
    )


def _fake_router(execute_result: AdapterResult | None = None):
    router = MagicMock()
    router.execute = MagicMock(return_value=execute_result or _ok())
    return router


@pytest.fixture
def cycle_result():
    return {
        "cycle_id": "cycle_1_100",
        "store_id": "shop-A",
        "duration_s": 1.5,
        "phase_error_count": 0,
        "status": "complete",
        "phases": {
            "data": {"products": 10, "orders": 3, "customers": 2},
            "analysis": {"insights": 4},
            "decisions": {"proposed": 2},
        },
    }


@pytest.fixture
def data():
    return {
        "order_data": [
            {"id": 1, "total_price": "99.99", "currency": "USD",
             "customer": {"id": 100}, "line_items": [{}]},
            {"id": 2, "total_price": "49.99", "currency": "USD",
             "customer": {"id": 101}, "line_items": [{}, {}]},
        ],
        "customer_data": [
            {"id": 100, "email": "a@example.com",
             "first_name": "Anne", "last_name": "A"},
            {"id": 101, "email": "b@example.com",
             "first_name": "Bob", "last_name": "B"},
            {"id": 102, "email": "a@example.com",  # duplicate
             "first_name": "Anne2", "last_name": "A"},
        ],
    }


class TestAnalyticsEvents:
    def test_emits_cycle_and_order_events(self, cycle_result, data):
        router = _fake_router()
        summary = emit_analytics_events(router, cycle_result, data)

        assert summary["cycle_event"]["ok"] is True
        assert summary["order_events"] == 2
        # 1 cycle event + 2 order events = 3 calls.
        assert router.execute.call_count == 3

        # First call should be the cycle event.
        first_cap, first_params = router.execute.call_args_list[0][0]
        assert first_cap == Capability.ANALYTICS_TRACK_EVENT
        assert first_params["event"] == "shopai_cycle_complete"
        assert first_params["distinct_id"] == "store:shop-A"

        # Subsequent calls should be order_placed events.
        second_params = router.execute.call_args_list[1][0][1]
        assert second_params["event"] == "order_placed"
        assert second_params["properties"]["total_price"] == "99.99"

    def test_handles_router_failure_silently(self, cycle_result, data):
        router = MagicMock()
        router.execute = MagicMock(side_effect=RuntimeError("boom"))

        summary = emit_analytics_events(router, cycle_result, data)
        # No crashes, events reported as not fired.
        assert summary["cycle_event"]["ok"] is False
        assert summary["order_events"] == 0

    def test_respects_order_cap(self, cycle_result, data, monkeypatch):
        monkeypatch.setenv("SHOPAI_ANALYTICS_ORDER_CAP", "1")
        router = _fake_router()
        summary = emit_analytics_events(router, cycle_result, data)
        # 1 cycle event + 1 order event capped = 2 calls.
        assert router.execute.call_count == 2
        assert summary["order_events"] == 1


class TestCrmSync:
    def test_upserts_unique_emails(self, data):
        router = _fake_router()
        result = sync_crm_contacts(router, data)
        # 2 unique emails (the 3rd is a duplicate).
        assert result["synced"] == 2
        assert result["skipped"] == 1

        call_caps = [c[0][0] for c in router.execute.call_args_list]
        assert all(c == Capability.CRM_UPSERT_CONTACT for c in call_caps)

    def test_no_customers(self):
        router = _fake_router()
        result = sync_crm_contacts(router, {"customer_data": []})
        assert result == {"synced": 0, "skipped": 0}
        router.execute.assert_not_called()

    def test_respects_sync_cap(self, data, monkeypatch):
        monkeypatch.setenv("SHOPAI_CRM_SYNC_CAP", "1")
        router = _fake_router()
        result = sync_crm_contacts(router, data)
        assert result["synced"] == 1

    def test_skips_customers_without_email(self):
        router = _fake_router()
        result = sync_crm_contacts(router, {"customer_data": [
            {"id": 1},  # no email
            {"id": 2, "email": ""},  # empty email
            {"id": 3, "email": "ok@example.com"},
        ]})
        assert result["synced"] == 1
        assert result["skipped"] == 2


class TestHelpdeskTicket:
    def test_no_ticket_when_no_errors(self, cycle_result):
        router = _fake_router()
        result = create_helpdesk_ticket_for_errors(router, cycle_result, {})
        assert result["created"] is False
        router.execute.assert_not_called()

    def test_no_ticket_below_threshold(self, cycle_result, monkeypatch):
        monkeypatch.setenv("SHOPAI_HELPDESK_ERROR_THRESHOLD", "5")
        router = _fake_router()
        result = create_helpdesk_ticket_for_errors(
            router, cycle_result,
            {"a": "err", "b": "err"},  # 2 < 5
        )
        assert result["created"] is False
        router.execute.assert_not_called()

    def test_creates_ticket_above_threshold(
        self, cycle_result, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_HELPDESK_ERROR_THRESHOLD", "2")
        router = _fake_router()
        errors = {"phase_a": "err1", "phase_b": "err2", "phase_c": "err3"}
        result = create_helpdesk_ticket_for_errors(
            router, cycle_result, errors,
        )
        assert result["created"] is True

        cap, params = router.execute.call_args[0]
        assert cap == Capability.HELPDESK_CREATE_TICKET
        assert "Cycle cycle_1_100 degraded" in params["subject"]
        assert "phase_a: err1" in params["body"]
        assert params["priority"] == "high"
        assert "shopai" in params["tags"]


class TestAutomationWebhook:
    def test_no_webhook_configured(self, cycle_result, monkeypatch):
        monkeypatch.delenv("SHOPAI_CYCLE_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("SHOPAI_CYCLE_WEBHOOK_PATH", raising=False)
        monkeypatch.delenv("SHOPAI_CYCLE_WORKFLOW_ID", raising=False)
        router = _fake_router()
        result = trigger_automation_webhook(router, cycle_result)
        assert result["triggered"] is False
        router.execute.assert_not_called()

    def test_webhook_url(self, cycle_result, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_CYCLE_WEBHOOK_URL", "https://n8n.test/hook/abc",
        )
        router = _fake_router()
        result = trigger_automation_webhook(router, cycle_result)
        assert result["triggered"] is True

        cap, params = router.execute.call_args[0]
        assert cap == Capability.AUTOMATION_TRIGGER
        assert params["webhook_url"] == "https://n8n.test/hook/abc"
        assert params["data"]["cycle_id"] == "cycle_1_100"

    def test_webhook_path(self, cycle_result, monkeypatch):
        monkeypatch.delenv("SHOPAI_CYCLE_WEBHOOK_URL", raising=False)
        monkeypatch.setenv("SHOPAI_CYCLE_WEBHOOK_PATH", "/cycle-done")
        router = _fake_router()
        result = trigger_automation_webhook(router, cycle_result)
        assert result["triggered"] is True
        params = router.execute.call_args[0][1]
        assert params["webhook_path"] == "/cycle-done"


class TestRunPostCycleHooks:
    def test_full_run(self, cycle_result, data, monkeypatch):
        monkeypatch.setenv("SHOPAI_CYCLE_WEBHOOK_URL", "https://n8n.test/x")
        router = _fake_router()
        summary = run_post_cycle_hooks(router, cycle_result, data, {})

        assert summary["enabled"] is True
        assert "analytics" in summary
        assert "crm" in summary
        assert "helpdesk" in summary
        assert "automation" in summary
        assert summary["analytics"]["order_events"] == 2
        assert summary["crm"]["synced"] == 2
        assert summary["helpdesk"]["created"] is False  # no errors
        assert summary["automation"]["triggered"] is True

    def test_disabled_by_env(self, cycle_result, data, monkeypatch):
        monkeypatch.setenv("SHOPAI_ADAPTER_HOOKS", "off")
        router = _fake_router()
        summary = run_post_cycle_hooks(router, cycle_result, data, {})
        assert summary == {"enabled": False}
        router.execute.assert_not_called()

    def test_no_router(self, cycle_result, data):
        summary = run_post_cycle_hooks(None, cycle_result, data, {})
        assert summary["enabled"] is False

    def test_one_hook_crash_doesnt_stop_others(
        self, cycle_result, data, monkeypatch,
    ):
        # Make analytics raise, everything else should still run.
        router = MagicMock()
        calls = {"n": 0}

        def _execute(cap, params):
            calls["n"] += 1
            if cap == Capability.ANALYTICS_TRACK_EVENT:
                raise RuntimeError("analytics down")
            return _ok()

        router.execute = _execute
        summary = run_post_cycle_hooks(router, cycle_result, data, {})
        # CRM should still have run.
        assert summary["crm"]["synced"] == 2
