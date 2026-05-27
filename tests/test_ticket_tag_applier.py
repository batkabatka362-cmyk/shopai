"""Tests for engines.customer_support.ticket_tag_applier."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.customer_support.ticket_tag_applier import (
    _build_customer_tag_map,
    apply_ticket_tags,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(error="adapter no"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestTagMapBuilder:
    """_build_customer_tag_map merges per-ticket
    classifications into per-customer tag sets."""

    def test_high_priority_emits_priority_tag(self):
        classified = [
            {
                "ticket_id": "t1",
                "category": "general",
                "priority": "high",
                "sentiment": "neutral",
            },
        ]
        raw = [{"id": "t1", "customer_id": "c1"}]
        out = _build_customer_tag_map(classified, raw)
        assert out == {
            "c1": ["shopai-support-priority-high"],
        }

    def test_urgent_priority_distinct_tag(self):
        classified = [{
            "ticket_id": "t1",
            "category": "general",
            "priority": "urgent",
            "sentiment": "neutral",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        out = _build_customer_tag_map(classified, raw)
        assert "shopai-support-priority-urgent" in out["c1"]

    def test_low_priority_no_tag(self):
        classified = [{
            "ticket_id": "t1",
            "category": "general",
            "priority": "low",
            "sentiment": "neutral",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        out = _build_customer_tag_map(classified, raw)
        assert out == {}

    def test_negative_sentiment_tags(self):
        classified = [{
            "ticket_id": "t1",
            "category": "general",
            "priority": "low",
            "sentiment": "negative",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        out = _build_customer_tag_map(classified, raw)
        assert "shopai-support-sentiment-negative" in out["c1"]

    def test_billing_category_tags(self):
        classified = [{
            "ticket_id": "t1",
            "category": "billing",
            "priority": "low",
            "sentiment": "neutral",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        out = _build_customer_tag_map(classified, raw)
        assert "shopai-support-billing" in out["c1"]

    def test_multiple_tickets_same_customer_merge(self):
        """Two tickets from cust_a → one merged entry with the
        union of all triggered tags."""
        classified = [
            {
                "ticket_id": "t1", "category": "billing",
                "priority": "high", "sentiment": "neutral",
            },
            {
                "ticket_id": "t2", "category": "product",
                "priority": "low", "sentiment": "negative",
            },
        ]
        raw = [
            {"id": "t1", "customer_id": "c1"},
            {"id": "t2", "customer_id": "c1"},
        ]
        out = _build_customer_tag_map(classified, raw)
        assert set(out["c1"]) == {
            "shopai-support-billing",
            "shopai-support-priority-high",
            "shopai-support-product-issue",
            "shopai-support-sentiment-negative",
        }

    def test_missing_customer_id_dropped(self):
        classified = [{
            "ticket_id": "t1", "category": "billing",
            "priority": "high", "sentiment": "neutral",
        }]
        # raw_tickets has no entry for t1 -> no customer_id
        out = _build_customer_tag_map(classified, [])
        assert out == {}

    def test_tag_set_is_sorted_deterministic(self):
        """The output list is sorted for deterministic call
        shape (so adapter cache + replay see stable bytes)."""
        classified = [{
            "ticket_id": "t1", "category": "billing",
            "priority": "urgent", "sentiment": "negative",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        out = _build_customer_tag_map(classified, raw)
        assert out["c1"] == sorted(out["c1"])

    def test_general_category_skipped(self):
        """category=general is the fallback bucket -- noise,
        not signal. No tag."""
        classified = [{
            "ticket_id": "t1", "category": "general",
            "priority": "low", "sentiment": "neutral",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        out = _build_customer_tag_map(classified, raw)
        assert out == {}


class TestApplyTicketTagsRouter:

    def test_router_unavailable_marks_all_skipped(self):
        classified = [{
            "ticket_id": "t1", "category": "billing",
            "priority": "high", "sentiment": "neutral",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        with patch(
            "engines.customer_support.ticket_tag_applier."
            "_get_router",
            return_value=None,
        ):
            out = apply_ticket_tags(classified, raw)
        assert len(out) == 1
        assert out[0]["applied"] is False
        assert out[0]["status"] == "router_unavailable"

    def test_router_ok_marks_applied(self):
        classified = [{
            "ticket_id": "t1", "category": "billing",
            "priority": "high", "sentiment": "neutral",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        fake_router = MagicMock()
        fake_router.execute.return_value = _ok()
        with patch(
            "engines.customer_support.ticket_tag_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.customer_support.ticket_tag_applier."
            "_capability",
            return_value=object(),
        ), patch(
            "engines.customer_support.ticket_tag_applier."
            "record_writeback",
        ) as rec:
            out = apply_ticket_tags(classified, raw)
        assert out[0]["applied"] is True
        assert out[0]["status"] == "recorded"
        rec.assert_called_once()

    def test_adapter_failure_coerces_error_to_string(self):
        """The router may return a non-string error (e.g. an
        exception instance). The applier must str-coerce so
        downstream JSON serializers don't blow up."""
        classified = [{
            "ticket_id": "t1", "category": "billing",
            "priority": "high", "sentiment": "neutral",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        fake_router = MagicMock()

        class WeirdError:
            def __str__(self) -> str:
                return "weird custom error"

        fake_router.execute.return_value = SimpleNamespace(
            ok=False, error=WeirdError(),
        )
        with patch(
            "engines.customer_support.ticket_tag_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.customer_support.ticket_tag_applier."
            "_capability",
            return_value=object(),
        ):
            out = apply_ticket_tags(classified, raw)
        assert out[0]["status"] == "adapter_failed"
        assert isinstance(out[0]["error"], str)
        assert "weird custom error" in out[0]["error"]

    def test_adapter_raises_caught_per_customer(self):
        """One row's exception must not poison other rows."""
        classified = [
            {
                "ticket_id": "t1", "category": "billing",
                "priority": "high", "sentiment": "neutral",
            },
            {
                "ticket_id": "t2", "category": "product",
                "priority": "urgent", "sentiment": "neutral",
            },
        ]
        raw = [
            {"id": "t1", "customer_id": "c1"},
            {"id": "t2", "customer_id": "c2"},
        ]
        fake_router = MagicMock()
        # First call raises; second succeeds
        fake_router.execute.side_effect = [
            RuntimeError("net down"),
            _ok(),
        ]
        with patch(
            "engines.customer_support.ticket_tag_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.customer_support.ticket_tag_applier."
            "_capability",
            return_value=object(),
        ):
            out = apply_ticket_tags(classified, raw)
        # Dict iteration order matches insertion in modern
        # Python -- c1 first, c2 second
        statuses = {r["customer_id"]: r["status"] for r in out}
        assert statuses["c1"] == "adapter_failed"
        assert statuses["c2"] == "recorded"


class TestEmptyInputs:

    def test_empty_classified_tickets(self):
        out = apply_ticket_tags([], [])
        assert out == []

    def test_classified_tickets_not_list(self):
        out = apply_ticket_tags(
            "not_a_list",  # type: ignore[arg-type]
            [],
        )
        assert out == []

    def test_no_actionable_tickets_returns_empty(self):
        """All tickets are low/neutral/general -> no tags ->
        no router calls + empty output."""
        classified = [{
            "ticket_id": "t1", "category": "general",
            "priority": "low", "sentiment": "neutral",
        }]
        raw = [{"id": "t1", "customer_id": "c1"}]
        out = apply_ticket_tags(classified, raw)
        assert out == []
