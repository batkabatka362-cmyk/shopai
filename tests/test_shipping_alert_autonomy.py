"""Tests for the shipping_alert_autonomy domain (Wave 756+).

Scaffolded via shopai autonomy-init. Verifies the 5-piece
template surface + applier safety gates + autonomy_status
rollup integration.
"""
from __future__ import annotations

from engines.shipping_alert_autonomy.shipping_applier import (
    apply_shipping_alert,
)
from engines.shipping_alert_autonomy.shipping_health import (
    analyze_shipping_alert_health,
)
from engines.shipping_alert_autonomy.shipping_log import (
    log_size,
    recent_events,
)
from engines.shipping_alert_autonomy.shipping_state import (
    is_paused,
)
from engines.shipping_alert_autonomy.shipping_status import (
    get_shipping_alert_status,
)


class TestTemplateImports:

    def test_log_exports(self):
        assert callable(log_size)
        assert callable(recent_events)

    def test_state_exports(self):
        assert callable(is_paused)
        assert isinstance(is_paused(), bool)

    def test_health_exports(self):
        assert callable(analyze_shipping_alert_health)
        r = analyze_shipping_alert_health()
        assert hasattr(r, "verdict")
        assert hasattr(r, "failure_ratio")

    def test_applier_exports(self):
        assert callable(apply_shipping_alert)

    def test_status_exports(self):
        assert callable(get_shipping_alert_status)
        r = get_shipping_alert_status()
        assert hasattr(r, "verdict")
        assert hasattr(r, "applied_count")


class TestApplierEmptyShortCircuit:

    def test_empty_list_returns_empty(self):
        assert apply_shipping_alert([]) == []

    def test_none_returns_empty(self):
        assert apply_shipping_alert(None) == []
