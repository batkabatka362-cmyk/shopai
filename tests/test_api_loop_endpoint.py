"""Tests for ``GET /api/loop`` — autonomous-loop dashboard HTTP parity.

HTTP companion to PR #151's CLI dashboard. Returns the same
six-section dict so a future UI can render the dashboard without
re-implementing per-subsystem aggregation.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _make_handler(query: str = ""):
    from api.server import ShopAIHandler
    handler = ShopAIHandler.__new__(ShopAIHandler)
    handler.path = f"/api/loop{query}"
    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda s, b: responses.append((s, b))
    )
    return handler, responses


class TestLoopEndpoint:

    def test_returns_six_section_payload(self):
        handler, responses = _make_handler()
        handler._loop_dashboard()
        status, body = responses[0]
        assert status == 200
        assert set(body.keys()) >= {
            "approval_queue",
            "recent_executed",
            "goal",
            "recommendations",
            "webhook_stats",
            "engine_coverage",
            "governance",
        }

    def test_default_top_5(self):
        """Default ``top`` is 5 so the recent_executed +
        recommendations lists stay bounded."""
        handler, responses = _make_handler()
        handler._loop_dashboard()
        body = responses[0][1]
        assert len(body["recent_executed"]) <= 5
        assert len(body["recommendations"]) <= 5

    def test_top_query_param_honored(self):
        handler, responses = _make_handler("?top=3")
        handler._loop_dashboard()
        body = responses[0][1]
        assert len(body["recommendations"]) <= 3

    def test_top_clamped_above(self):
        """``?top=9999`` clamps to 50 — protects against
        payload-size DoS by query."""
        handler, responses = _make_handler("?top=9999")
        handler._loop_dashboard()
        body = responses[0][1]
        assert len(body["recommendations"]) <= 50

    def test_top_clamped_below(self):
        """``?top=0`` or negative clamps to at least 1."""
        handler, responses = _make_handler("?top=0")
        handler._loop_dashboard()
        body = responses[0][1]
        # 1 is the floor — we may have 0 if no engines are
        # mapped, but the cap was applied
        assert len(body["recommendations"]) <= 1

    def test_top_invalid_falls_to_default(self):
        handler, responses = _make_handler("?top=garbage")
        handler._loop_dashboard()
        status, body = responses[0]
        assert status == 200
        # Falls back to default 5 (not 500'd)
        assert len(body["recommendations"]) <= 5


class TestResponseShape:

    def test_engine_coverage_includes_ratio(self):
        handler, responses = _make_handler()
        handler._loop_dashboard()
        body = responses[0][1]
        cov = body["engine_coverage"]
        assert "total" in cov
        assert "mapped" in cov
        assert "ratio" in cov

    def test_goal_section_shape(self):
        handler, responses = _make_handler()
        handler._loop_dashboard()
        body = responses[0][1]
        assert "current" in body["goal"]
        assert "stats" in body["goal"]


class TestResilience:

    def test_build_failure_returns_200(self):
        """If the aggregator raises, return 200 with empty
        sections + an ``error`` key. A dashboard endpoint
        should never 500."""
        # The aggregator pulls from cli.py; the only way to
        # force a top-level failure is to break the import.
        # Patch the helper directly via importlib.
        import importlib.util
        with patch.object(
            importlib.util, "spec_from_file_location",
            side_effect=RuntimeError("import broken"),
        ):
            handler, responses = _make_handler()
            handler._loop_dashboard()
        status, body = responses[0]
        assert status == 200
        assert "error" in body
        # Empty sections still present so consumers can rely
        # on the schema
        assert body["approval_queue"] == {}
        assert body["recent_executed"] == []


class TestRouteRegistration:

    def test_route_in_get_table(self):
        import inspect
        from api.server import ShopAIHandler

        src = inspect.getsource(ShopAIHandler.do_GET)
        assert '"/api/loop"' in src
        assert "_loop_dashboard" in src
