"""Tests for Phase 12.A fulfillment autonomy (W126-131).

Validates that the thin wrappers (fulfillment_log /
fulfillment_state / fulfillment_health) correctly delegate to
core/automation/* + the domain-specific router applies behind
the same safety gates.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.fulfillment_autonomy.fulfillment_log import (
    FulfillmentEvent,
)
from engines.fulfillment_autonomy.fulfillment_applier import (
    apply_fulfillment_routes,
)


def _ok(data=None):
    return SimpleNamespace(
        ok=True, data=data or {"fulfillment_id": "gid://F1"},
        error=None,
    )


def _fail(error="no adapter"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestFulfillmentRouterSafety:
    """Safety gates fire in correct order."""

    def test_paused_skips_every_row(self):
        with patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "is_paused",
            return_value=True,
        ):
            out = apply_fulfillment_routes([
                {
                    "order_id": "o1", "location_id": "l1",
                    "store_id": "s1", "action": "route",
                },
            ])
        assert out[0]["status"] == "paused"
        assert out[0]["applied"] is False

    def test_not_route_action_skipped(self):
        with patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_fulfillment_routes([
                {"order_id": "o1", "action": "hold"},
            ])
        assert out[0]["status"] == "not_actionable"

    def test_missing_ids_skipped(self):
        with patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_fulfillment_routes([
                {"order_id": "o1", "action": "route"},
                {"location_id": "l1", "action": "route"},
            ])
        assert out[0]["status"] == "missing_ids"
        assert out[1]["status"] == "missing_ids"

    def test_router_unavailable(self):
        with patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "is_paused",
            return_value=False,
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "_get_router",
            return_value=None,
        ):
            out = apply_fulfillment_routes([
                {
                    "order_id": "o1", "location_id": "l1",
                    "action": "route",
                },
            ])
        assert out[0]["status"] == "router_unavailable"

    def test_happy_path_route(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = _ok()
        with patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "is_paused",
            return_value=False,
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "_capability",
            return_value=object(),
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "record_writeback",
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "record_fulfillment_event",
        ):
            out = apply_fulfillment_routes([
                {
                    "order_id": "o1", "location_id": "l1",
                    "store_id": "s1", "action": "route",
                },
            ])
        assert out[0]["applied"] is True
        assert out[0]["status"] == "recorded"

    def test_adapter_failure_coerces_to_str(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = SimpleNamespace(
            ok=False, error=Exception("weird"),
        )
        with patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "is_paused",
            return_value=False,
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_applier."
            "_capability",
            return_value=object(),
        ):
            out = apply_fulfillment_routes([
                {
                    "order_id": "o1", "location_id": "l1",
                    "action": "route",
                },
            ])
        assert out[0]["status"] == "adapter_failed"
        assert isinstance(out[0]["error"], str)


class TestFulfillmentSubstrateWrappers:
    """The thin wrappers correctly route through core/automation/*"""

    def test_log_event_dataclass_shape(self):
        event = FulfillmentEvent(
            order_id="o1", location_id="l1",
            applied=True, status="recorded",
        )
        assert event.order_id == "o1"
        assert event.location_id == "l1"
        assert event.recorded_at > 0  # auto-defaulted

    def test_state_module_imports_cleanly(self):
        from engines.fulfillment_autonomy.fulfillment_state import (
            get_state, is_paused, pause, resume,
        )
        # Pattern J guard keeps these no-op under pytest
        assert callable(get_state)
        assert callable(is_paused)
        assert callable(pause)
        assert callable(resume)

    def test_health_uses_FULFILLMENT_env_prefix(
        self, monkeypatch,
    ):
        """Setting SHOPAI_FULFILLMENT_HEALTH_MIN_SAMPLE=99
        should drive the threshold for fulfillment but NOT
        leak into refund or budget."""
        monkeypatch.setenv(
            "SHOPAI_FULFILLMENT_HEALTH_MIN_SAMPLE", "99",
        )
        from engines.fulfillment_autonomy.fulfillment_health import (
            analyze_fulfillment_health,
        )
        with patch(
            "engines.fulfillment_autonomy.fulfillment_log."
            "recent_events",
            return_value=[
                {
                    "applied": False,
                    "status": "adapter_failed",
                    "recorded_at": __import__("time").time(),
                }
                for _ in range(10)
            ],
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_state."
            "is_paused",
            return_value=False,
        ):
            r = analyze_fulfillment_health()
        # 10 < 99 min_sample -> healthy
        assert r.verdict == "healthy"
        assert "insufficient data" in r.reasons[0]


class TestFulfillmentNotifyIntegration:
    """Wave 130 notify alert kinds."""

    def test_fulfillment_paused_alert(self):
        from engines._notify import collect_alerts
        from core.automation.pause_state import PauseState
        from engines.returns_management.refund_state import (
            RefundPauseState,
        )
        from engines.returns_management.refund_health import (
            RefundHealthReport,
        )
        from engines.roas_guardrails.budget_state import (
            BudgetPauseState,
        )
        with patch(
            "engines.returns_management.refund_state.get_state",
            return_value=RefundPauseState(),
        ), patch(
            "engines.returns_management.refund_health."
            "analyze_refund_health",
            return_value=RefundHealthReport(
                window_hours=24.0, verdict="healthy",
            ),
        ), patch(
            "engines.roas_guardrails.budget_state.get_state",
            return_value=BudgetPauseState(),
        ), patch(
            "engines.roas_guardrails.budget_health."
            "analyze_budget_health",
            return_value=SimpleNamespace(
                verdict="healthy", failure_ratio=0.0,
                sample_size=0,
            ),
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_state."
            "get_state",
            return_value=PauseState(
                paused=True, reason="threshold",
            ),
        ), patch(
            "engines.fulfillment_autonomy.fulfillment_health."
            "analyze_fulfillment_health",
            return_value=SimpleNamespace(
                verdict="healthy", failure_ratio=0.0,
                sample_size=0,
            ),
        ):
            alerts = collect_alerts()
        kinds = {a.kind for a in alerts}
        assert "fulfillment_paused" in kinds
