"""Tests for the catalog_quality_autonomy domain (Wave 476+).

9th autonomy domain. Verifies the 5-piece template surface +
applier safety gates + autonomy_status rollup integration.
"""
from __future__ import annotations

from engines.catalog_quality_autonomy.quality_applier import (
    apply_catalog_quality,
)
from engines.catalog_quality_autonomy.quality_health import (
    analyze_catalog_quality_health,
)
from engines.catalog_quality_autonomy.quality_log import (
    log_size,
    recent_events,
)
from engines.catalog_quality_autonomy.quality_state import (
    is_paused,
)
from engines.catalog_quality_autonomy.quality_status import (
    get_catalog_quality_status,
)


class TestTemplateImports:

    def test_log_exports(self):
        assert callable(log_size)
        assert callable(recent_events)

    def test_state_exports(self):
        assert callable(is_paused)
        assert isinstance(is_paused(), bool)

    def test_health_exports(self):
        assert callable(analyze_catalog_quality_health)
        r = analyze_catalog_quality_health()
        assert hasattr(r, "verdict")
        assert hasattr(r, "failure_ratio")

    def test_applier_exports(self):
        assert callable(apply_catalog_quality)

    def test_status_exports(self):
        assert callable(get_catalog_quality_status)
        r = get_catalog_quality_status()
        assert hasattr(r, "verdict")
        assert hasattr(r, "applied_count")


class TestApplierEmptyShortCircuit:

    def test_empty_list_returns_empty(self):
        assert apply_catalog_quality([]) == []

    def test_none_returns_empty(self):
        assert apply_catalog_quality(None) == []

    def test_non_list_returns_empty(self):
        assert apply_catalog_quality("not a list") == []


class TestApplierSafetyGates:

    def test_not_actionable_action(self):
        out = apply_catalog_quality([{
            "product_id": "P1",
            "tag": "shopai-quality-needs-images",
            "action": "wrong_action",
        }])
        assert len(out) == 1
        assert out[0]["status"] == "not_actionable"
        assert not out[0]["applied"]

    def test_missing_product_id(self):
        out = apply_catalog_quality([{
            "product_id": "",
            "tag": "shopai-quality-needs-images",
            "action": "tag_quality",
        }])
        assert out[0]["status"] == "missing_ids"

    def test_missing_tag(self):
        out = apply_catalog_quality([{
            "product_id": "P1",
            "tag": "",
            "action": "tag_quality",
        }])
        assert out[0]["status"] == "missing_ids"

    def test_invalid_tag_blocked(self):
        out = apply_catalog_quality([{
            "product_id": "P1",
            "tag": "shopai-quality-INVALID",
            "action": "tag_quality",
        }])
        assert out[0]["status"] == "invalid_tag"
        assert "INVALID" in (out[0]["error"] or "")

    def test_valid_tag_attempted(self):
        out = apply_catalog_quality([{
            "product_id": "P1",
            "tag": "shopai-quality-needs-images",
            "action": "tag_quality",
        }])
        # Either router_unavailable or adapter_failed
        assert out[0]["status"] in {
            "router_unavailable", "adapter_failed",
            "recorded",
        }

    def test_all_5_taxonomy_tags_accepted(self):
        for tag in [
            "shopai-quality-needs-images",
            "shopai-quality-thin-description",
            "shopai-quality-no-variants",
            "shopai-quality-validated",
            "shopai-quality-flagged-review",
        ]:
            out = apply_catalog_quality([{
                "product_id": "P1",
                "tag": tag,
                "action": "tag_quality",
            }])
            # Valid tag should not fail invalid_tag gate
            assert out[0]["status"] != "invalid_tag"


class TestStatusSurface:

    def test_quiet_when_idle(self):
        r = get_catalog_quality_status()
        assert r.verdict in {"quiet", "healthy"}
        assert r.applied_count == 0

    def test_status_carries_window(self):
        r = get_catalog_quality_status(window_hours=72.0)
        assert r.window_hours == 72.0

    def test_status_carries_store_id(self):
        r = get_catalog_quality_status(store_id="store-q")
        assert r.store_id == "store-q"


class TestAutonomyStatusIntegration:

    def test_appears_in_rollup(self):
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        rollup = get_autonomy_status()
        names = {d.name for d in rollup.domains}
        assert "catalog_quality" in names

    def test_all_domains_total(self):
        # W937: roster grew to 10 (shipping_alert)
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        rollup = get_autonomy_status()
        assert len(rollup.domains) >= 9
