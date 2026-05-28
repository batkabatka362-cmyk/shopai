"""Tests for Phase 15 order followup autonomy (W174-180)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.order_followup_autonomy.followup_applier import (
    apply_order_followups,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(error="no adapter"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestFollowupApplier:

    def test_paused_skips(self):
        with patch(
            "engines.order_followup_autonomy.followup_applier."
            "is_paused",
            return_value=True,
        ):
            out = apply_order_followups([
                {
                    "order_id": "o1",
                    "action": "tag_followup",
                    "tag": "shopai-followup-thank-you-sent",
                },
            ])
        assert out[0]["status"] == "paused"

    def test_not_actionable(self):
        with patch(
            "engines.order_followup_autonomy.followup_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_order_followups([
                {"order_id": "o1", "action": "browse"},
            ])
        assert out[0]["status"] == "not_actionable"

    def test_missing_ids(self):
        with patch(
            "engines.order_followup_autonomy.followup_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_order_followups([
                {
                    "order_id": "", "action": "tag_followup",
                    "tag": "shopai-followup-pending-review",
                },
                {
                    "order_id": "o1",
                    "action": "tag_followup",
                    "tag": "",
                },
            ])
        for r in out:
            assert r["status"] == "missing_ids"

    def test_invalid_tag_rejected(self):
        with patch(
            "engines.order_followup_autonomy.followup_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_order_followups([
                {
                    "order_id": "o1",
                    "action": "tag_followup",
                    "tag": "arbitrary-typo-tag",
                },
            ])
        assert out[0]["status"] == "invalid_tag"
        assert "not in curated taxonomy" in out[0]["error"]

    def test_happy_path(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = _ok()
        with patch(
            "engines.order_followup_autonomy.followup_applier."
            "is_paused",
            return_value=False,
        ), patch(
            "engines.order_followup_autonomy.followup_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.order_followup_autonomy.followup_applier."
            "_capability",
            return_value=object(),
        ), patch(
            "engines.order_followup_autonomy.followup_applier."
            "record_writeback",
        ), patch(
            "engines.order_followup_autonomy.followup_applier."
            "record_followup_event",
        ):
            out = apply_order_followups([
                {
                    "order_id": "o1", "store_id": "s1",
                    "customer_id": "c1",
                    "action": "tag_followup",
                    "tag": "shopai-followup-thank-you-sent",
                },
            ])
        assert out[0]["applied"] is True
        assert out[0]["status"] == "recorded"


class TestAutonomyStatusSixDomains:
    """get_autonomy_status now rolls up 6 domains."""

    def test_includes_order_followup_domain(self):
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        report = get_autonomy_status()
        names = {d.name for d in report.domains}
        assert "order_followup" in names
        assert len(names) == 6
