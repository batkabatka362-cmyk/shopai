"""Tests for the new dashboard panels: agentic / moby / fal (A4/A6/A7)."""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import dashboard as dash_mod


def _dashboard_no_orch():
    """Build a Dashboard without _ensure_orch running."""
    d = dash_mod.Dashboard()
    # Prevent accidental MainOrchestrator boot inside panel tests
    d._orch = MagicMock()
    return d


class TestAgenticChannelsPanel(unittest.TestCase):
    def test_renders_channel_table(self):
        d = _dashboard_no_orch()
        fake_bridge = MagicMock()
        fake_bridge.status.return_value = [
            MagicMock(
                channel="chatgpt",
                enabled=True,
                total_orders=12,
                note="",
            ),
            MagicMock(
                channel="gemini",
                enabled=False,
                total_orders=0,
                note="not reported by Shopify",
            ),
        ]
        buf = io.StringIO()
        with patch(
            "core.bridge.agentic_storefront"
            ".get_agentic_bridge",
            return_value=fake_bridge,
        ):
            with redirect_stdout(buf):
                d._agentic_channels()
        out = buf.getvalue()
        self.assertIn("AGENTIC CHANNELS", out)
        self.assertIn("chatgpt", out)
        self.assertIn("gemini", out)
        self.assertIn("12", out)
        self.assertIn("Enrolled: ", out)

    def test_bridge_raise_is_soft(self):
        d = _dashboard_no_orch()
        buf = io.StringIO()
        with patch(
            "core.bridge.agentic_storefront"
            ".get_agentic_bridge",
            side_effect=RuntimeError("boom"),
        ):
            with redirect_stdout(buf):
                d._agentic_channels()
        out = buf.getvalue()
        self.assertIn("bridge unavailable", out)


class TestMobyTrustPanel(unittest.TestCase):
    def test_no_resolved_shows_empty_hint(self):
        d = _dashboard_no_orch()
        fake_cmp = MagicMock()
        fake_cmp.win_rate.return_value = {
            "total_resolved": 0,
        }
        buf = io.StringIO()
        with patch(
            "core.brain.moby_vote_comparator"
            ".get_moby_vote_comparator",
            return_value=fake_cmp,
        ):
            with redirect_stdout(buf):
                d._moby_trust()
        out = buf.getvalue()
        self.assertIn("MOBY TRUST", out)
        self.assertIn("no resolved disagreements", out)

    def test_resolved_shows_win_rates(self):
        d = _dashboard_no_orch()
        fake_cmp = MagicMock()
        fake_cmp.win_rate.return_value = {
            "total_resolved": 10,
            "shopai_only": 6,
            "moby_only": 3,
            "both_correct": 1,
            "both_wrong": 0,
            "shopai_win_rate": 0.7,
            "moby_win_rate": 0.4,
        }
        buf = io.StringIO()
        with patch(
            "core.brain.moby_vote_comparator"
            ".get_moby_vote_comparator",
            return_value=fake_cmp,
        ):
            with redirect_stdout(buf):
                d._moby_trust()
        out = buf.getvalue()
        self.assertIn("Resolved:", out)
        self.assertIn("70.0%", out)
        self.assertIn("40.0%", out)

    def test_comparator_raise_is_soft(self):
        d = _dashboard_no_orch()
        buf = io.StringIO()
        with patch(
            "core.brain.moby_vote_comparator"
            ".get_moby_vote_comparator",
            side_effect=RuntimeError("down"),
        ):
            with redirect_stdout(buf):
                d._moby_trust()
        out = buf.getvalue()
        self.assertIn("comparator unavailable", out)


class TestFalBudgetPanel(unittest.TestCase):
    def test_renders_router_stats(self):
        d = _dashboard_no_orch()
        fake_router = MagicMock()
        fake_router.stats.return_value = {
            "configured": True,
            "weekly_cap_usd": 10.0,
            "total_spend_usd": 3.25,
            "total_generations": 4,
        }
        buf = io.StringIO()
        with patch(
            "core.adapters.fal.video_router"
            ".FalVideoRouter",
            return_value=fake_router,
        ):
            with redirect_stdout(buf):
                d._fal_budget()
        out = buf.getvalue()
        self.assertIn("VIDEO BUDGET", out)
        self.assertIn("$10.00", out)
        self.assertIn("$3.25", out)
        self.assertIn("Generations: 4", out)

    def test_unconfigured_shows_hint(self):
        d = _dashboard_no_orch()
        fake_router = MagicMock()
        fake_router.stats.return_value = {
            "configured": False,
            "weekly_cap_usd": 10.0,
            "total_spend_usd": 0.0,
            "total_generations": 0,
        }
        buf = io.StringIO()
        with patch(
            "core.adapters.fal.video_router"
            ".FalVideoRouter",
            return_value=fake_router,
        ):
            with redirect_stdout(buf):
                d._fal_budget()
        out = buf.getvalue()
        self.assertIn("set FAL_KEY", out)

    def test_import_failure_soft(self):
        d = _dashboard_no_orch()
        buf = io.StringIO()
        with patch(
            "core.adapters.fal.video_router"
            ".FalVideoRouter",
            side_effect=RuntimeError("missing dep"),
        ):
            with redirect_stdout(buf):
                d._fal_budget()
        out = buf.getvalue()
        self.assertIn("router unavailable", out)


if __name__ == "__main__":
    unittest.main()
