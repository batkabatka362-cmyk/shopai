"""Tests for ``shopai feedback stats`` — terminal parity with
the ``GET /api/feedback/stats`` endpoint.

Operators debugging "are Shopify webhooks reaching this server?"
should be able to run a single command from the terminal instead
of curling the API.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


# ─── dispatcher ───────────────────────────────────────────────────


class TestFeedbackDispatcher:

    def test_no_subcommand_shows_usage(self, cli):
        out, code = _capture(
            cli._cmd_feedback, _ns(feedback_action=None),
        )
        assert code == 1
        assert "Usage:" in out
        assert "feedback stats" in out

    def test_dispatches_stats(self, cli):
        with patch(
            "core.feedback.get_webhook_feedback_bridge",
        ) as mock_get:
            mock_bridge = MagicMock()
            mock_bridge.get_stats.return_value = {
                "events_seen": 0, "matched_actions": 0,
                "orphan_events": 0, "feedback_recorded": 0,
                "errors": 0,
            }
            mock_get.return_value = mock_bridge
            out, code = _capture(
                cli._cmd_feedback,
                _ns(feedback_action="stats", json=False),
            )
        assert code == 0
        assert "Webhook bridge stats:" in out


# ─── stats verb ───────────────────────────────────────────────────


class TestFeedbackStats:

    def test_text_view(self, cli):
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
            out, code = _capture(
                cli._cmd_feedback_stats, _ns(json=False),
            )
        assert code == 0
        # Each counter renders
        assert "Events seen" in out
        assert "42" in out
        assert "Matched actions" in out
        assert "18" in out

    def test_json_view(self, cli):
        mock_bridge = MagicMock()
        mock_bridge.get_stats.return_value = {
            "events_seen": 42, "matched_actions": 0,
            "orphan_events": 0, "feedback_recorded": 0, "errors": 0,
        }
        with patch(
            "core.feedback.get_webhook_feedback_bridge",
            return_value=mock_bridge,
        ):
            out, code = _capture(
                cli._cmd_feedback_stats, _ns(json=True),
            )
        assert code == 0
        # Output round-trips through json.loads
        data = json.loads(out)
        assert data["events_seen"] == 42

    def test_zero_events_hint(self, cli):
        """Operator-friendly hint when no webhooks have arrived —
        points at the Shopify webhook subscription as the likely
        culprit."""
        mock_bridge = MagicMock()
        mock_bridge.get_stats.return_value = {
            "events_seen": 0, "matched_actions": 0,
            "orphan_events": 0, "feedback_recorded": 0, "errors": 0,
        }
        with patch(
            "core.feedback.get_webhook_feedback_bridge",
            return_value=mock_bridge,
        ):
            out, _ = _capture(
                cli._cmd_feedback_stats, _ns(json=False),
            )
        assert "Hint: 0 events seen" in out
        assert "Shopify webhook" in out

    def test_zero_matched_hint(self, cli):
        """Hint when events arrive but no engine attribution —
        engines may not be emitting matchable params."""
        mock_bridge = MagicMock()
        mock_bridge.get_stats.return_value = {
            "events_seen": 50, "matched_actions": 0,
            "orphan_events": 50, "feedback_recorded": 50, "errors": 0,
        }
        with patch(
            "core.feedback.get_webhook_feedback_bridge",
            return_value=mock_bridge,
        ):
            out, _ = _capture(
                cli._cmd_feedback_stats, _ns(json=False),
            )
        assert "no engine attribution" in out

    def test_bridge_import_failure_exits_1(self, cli):
        import sys
        original = sys.modules.get("core.feedback")
        sys.modules["core.feedback"] = None
        try:
            out, code = _capture(
                cli._cmd_feedback_stats, _ns(json=False),
            )
        finally:
            if original is not None:
                sys.modules["core.feedback"] = original
            else:
                sys.modules.pop("core.feedback", None)
        assert code == 1
        assert "Error" in out
