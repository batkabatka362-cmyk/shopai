"""Tests for Phase 18.A product SEO autonomy (W195-202)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.product_seo_autonomy.seo_applier import (
    apply_seo_updates,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


class TestSEOApplier:

    def test_paused_skips(self):
        with patch(
            "engines.product_seo_autonomy.seo_applier."
            "is_paused",
            return_value=True,
        ):
            out = apply_seo_updates([
                {
                    "product_id": "p1",
                    "action": "update_seo",
                    "field": "meta_description",
                    "new_value": "some description",
                },
            ])
        assert out[0]["status"] == "paused"

    def test_not_actionable(self):
        with patch(
            "engines.product_seo_autonomy.seo_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_seo_updates([
                {"product_id": "p1", "action": "browse"},
            ])
        assert out[0]["status"] == "not_actionable"

    def test_invalid_field(self):
        with patch(
            "engines.product_seo_autonomy.seo_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_seo_updates([
                {
                    "product_id": "p1",
                    "action": "update_seo",
                    "field": "some_other_field",
                    "new_value": "x",
                },
            ])
        assert out[0]["status"] == "invalid_field"

    def test_exceeds_max_length(self):
        with patch(
            "engines.product_seo_autonomy.seo_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_seo_updates([
                {
                    "product_id": "p1",
                    "action": "update_seo",
                    "field": "meta_description",
                    "new_value": "x" * 500,
                },
            ], max_length=320)
        assert out[0]["status"] == "exceeds_max_length"

    def test_happy_path(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = _ok()
        with patch(
            "engines.product_seo_autonomy.seo_applier."
            "is_paused",
            return_value=False,
        ), patch(
            "engines.product_seo_autonomy.seo_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.product_seo_autonomy.seo_applier."
            "_capability",
            return_value=object(),
        ), patch(
            "engines.product_seo_autonomy.seo_applier."
            "record_writeback",
        ), patch(
            "engines.product_seo_autonomy.seo_applier."
            "record_seo_event",
        ):
            out = apply_seo_updates([
                {
                    "product_id": "p1",
                    "store_id": "s1",
                    "action": "update_seo",
                    "field": "meta_description",
                    "new_value": "Quality product, ships fast.",
                },
            ])
        assert out[0]["applied"] is True
        assert out[0]["status"] == "recorded"


class TestAutonomyStatusSevenDomains:

    def test_includes_product_seo_domain(self):
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        report = get_autonomy_status()
        names = {d.name for d in report.domains}
        assert "product_seo" in names
        assert len(names) == 7
