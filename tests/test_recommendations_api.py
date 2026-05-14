"""Tests for the /api/recommendations HTTP endpoint and the
``shopai suggest`` CLI command.

The recommender core is fully tested in
``test_engine_recommender.py``. This file exercises the two
surfaces that expose it externally:

  1. ``ShopAIHandler._list_recommendations`` — query-param parsing
     + JSON response shape.
  2. ``cli.py suggest`` — table view, JSON view, alternatives
     toggle.
"""
from __future__ import annotations

import json
import subprocess
import sys
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest


# ─── /api/recommendations ─────────────────────────────────────


def _make_handler(query: str):
    """Build a minimal handler with just enough plumbing to call
    ``_list_recommendations`` directly."""
    from api.server import ShopAIHandler

    handler = ShopAIHandler.__new__(ShopAIHandler)
    handler.path = f"/api/recommendations{query}"

    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda status, body: responses.append((status, body))
    )
    return handler, responses


class TestRecommendationsAPI:

    def test_default_returns_200_with_recommendations(self):
        handler, responses = _make_handler("")
        handler._list_recommendations()
        assert len(responses) == 1
        status, body = responses[0]
        assert status == 200
        assert "active_goal" in body
        assert "primary" in body
        assert "alternatives" in body
        assert "source" in body
        assert body["source"] == "rules"

    def test_explicit_goal_used(self):
        handler, responses = _make_handler("?goal=grow_customers")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        assert body["active_goal"] == "grow_customers"
        # All primary picks aligned to grow_customers
        for r in body["primary"]:
            assert r["goal"] == "grow_customers"
            assert r["alignment"] == 1.0

    def test_limit_clamped(self):
        handler, responses = _make_handler("?limit=3")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        assert len(body["primary"]) <= 3

    def test_limit_max_capped_at_50(self):
        handler, responses = _make_handler("?limit=9999")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        assert len(body["primary"]) <= 50

    def test_limit_invalid_defaults_to_10(self):
        handler, responses = _make_handler("?limit=garbage")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        # Falls back to default 10, primary list reflects that
        assert len(body["primary"]) <= 10

    def test_alternatives_zero_skips_bucket(self):
        handler, responses = _make_handler("?alternatives=0")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 200
        assert body["alternatives"] == []

    def test_alternatives_false_skips_bucket(self):
        handler, responses = _make_handler("?alternatives=false")
        handler._list_recommendations()
        status, body = responses[0]
        assert body["alternatives"] == []

    def test_alternatives_default_included(self):
        handler, responses = _make_handler("?goal=grow_customers")
        handler._list_recommendations()
        status, body = responses[0]
        # Alternatives bucket has entries (cross-goal engines exist)
        assert len(body["alternatives"]) > 0

    def test_invalid_goal_name_rejected(self):
        """Goal names go through validate_safe_name — special chars
        produce a 400."""
        handler, responses = _make_handler("?goal=evil%20goal!!")
        handler._list_recommendations()
        status, body = responses[0]
        assert status == 400
        assert "error" in body

    def test_recommender_failure_returns_500(self):
        handler, responses = _make_handler("")
        with patch(
            "core.brain.engine_recommender.recommend_engines",
            side_effect=RuntimeError("internal failure"),
        ):
            handler._list_recommendations()
        status, body = responses[0]
        assert status == 500
        assert "internal failure" in body["error"]

    def test_response_serializes_cleanly(self):
        """The handler's _json_response stub records the dict;
        verify it actually round-trips through json.dumps."""
        handler, responses = _make_handler("?goal=grow_customers&limit=3")
        handler._list_recommendations()
        status, body = responses[0]
        # json.dumps must not raise
        encoded = json.dumps(body, default=str)
        # And re-parsing returns equivalent structure
        decoded = json.loads(encoded)
        assert decoded["active_goal"] == "grow_customers"


# ─── /api/recommendations route registration ──────────────────


class TestRouteRegistration:

    def test_recommendations_is_GET_route(self):
        """The endpoint is registered in the GET routes table so
        dispatch finds it."""
        from api.server import ShopAIHandler

        # We can't easily test the do_GET method directly without
        # spinning up the server, but we can assert the route map
        # contains our entry by inspecting the do_GET source.
        import inspect
        src = inspect.getsource(ShopAIHandler.do_GET)
        assert '"/api/recommendations"' in src
        assert "_list_recommendations" in src


# ─── shopai suggest CLI command ───────────────────────────────


def _run_cli(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run ``python cli.py <args>`` and capture stdout/stderr."""
    return subprocess.run(
        [sys.executable, "cli.py", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


class TestSuggestCLI:

    def test_default_invocation_succeeds(self):
        proc = _run_cli("suggest", "--limit", "2")
        assert proc.returncode == 0, proc.stderr
        assert "Active goal:" in proc.stdout
        assert "Top picks" in proc.stdout

    def test_explicit_goal(self):
        proc = _run_cli(
            "suggest", "--goal", "grow_customers", "--limit", "2",
        )
        assert proc.returncode == 0, proc.stderr
        assert "grow_customers" in proc.stdout

    def test_json_output_is_parseable(self):
        proc = _run_cli(
            "suggest", "--goal", "grow_customers", "--limit", "2",
            "--json",
        )
        assert proc.returncode == 0, proc.stderr
        # The full stdout should be valid JSON.
        # Strip any logger noise from stderr (stdout-only check).
        payload = json.loads(proc.stdout)
        assert payload["active_goal"] == "grow_customers"
        assert isinstance(payload["primary"], list)
        assert isinstance(payload["alternatives"], list)

    def test_no_alternatives_flag(self):
        proc = _run_cli(
            "suggest", "--goal", "increase_aov",
            "--limit", "2", "--no-alternatives",
        )
        assert proc.returncode == 0, proc.stderr
        # Table view: no "Alternatives" section heading
        assert "Alternatives" not in proc.stdout

    def test_unknown_goal_returns_no_match(self):
        """Unknown goal → primary list empty, exit cleanly."""
        proc = _run_cli(
            "suggest", "--goal", "totally_made_up", "--limit", "2",
        )
        assert proc.returncode == 0, proc.stderr
        # Either "No engines mapped" message or empty rank list
        # surfaces — both signal "nothing to do".
        assert (
            "No engines mapped" in proc.stdout
            or "no engines map" in proc.stdout
        )
