"""Tests for Phase 14.A discount cleanup autonomy (W154-159)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.discount_cleanup_autonomy.cleanup_applier import (
    apply_discount_cleanup,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(error="no adapter"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestCleanupApplierSafety:

    def test_paused_skips(self):
        with patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "is_paused",
            return_value=True,
        ):
            out = apply_discount_cleanup([
                {
                    "discount_id": "d1", "code": "PROMO10",
                    "action": "deactivate", "age_days": 60,
                },
            ])
        assert out[0]["status"] == "paused"

    def test_not_actionable_skipped(self):
        with patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_discount_cleanup([
                {"discount_id": "d1", "action": "tweak"},
            ])
        assert out[0]["status"] == "not_actionable"

    def test_missing_ids_skipped(self):
        with patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_discount_cleanup([
                {"discount_id": "", "action": "deactivate"},
                {"code": "X", "action": "deactivate"},
            ])
        for r in out:
            assert r["status"] == "missing_ids"

    def test_too_young_skipped(self):
        with patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_discount_cleanup([
                {
                    "discount_id": "d1", "code": "X",
                    "action": "deactivate", "age_days": 5,
                },
            ], min_age_days=30)
        assert out[0]["status"] == "too_young"

    def test_per_run_cap(self):
        """6th candidate skipped when max_per_run=5."""
        fake_router = MagicMock()
        fake_router.execute.return_value = _ok()
        with patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "is_paused",
            return_value=False,
        ), patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "_capability",
            return_value=object(),
        ), patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "record_writeback",
        ), patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "record_cleanup_event",
        ):
            candidates = [
                {
                    "discount_id": f"d{i}", "code": f"C{i}",
                    "action": "deactivate", "age_days": 60,
                }
                for i in range(7)
            ]
            out = apply_discount_cleanup(
                candidates, max_per_run=5,
            )
        applied = [r for r in out if r["applied"]]
        skipped = [
            r for r in out
            if r["status"] == "exceeds_per_run_cap"
        ]
        assert len(applied) == 5
        assert len(skipped) == 2

    def test_happy_path(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = _ok()
        with patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "is_paused",
            return_value=False,
        ), patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "_capability",
            return_value=object(),
        ), patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "record_writeback",
        ), patch(
            "engines.discount_cleanup_autonomy.cleanup_applier."
            "record_cleanup_event",
        ):
            out = apply_discount_cleanup([
                {
                    "discount_id": "d1", "code": "X",
                    "store_id": "s1",
                    "action": "deactivate", "age_days": 60,
                    "reason": "expired",
                },
            ])
        assert out[0]["applied"] is True
        assert out[0]["status"] == "recorded"


class TestAutonomyStatusFiveDomains:
    """get_autonomy_status now rolls up >=5 domains.

    W937 convention: roster grows over time (Phase 18-35 added
    product_seo, customer_outreach, order_followup, shipping_
    alert, catalog_quality). Original five must remain present;
    superset additions are allowed.
    """

    def test_includes_discount_cleanup_domain(self):
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        report = get_autonomy_status()
        names = {d.name for d in report.domains}
        expected = {
            "customer_support", "marketing",
            "fulfillment", "inventory",
            "discount_cleanup",
        }
        assert expected.issubset(names)
        assert len(names) >= 5
