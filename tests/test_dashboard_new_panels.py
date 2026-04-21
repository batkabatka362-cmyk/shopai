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


class TestAutopilotPanel(unittest.TestCase):
    def test_not_running_shows_start_hint(self):
        d = _dashboard_no_orch()
        fake_status = MagicMock(
            running=False,
            detail="pidfile not found",
            pid=0, uptime_s=0,
        )
        buf = io.StringIO()
        with patch(
            "core.system.pidfile.read_status",
            return_value=fake_status,
        ):
            with redirect_stdout(buf):
                d._autopilot_panel()
        out = buf.getvalue()
        self.assertIn("AUTOPILOT DAEMON", out)
        self.assertIn("running:", out)
        self.assertIn("run_daemon.py", out)

    def test_running_shows_pid_and_uptime(self):
        d = _dashboard_no_orch()
        fake_status = MagicMock(
            running=True,
            pid=12345,
            uptime_s=3600 * 5,
            detail="",
        )
        buf = io.StringIO()
        with patch(
            "core.system.pidfile.read_status",
            return_value=fake_status,
        ):
            with redirect_stdout(buf):
                d._autopilot_panel()
        out = buf.getvalue()
        self.assertIn("pid=12345", out)
        self.assertIn("uptime=5.0h", out)

    def test_pidfile_raise_is_soft(self):
        d = _dashboard_no_orch()
        buf = io.StringIO()
        with patch(
            "core.system.pidfile.read_status",
            side_effect=RuntimeError("boom"),
        ):
            with redirect_stdout(buf):
                d._autopilot_panel()
        out = buf.getvalue()
        self.assertIn("pidfile unavailable", out)


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


class TestForceFreshPropagation(unittest.TestCase):
    """P1.5 — ``--live`` must pass force=True so the 5-min
    agentic bridge cache doesn't make consecutive refreshes
    show stale data."""

    def test_default_calls_status_without_force(self):
        d = _dashboard_no_orch()
        fake_bridge = MagicMock()
        fake_bridge.status.return_value = []
        with patch(
            "core.bridge.agentic_storefront"
            ".get_agentic_bridge",
            return_value=fake_bridge,
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                d._agentic_channels()
        fake_bridge.status.assert_called_once_with(
            force=False,
        )

    def test_force_fresh_true_passes_force(self):
        d = _dashboard_no_orch()
        fake_bridge = MagicMock()
        fake_bridge.status.return_value = []
        with patch(
            "core.bridge.agentic_storefront"
            ".get_agentic_bridge",
            return_value=fake_bridge,
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                d._agentic_channels(force_fresh=True)
        fake_bridge.status.assert_called_once_with(
            force=True,
        )

    def test_show_live_forces_fresh(self):
        """show_live() calls show(force_fresh=True)."""
        d = _dashboard_no_orch()
        calls: list[dict] = []
        d.show = lambda **kw: (
            calls.append(kw)
            or (_ for _ in ()).throw(KeyboardInterrupt)
        )
        d.show_live(interval=0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].get("force_fresh"))

    def test_plain_show_does_not_force(self):
        d = _dashboard_no_orch()
        fake_bridge = MagicMock()
        fake_bridge.status.return_value = []
        with patch(
            "core.bridge.agentic_storefront"
            ".get_agentic_bridge",
            return_value=fake_bridge,
        ):
            # Patch out every non-agentic panel so show()
            # doesn't explode on MagicMock-orch attrs.
            for name in (
                "_header", "_system_health", "_engine_stats",
                "_agent_stats", "_workflow_stats", "_metrics",
                "_autopilot_panel", "_moby_trust",
                "_fal_budget", "_recent_activity", "_footer",
            ):
                setattr(d, name, lambda *a, **k: None)
            d.show()
        # Default show() → force=False
        fake_bridge.status.assert_called_once_with(
            force=False,
        )


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
