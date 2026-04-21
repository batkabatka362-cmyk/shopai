"""Tests for brain-side MCP tools: trust_status, memory_ladder,
recent_decisions, predict_outcome."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mcp_server.tools import (
    ToolCall,
    ToolError,
    build_default_registry,
)


class TestRegistered(unittest.TestCase):
    def test_all_four_registered(self):
        reg = build_default_registry()
        names = {spec.name for spec in reg.list_tools()}
        for expected in (
            "trust_status",
            "memory_ladder",
            "recent_decisions",
            "predict_outcome",
        ):
            self.assertIn(expected, names)


class TestTrustStatus(unittest.TestCase):
    def test_returns_ranked_sources(self):
        calib = MagicMock()
        calib.ranked.return_value = [
            ("trends.google", 0.82),
            ("peer_store_a", 0.61),
        ]
        calib.get.side_effect = [
            MagicMock(
                samples=100,
                win_ema=0.75,
                error_rate_ema=0.05,
            ),
            MagicMock(
                samples=20,
                win_ema=0.50,
                error_rate_ema=0.30,
            ),
        ]
        reg = build_default_registry()
        with patch(
            "core.data.source_trust_calibrator.get_calibrator",
            return_value=calib,
        ):
            res = reg.call(ToolCall(tool="trust_status"))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.content), 2)
        self.assertEqual(
            res.content[0]["source"], "trends.google",
        )
        self.assertAlmostEqual(
            res.content[0]["trust"], 0.82,
        )
        self.assertEqual(
            res.content[1]["samples"], 20,
        )


class TestMemoryLadder(unittest.TestCase):
    def test_returns_stats_dict(self):
        fake_consolidator = MagicMock()
        fake_consolidator.stats.return_value = {
            "episodes": 42,
            "concepts": 7,
            "procedures": 2,
            "cold_archive": 10,
            "min_episodes_for_concept": 5,
            "min_concept_refs_for_procedure": 3,
            "min_success_rate": 0.7,
            "stale_after_s": 30 * 86400,
        }
        reg = build_default_registry()
        with patch(
            "core.memory.consolidator.get_consolidator",
            return_value=fake_consolidator,
        ):
            res = reg.call(ToolCall(tool="memory_ladder"))
        self.assertTrue(res.ok)
        self.assertEqual(res.content["episodes"], 42)
        self.assertEqual(res.content["concepts"], 7)
        self.assertEqual(res.content["procedures"], 2)


class TestRecentDecisions(unittest.TestCase):
    def _fake_record(self, decision_id, ts):
        r = MagicMock()
        r.decision_id = decision_id
        r.ts = ts
        r.node_count = 3
        r.summary = f"summary-{decision_id}"
        r.as_dict.return_value = {
            "decision_id": decision_id,
            "ts": ts,
            "node_count": 3,
            "summary": f"summary-{decision_id}",
        }
        return r

    def test_default_limit_twenty(self):
        ledger = MagicMock()
        ledger.recent.return_value = [
            self._fake_record(f"dec-{i}", 1000.0 + i)
            for i in range(3)
        ]
        reg = build_default_registry()
        with patch(
            "core.decision.rationale_ledger.get_rationale_ledger",
            return_value=ledger,
        ):
            res = reg.call(ToolCall(tool="recent_decisions"))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.content), 3)
        self.assertEqual(
            res.content[0]["decision_id"], "dec-0",
        )
        ledger.recent.assert_called_once_with(limit=20)

    def test_explicit_limit_honored(self):
        ledger = MagicMock()
        ledger.recent.return_value = []
        reg = build_default_registry()
        with patch(
            "core.decision.rationale_ledger.get_rationale_ledger",
            return_value=ledger,
        ):
            reg.call(ToolCall(
                tool="recent_decisions",
                arguments={"limit": 5},
            ))
        ledger.recent.assert_called_once_with(limit=5)

    def test_limit_clamped(self):
        ledger = MagicMock()
        ledger.recent.return_value = []
        reg = build_default_registry()
        with patch(
            "core.decision.rationale_ledger.get_rationale_ledger",
            return_value=ledger,
        ):
            reg.call(ToolCall(
                tool="recent_decisions",
                arguments={"limit": 5000},
            ))
        ledger.recent.assert_called_once_with(limit=200)


class TestPredictOutcome(unittest.TestCase):
    def test_predicts_with_full_context(self):
        calib = MagicMock()
        pred = MagicMock()
        pred.as_dict.return_value = {
            "mean": 0.42,
            "calibrated_stdev": 0.1,
            "band": "moderate",
        }
        calib.predict.return_value = pred
        reg = build_default_registry()
        with patch(
            "core.brain.world_model_calibration"
            ".get_world_model_calibration",
            return_value=calib,
        ):
            res = reg.call(ToolCall(
                tool="predict_outcome",
                arguments={
                    "action": "increase_budget",
                    "kpi": "roas",
                    "niche": "pets",
                    "price_band": "30-50",
                    "margin_band": "0.4-0.6",
                    "tone": "playful",
                },
            ))
        self.assertTrue(res.ok)
        self.assertEqual(
            res.content["band"], "moderate",
        )
        calib.predict.assert_called_once()
        kwargs = calib.predict.call_args.kwargs
        self.assertEqual(kwargs["action"], "increase_budget")
        self.assertEqual(kwargs["kpi"], "roas")
        self.assertEqual(
            kwargs["context"]["niche"], "pets",
        )

    def test_missing_action_raises_tool_error(self):
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="predict_outcome",
            arguments={"kpi": "roas"},
        ))
        self.assertFalse(res.ok)
        self.assertIn("required", res.error)

    def test_missing_kpi_raises_tool_error(self):
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="predict_outcome",
            arguments={"action": "x"},
        ))
        self.assertFalse(res.ok)


if __name__ == "__main__":
    unittest.main()
