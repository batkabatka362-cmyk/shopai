"""Tests for Phase 11.B marketing autonomy substrate.

Covers Wave 110 (ad_spend_log), 111 (budget_state +
budget_health), 112 (budget_applier), 113 (marketing_status),
115 (notify integration).
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from engines.roas_guardrails.ad_spend_log import (
    AdSpendEvent,
    record_ad_spend_event,
    recent_events,
)
from engines.roas_guardrails.budget_state import (
    BudgetPauseState,
    get_state,
    is_paused,
    pause,
    resume,
)
from engines.roas_guardrails.budget_health import (
    analyze_budget_health,
    maybe_auto_pause_budget,
)
from engines.roas_guardrails.budget_applier import (
    apply_budget_changes,
)
from engines.roas_guardrails.marketing_status import (
    get_marketing_status,
)


# ─── Wave 110: ad_spend_log ──────────────────────────────


class TestAdSpendLog:

    def test_record_no_op_under_pytest(self):
        with patch(
            "engines.roas_guardrails.ad_spend_log._save",
        ) as save_mock:
            record_ad_spend_event(AdSpendEvent(
                campaign_id="c1", action="cut",
                prior_budget=100.0, new_budget=50.0,
                applied=True, status="recorded",
            ))
        save_mock.assert_not_called()

    def test_recent_events_filters_by_window(self):
        now = time.time()
        rows = [
            {"campaign_id": "c1", "recorded_at": now - 3600},
            {"campaign_id": "c2", "recorded_at": now - 36000},
        ]
        with patch(
            "engines.roas_guardrails.ad_spend_log._load",
            return_value=rows,
        ):
            out = recent_events(window_hours=4.0)
        assert len(out) == 1
        assert out[0]["campaign_id"] == "c1"

    def test_recent_events_filters_by_store_and_network(self):
        now = time.time()
        rows = [
            {
                "campaign_id": "c1", "store_id": "a",
                "network": "meta", "recorded_at": now,
            },
            {
                "campaign_id": "c2", "store_id": "b",
                "network": "meta", "recorded_at": now,
            },
            {
                "campaign_id": "c3", "store_id": "a",
                "network": "google", "recorded_at": now,
            },
        ]
        with patch(
            "engines.roas_guardrails.ad_spend_log._load",
            return_value=rows,
        ):
            out = recent_events(
                store_id="a", network="meta",
            )
        assert len(out) == 1
        assert out[0]["campaign_id"] == "c1"


# ─── Wave 111: budget_state ──────────────────────────────


class TestBudgetState:

    def test_pause_then_resume(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "engines.roas_guardrails.budget_state."
            "_is_test_environment",
            lambda: False,
        )
        fake_path = tmp_path / "budget_state.json"
        monkeypatch.setattr(
            "engines.roas_guardrails.budget_state._STATE_PATH",
            fake_path,
        )
        state = pause(reason="threshold")
        assert state.paused is True
        assert is_paused() is True
        state2 = resume()
        assert state2.paused is False

    def test_auto_resume_after_deadline(
        self, monkeypatch, tmp_path,
    ):
        monkeypatch.setattr(
            "engines.roas_guardrails.budget_state."
            "_is_test_environment",
            lambda: False,
        )
        fake_path = tmp_path / "budget_state.json"
        monkeypatch.setattr(
            "engines.roas_guardrails.budget_state._STATE_PATH",
            fake_path,
        )
        pause(
            reason="test",
            auto_resume_after=time.time() - 60,
        )
        state = get_state()
        assert state.paused is False


# ─── Wave 111: budget_health ─────────────────────────────


def _event(*, applied=True, status="recorded"):
    return {
        "campaign_id": "c", "applied": applied,
        "status": status, "recorded_at": time.time(),
    }


class TestBudgetHealth:

    def _stub_events(self, rows):
        return patch(
            "engines.roas_guardrails.budget_health."
            "recent_events",
            return_value=rows,
        )

    def test_small_sample_healthy(self):
        with self._stub_events(
            [_event(applied=False, status="adapter_failed")],
        ), patch(
            "engines.roas_guardrails.budget_health.is_paused",
            return_value=False,
        ):
            r = analyze_budget_health()
        assert r.verdict == "healthy"
        assert "insufficient data" in r.reasons[0]

    def test_high_ratio_critical(self):
        rows = [
            _event(applied=False, status="adapter_failed")
            for _ in range(8)
        ]
        with self._stub_events(rows), patch(
            "engines.roas_guardrails.budget_health.is_paused",
            return_value=False,
        ):
            r = analyze_budget_health()
        assert r.verdict == "critical"

    def test_bridge_off_by_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_PAUSE_BUDGET_ON_FAILURE",
            raising=False,
        )
        rows = [
            _event(applied=False, status="adapter_failed")
            for _ in range(8)
        ]
        with self._stub_events(rows), patch(
            "engines.roas_guardrails.budget_health.is_paused",
            return_value=False,
        ), patch(
            "engines.roas_guardrails.budget_health.pause",
        ) as pause_mock:
            r = maybe_auto_pause_budget()
        assert r.verdict == "critical"
        assert r.bridge_fired is False
        pause_mock.assert_not_called()

    def test_bridge_fires_when_gated(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_BUDGET_ON_FAILURE", "1",
        )
        rows = [
            _event(applied=False, status="adapter_failed")
            for _ in range(8)
        ]
        with self._stub_events(rows), patch(
            "engines.roas_guardrails.budget_health.is_paused",
            return_value=False,
        ), patch(
            "engines.roas_guardrails.budget_health.pause",
        ) as pause_mock:
            r = maybe_auto_pause_budget()
        assert r.bridge_fired is True
        pause_mock.assert_called_once()


# ─── Wave 112: budget_applier ────────────────────────────


class TestBudgetApplier:

    def test_paused_skips_every_row(self):
        with patch(
            "engines.roas_guardrails.budget_applier."
            "is_paused", return_value=True,
        ):
            out = apply_budget_changes([
                {
                    "campaign_id": "c1", "action": "cut",
                    "prior_budget": 100.0,
                    "proposed_budget": 50.0,
                },
            ])
        assert out[0]["status"] == "paused"
        assert out[0]["applied"] is False

    def test_not_actionable_skipped(self):
        out = apply_budget_changes([
            {"campaign_id": "c1", "action": "tweak"},
        ])
        assert out[0]["status"] == "not_actionable"

    def test_exceeds_max_delta(self):
        with patch(
            "engines.roas_guardrails.budget_applier."
            "is_paused", return_value=False,
        ), patch(
            "engines.roas_guardrails.budget_applier."
            "_get_router",
            return_value=MagicMock(),
        ), patch(
            "engines.roas_guardrails.budget_applier."
            "_capability",
            return_value=object(),
        ):
            out = apply_budget_changes([
                {
                    "campaign_id": "c1", "action": "cut",
                    "prior_budget": 1000.0,
                    "proposed_budget": 0.0,  # delta = $1000
                },
            ], max_delta=200.0)
        assert out[0]["status"] == "exceeds_max_delta"
        assert "1000" in out[0]["error"]

    def test_router_unavailable(self):
        with patch(
            "engines.roas_guardrails.budget_applier."
            "is_paused", return_value=False,
        ), patch(
            "engines.roas_guardrails.budget_applier."
            "_get_router", return_value=None,
        ):
            out = apply_budget_changes([
                {
                    "campaign_id": "c1", "action": "cut",
                    "prior_budget": 100.0,
                    "proposed_budget": 50.0,
                },
            ])
        assert out[0]["status"] == "router_unavailable"

    def test_happy_path_cut(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = SimpleNamespace(
            ok=True, data={}, error=None,
        )
        with patch(
            "engines.roas_guardrails.budget_applier."
            "is_paused", return_value=False,
        ), patch(
            "engines.roas_guardrails.budget_applier."
            "_get_router", return_value=fake_router,
        ), patch(
            "engines.roas_guardrails.budget_applier."
            "_capability", return_value=object(),
        ), patch(
            "engines.roas_guardrails.budget_applier."
            "record_writeback",
        ), patch(
            "engines.roas_guardrails.budget_applier."
            "record_ad_spend_event",
        ):
            out = apply_budget_changes([
                {
                    "campaign_id": "c1", "action": "cut",
                    "prior_budget": 100.0,
                    "proposed_budget": 50.0,
                },
            ])
        assert out[0]["applied"] is True
        assert out[0]["status"] == "recorded"


# ─── Wave 113: marketing_status ──────────────────────────


class TestMarketingStatus:

    def _patches(self, *, rows=None, health_verdict="healthy",
                 paused=False):
        rows = rows or []
        return [
            patch(
                "engines.roas_guardrails.marketing_status."
                "recent_events",
                return_value=rows,
            ),
            patch(
                "engines.roas_guardrails.marketing_status."
                "analyze_budget_health",
                return_value=SimpleNamespace(
                    verdict=health_verdict,
                    failure_ratio=0.0,
                ),
            ),
            patch(
                "engines.roas_guardrails.marketing_status."
                "get_state",
                return_value=BudgetPauseState(paused=paused),
            ),
        ]

    def _apply(self, patches, fn):
        entered = [p.__enter__() for p in patches]
        try:
            return fn()
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    def test_paused_verdict(self):
        report = self._apply(
            self._patches(paused=True),
            lambda: get_marketing_status(),
        )
        assert report.verdict == "paused"

    def test_critical_health_degraded(self):
        report = self._apply(
            self._patches(health_verdict="critical"),
            lambda: get_marketing_status(),
        )
        assert report.verdict == "degraded"

    def test_quiet_when_no_events(self):
        report = self._apply(
            self._patches(),
            lambda: get_marketing_status(),
        )
        assert report.verdict == "quiet"

    def test_healthy_when_activity_present(self):
        rows = [
            {
                "campaign_id": "c1", "applied": True,
                "action": "cut", "status": "recorded",
                "recorded_at": time.time(),
            },
        ]
        report = self._apply(
            self._patches(rows=rows),
            lambda: get_marketing_status(),
        )
        assert report.verdict == "healthy"
        assert report.cuts_count == 1


# ─── Wave 115: notify integration ────────────────────────


class TestBudgetNotifyAlerts:

    def test_budget_paused_alert(self):
        from engines._notify import collect_alerts
        from engines.returns_management.refund_state import (
            RefundPauseState,
        )
        from engines.returns_management.refund_health import (
            RefundHealthReport,
        )
        with patch(
            "engines.roas_guardrails.budget_state.get_state",
            return_value=BudgetPauseState(
                paused=True, reason="threshold",
            ),
        ), patch(
            "engines.roas_guardrails.budget_health."
            "analyze_budget_health",
            return_value=SimpleNamespace(
                verdict="healthy", failure_ratio=0.0,
                sample_size=0,
            ),
        ), patch(
            "engines.returns_management.refund_state.get_state",
            return_value=RefundPauseState(),
        ), patch(
            "engines.returns_management.refund_health."
            "analyze_refund_health",
            return_value=RefundHealthReport(
                window_hours=24.0, verdict="healthy",
            ),
        ):
            alerts = collect_alerts()
        kinds = {a.kind for a in alerts}
        assert "budget_paused" in kinds
