"""Tests for engines._go_live_check."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from engines._go_live_check import (
    CheckResult,
    run_go_live_check,
    summarize,
)


class TestSummarize:

    def test_all_pass_ready(self):
        checks = [
            CheckResult(name=f"c{i}", status="pass", detail="")
            for i in range(3)
        ]
        s = summarize(checks)
        assert s["verdict"] == "ready_to_go_live"
        assert s["pass"] == 3
        assert s["fail"] == 0

    def test_any_fail_not_ready(self):
        checks = [
            CheckResult(name="c1", status="pass", detail=""),
            CheckResult(name="c2", status="fail", detail=""),
        ]
        s = summarize(checks)
        assert s["verdict"] == "not_ready"
        assert s["fail"] == 1

    def test_warns_alone_still_ready(self):
        """Warns are advisory; ready_to_go_live as long as no
        fails."""
        checks = [
            CheckResult(name="c1", status="pass", detail=""),
            CheckResult(name="c2", status="warn", detail=""),
            CheckResult(name="c3", status="warn", detail=""),
        ]
        s = summarize(checks)
        assert s["verdict"] == "ready_to_go_live"
        assert s["warn"] == 2


class TestRunCheckShape:
    """The aggregate returns 8 CheckResult objects with the
    expected name set."""

    def test_returns_check_results(self):
        checks = run_go_live_check()
        assert all(isinstance(c, CheckResult) for c in checks)

    def test_all_expected_names_present(self):
        checks = run_go_live_check()
        names = {c.name for c in checks}
        assert "shopify_credentials" in names
        assert "wired_engines" in names
        assert "institutional_audits" in names
        assert "cycle_history" in names
        assert "spend_cap" in names
        assert "revenue_quarantine" in names
        assert "notify_webhook" in names
        assert "ai_strategy" in names
        assert "store_niches" in names  # Wave 76

    def test_each_check_has_valid_status(self):
        checks = run_go_live_check()
        for c in checks:
            assert c.status in ("pass", "warn", "fail")


class TestSpendCapCheck:

    def test_warn_when_no_caps_set(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_SPEND_CAP_DAILY_USD", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_SPEND_CAP_WEEKLY_USD", raising=False,
        )
        from engines._go_live_check import _check_spend_cap_configured
        r = _check_spend_cap_configured()
        assert r.status == "warn"

    def test_warn_when_caps_but_bridge_off(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SPEND_CAP_DAILY_USD", "50",
        )
        monkeypatch.delenv(
            "SHOPAI_AUTO_PAUSE_ON_OVERSPEND", raising=False,
        )
        from engines._go_live_check import _check_spend_cap_configured
        r = _check_spend_cap_configured()
        assert r.status == "warn"
        assert "bridge disabled" in r.detail.lower()

    def test_pass_when_caps_and_bridge_on(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_SPEND_CAP_DAILY_USD", "50",
        )
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_ON_OVERSPEND", "1",
        )
        from engines._go_live_check import _check_spend_cap_configured
        r = _check_spend_cap_configured()
        assert r.status == "pass"


class TestNotifyWebhookCheck:

    def test_warn_when_unset(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_NOTIFY_WEBHOOK_URL", raising=False,
        )
        from engines._go_live_check import _check_notify_webhook
        r = _check_notify_webhook()
        assert r.status == "warn"

    def test_pass_when_set(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_NOTIFY_WEBHOOK_URL",
            "https://hooks.slack.com/...",
        )
        from engines._go_live_check import _check_notify_webhook
        r = _check_notify_webhook()
        assert r.status == "pass"


class TestStoreNichesCheck:

    def test_pass_when_all_tagged(self):
        from unittest.mock import patch
        from engines._go_live_check import _check_store_niches
        fake_stores = [
            {"store_id": "a", "niche": "beauty"},
            {"store_id": "b", "niche": "tech"},
        ]
        with patch(
            "data_pipeline.store.store_manager.StoreManager"
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = (
                fake_stores
            )
            r = _check_store_niches()
        assert r.status == "pass"

    def test_warn_when_untagged_present(self):
        from unittest.mock import patch
        from engines._go_live_check import _check_store_niches
        fake_stores = [
            {"store_id": "a", "niche": "beauty"},
            {"store_id": "b", "niche": ""},
            {"store_id": "c", "niche": "general"},
        ]
        with patch(
            "data_pipeline.store.store_manager.StoreManager"
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = (
                fake_stores
            )
            r = _check_store_niches()
        assert r.status == "warn"
        # b and c are untagged
        assert "2" in r.detail


class TestAIStrategyCheck:

    def test_warn_all_off(self, monkeypatch):
        for var in (
            "SHOPAI_AI_STRATEGY", "SHOPAI_AI_PREVET",
            "SHOPAI_REVENUE_AWARE_ORCHESTRATOR",
            "SHOPAI_REVENUE_AWARE_CAPTAIN",
        ):
            monkeypatch.delenv(var, raising=False)
        from engines._go_live_check import _check_ai_strategy
        r = _check_ai_strategy()
        assert r.status == "warn"

    def test_pass_when_any_set(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")
        from engines._go_live_check import _check_ai_strategy
        r = _check_ai_strategy()
        assert r.status == "pass"
