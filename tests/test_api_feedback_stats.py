"""Tests for ``GET /api/feedback/stats`` — webhook bridge counters.

Operators debugging "is the autonomous loop receiving Shopify
webhooks?" needed a way to inspect the bridge's running counters.
The bridge exposed ``get_stats()`` already; this endpoint just
serves the same dict over HTTP.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_handler():
    from api.server import ShopAIHandler
    handler = ShopAIHandler.__new__(ShopAIHandler)
    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda s, b: responses.append((s, b))
    )
    return handler, responses


class TestFeedbackStats:

    def test_returns_zero_counters_on_fresh_bridge(self):
        """A bridge with no recorded events returns the zero
        baseline — callers can detect a wired-but-quiet system."""
        handler, responses = _make_handler()
        handler._feedback_stats()
        status, body = responses[0]
        assert status == 200
        assert "stats" in body
        for key in (
            "events_seen", "matched_actions",
            "orphan_events", "feedback_recorded", "errors",
        ):
            assert key in body["stats"]

    def test_counters_round_trip(self):
        """Mock bridge with known counts → handler returns them
        verbatim."""
        mock_bridge = MagicMock()
        mock_bridge.get_stats.return_value = {
            "events_seen": 42,
            "matched_actions": 18,
            "orphan_events": 24,
            "feedback_recorded": 18,
            "errors": 1,
        }
        with patch(
            "core.feedback.get_webhook_feedback_bridge",
            return_value=mock_bridge,
        ):
            handler, responses = _make_handler()
            handler._feedback_stats()
        status, body = responses[0]
        assert status == 200
        assert body["stats"]["events_seen"] == 42
        assert body["stats"]["matched_actions"] == 18
        assert body["stats"]["errors"] == 1


class TestResilience:

    def test_bridge_import_failure_returns_200(self):
        """If core.feedback can't import (module broken), endpoint
        returns 200 with empty stats + error string. NOT 500 — a
        read-only debug endpoint should always answer."""
        import sys

        original = sys.modules.get("core.feedback")
        sys.modules["core.feedback"] = None
        try:
            handler, responses = _make_handler()
            handler._feedback_stats()
        finally:
            if original is not None:
                sys.modules["core.feedback"] = original
            else:
                sys.modules.pop("core.feedback", None)

        status, body = responses[0]
        assert status == 200
        assert body["stats"] == {}
        assert "error" in body

    def test_get_stats_raise_safe(self):
        """If bridge.get_stats() raises, return 200 + empty stats
        + the error string. Same principle: the endpoint should
        always answer."""
        mock_bridge = MagicMock()
        mock_bridge.get_stats.side_effect = RuntimeError("counters broken")
        with patch(
            "core.feedback.get_webhook_feedback_bridge",
            return_value=mock_bridge,
        ):
            handler, responses = _make_handler()
            handler._feedback_stats()
        status, body = responses[0]
        assert status == 200
        assert body["stats"] == {}
        assert "counters broken" in body["error"]


class TestRouteRegistration:

    def test_feedback_route_in_get_table(self):
        import inspect

        from api.server import ShopAIHandler
        src = inspect.getsource(ShopAIHandler.do_GET)
        assert '"/api/feedback/stats"' in src
        assert "_feedback_stats" in src
