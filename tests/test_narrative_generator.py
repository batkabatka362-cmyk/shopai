"""Narrative generator tests."""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from core.brain import narrative_generator as ng


@dataclass
class _FakeEvent:
    kind: str
    payload: dict[str, Any]
    cycle_id: str = "c1"


class TestGroup(unittest.TestCase):
    def test_groups_by_kind(self) -> None:
        events = [
            _FakeEvent("phase", {"name": "a"}),
            _FakeEvent("decision", {"chosen": {}}),
            _FakeEvent("phase", {"name": "b"}),
        ]
        groups = ng._group_by_kind(events)
        self.assertEqual(len(groups["phase"]), 2)
        self.assertEqual(len(groups["decision"]), 1)

    def test_missing_kind_skipped(self) -> None:
        events = [{"payload": {}}, _FakeEvent("phase", {"name": "x"})]
        groups = ng._group_by_kind(events)
        self.assertEqual(len(groups["phase"]), 1)


class TestKpiMoves(unittest.TestCase):
    def test_delta_positive(self) -> None:
        now = [
            _FakeEvent("outcome", {"kpi": "roas", "value": 3.0}),
        ]
        prev = [
            _FakeEvent("outcome", {"kpi": "roas", "value": 2.0}),
        ]
        moves = ng._compute_kpi_moves(now, prev)
        self.assertEqual(moves[0].kpi, "roas")
        self.assertEqual(moves[0].delta, 1.0)

    def test_missing_prev_delta_zero(self) -> None:
        now = [_FakeEvent("outcome", {"kpi": "roas", "value": 3.0})]
        moves = ng._compute_kpi_moves(now, [])
        # No previous → delta treated as 0 so we don't invent a drop
        self.assertEqual(moves[0].delta, 0.0)

    def test_invalid_value_skipped(self) -> None:
        now = [_FakeEvent("outcome", {"kpi": "roas", "value": "nope"})]
        moves = ng._compute_kpi_moves(now, [])
        self.assertEqual(moves, [])

    def test_percent_change_zero_previous(self) -> None:
        m = ng.KpiMove(kpi="x", previous=0.0, current=5.0, delta=5.0)
        self.assertEqual(m.percent_change, 0.0)


class TestCompose(unittest.TestCase):
    def test_empty_narrative(self) -> None:
        n = ng.compose("c1", [], [])
        self.assertIn("c1", n.headline)
        self.assertEqual(n.kpi_moves, [])

    def test_headline_counts(self) -> None:
        events = [
            _FakeEvent("decision", {"chosen": {"action": "scale"}}),
            _FakeEvent("outcome", {"kpi": "roas", "value": 2.0}),
        ]
        n = ng.compose("c_42", events)
        self.assertIn("1 decision", n.headline)
        self.assertIn("1 outcome", n.headline)

    def test_phase_failures_become_warnings(self) -> None:
        events = [
            _FakeEvent("phase", {"name": "fetch", "status": "failed"}),
            _FakeEvent("phase", {"name": "ok_phase", "status": "ok"}),
        ]
        n = ng.compose("c", events)
        self.assertEqual(len(n.warnings), 1)
        self.assertIn("fetch", n.warnings[0])

    def test_health_picked_from_assessment(self) -> None:
        events = [
            _FakeEvent("assessment", {"health_score": 72.0}),
        ]
        n = ng.compose("c", events)
        self.assertEqual(n.health_score, 72.0)
        self.assertIn("health=72", n.headline)

    def test_kpi_moves_in_body(self) -> None:
        now = [_FakeEvent("outcome", {"kpi": "roas", "value": 3.0})]
        prev = [_FakeEvent("outcome", {"kpi": "roas", "value": 2.0})]
        n = ng.compose("c", now, prev)
        self.assertIn("roas", n.body)
        self.assertIn("↑", n.body)

    def test_decisions_in_body(self) -> None:
        events = [
            _FakeEvent(
                "decision",
                {
                    "chosen": {"action": "scale"},
                    "context": {"niche": "audio"},
                },
            ),
        ]
        n = ng.compose("c", events)
        self.assertIn("scale", n.body)
        self.assertIn("audio", n.body)

    def test_llm_section_shown(self) -> None:
        events = [
            _FakeEvent("llm_call", {"cost_usd": 0.01, "adapter": "groq"}),
            _FakeEvent("llm_call", {"cost_usd": 0.02, "adapter": "groq"}),
        ]
        n = ng.compose("c", events)
        self.assertIn("LLM", n.body)
        self.assertIn("2 call", n.body)


class TestDict(unittest.TestCase):
    def test_narrative_as_dict(self) -> None:
        n = ng.compose("c", [
            _FakeEvent("decision", {"chosen": {"action": "x"}}),
        ])
        d = n.as_dict()
        self.assertIn("headline", d)
        self.assertIn("body", d)

    def test_kpi_move_as_dict(self) -> None:
        m = ng.KpiMove(kpi="r", previous=1.0, current=2.0, delta=1.0)
        d = m.as_dict()
        self.assertEqual(d["percent_change"], 100.0)


class TestGenerateNarrativeLookup(unittest.TestCase):
    """generate_narrative pulls from experience_recorder; patch it."""

    def test_graceful_when_recorder_fails(self) -> None:
        import unittest.mock as mock
        with mock.patch(
            "core.brain.experience_recorder.recent",
            side_effect=RuntimeError("db missing"),
        ):
            # Exception inside recent() should NOT propagate — compose
            # returns an empty narrative instead.
            try:
                n = ng.generate_narrative("c")
            except RuntimeError:
                self.fail("generate_narrative should not raise")
            else:
                self.assertIsNotNone(n)


if __name__ == "__main__":
    unittest.main()
