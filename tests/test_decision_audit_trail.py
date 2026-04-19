"""Decision audit trail tests."""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from core.brain import decision_audit_trail as dat


@dataclass
class _FakeEvent:
    id: str
    kind: str
    payload: dict[str, Any]
    cycle_id: str
    ts: float


def _make_recent(events):
    def fn(**kwargs):
        return events
    return fn


class TestUnknown(unittest.TestCase):
    def test_unknown_decision_id(self) -> None:
        a = dat.DecisionAuditor(recent_fn=_make_recent([]))
        trail = a.build("nope")
        self.assertEqual(trail.verdict, "unknown")
        self.assertEqual(trail.contributors, [])

    def test_blank_decision_id(self) -> None:
        a = dat.DecisionAuditor()
        trail = a.build("")
        self.assertEqual(trail.verdict, "unknown")


class TestPartial(unittest.TestCase):
    def test_decision_with_only_one_phase(self) -> None:
        events = [
            _FakeEvent("d1", "decision",
                       {"chosen": {"action": "scale"}},
                       cycle_id="c1", ts=10.0),
            _FakeEvent("p1", "phase",
                       {"name": "fetch", "status": "ok"},
                       cycle_id="c1", ts=8.0),
        ]
        a = dat.DecisionAuditor(recent_fn=_make_recent(events))
        trail = a.build("d1")
        # Phase only — no outcome → partial
        self.assertEqual(trail.verdict, "partial")
        self.assertEqual(len(trail.contributors), 1)


class TestComplete(unittest.TestCase):
    def test_decision_with_phase_and_outcome(self) -> None:
        events = [
            _FakeEvent(
                "d1", "decision",
                {"chosen": {"action": "scale"},
                 "context": {"niche": "audio"}},
                cycle_id="c1", ts=10.0,
            ),
            _FakeEvent(
                "p1", "phase",
                {"name": "fetch", "status": "ok"},
                cycle_id="c1", ts=8.0,
            ),
            _FakeEvent(
                "o1", "outcome",
                {"kpi": "roas", "value": 2.5},
                cycle_id="c1", ts=15.0,
            ),
        ]
        a = dat.DecisionAuditor(
            recent_fn=_make_recent(events),
            credit_lookup_fn=lambda did: {"total_credit": 50.0},
        )
        trail = a.build("d1")
        self.assertEqual(trail.verdict, "complete")
        self.assertEqual(len(trail.contributors), 2)
        self.assertEqual(
            trail.metrics["credits"]["total_credit"], 50.0,
        )

    def test_only_includes_same_cycle(self) -> None:
        events = [
            _FakeEvent(
                "d1", "decision",
                {"chosen": {"action": "x"}},
                cycle_id="c1", ts=10.0,
            ),
            _FakeEvent(
                "p1", "phase",
                {"name": "ok", "status": "ok"},
                cycle_id="c1", ts=8.0,
            ),
            _FakeEvent(
                "o_other", "outcome",
                {"kpi": "x", "value": 1},
                cycle_id="c2", ts=11.0,
            ),
        ]
        a = dat.DecisionAuditor(recent_fn=_make_recent(events))
        trail = a.build("d1")
        for c in trail.contributors:
            self.assertNotEqual(c.ref_id, "o_other")


class TestContributorsOrdered(unittest.TestCase):
    def test_sorted_by_ts(self) -> None:
        events = [
            _FakeEvent(
                "d1", "decision",
                {"chosen": {}}, cycle_id="c1", ts=20.0,
            ),
            _FakeEvent(
                "late", "phase",
                {"name": "x", "status": "ok"},
                cycle_id="c1", ts=15.0,
            ),
            _FakeEvent(
                "early", "phase",
                {"name": "y", "status": "ok"},
                cycle_id="c1", ts=5.0,
            ),
        ]
        a = dat.DecisionAuditor(recent_fn=_make_recent(events))
        trail = a.build("d1")
        ids = [c.ref_id for c in trail.contributors]
        self.assertEqual(ids, ["early", "late"])


class TestLLMCostAggregation(unittest.TestCase):
    def test_costs_summed(self) -> None:
        events = [
            _FakeEvent(
                "d1", "decision", {"chosen": {}},
                cycle_id="c1", ts=10.0,
            ),
            _FakeEvent(
                "l1", "llm_call",
                {"cost_usd": 0.01, "adapter": "groq", "ok": True},
                cycle_id="c1", ts=5.0,
            ),
            _FakeEvent(
                "l2", "llm_call",
                {"cost_usd": 0.05, "adapter": "groq", "ok": True},
                cycle_id="c1", ts=7.0,
            ),
        ]
        a = dat.DecisionAuditor(recent_fn=_make_recent(events))
        trail = a.build("d1")
        self.assertAlmostEqual(
            trail.metrics["llm_cost_usd"], 0.06, places=6,
        )

    def test_invalid_cost_skipped(self) -> None:
        events = [
            _FakeEvent(
                "d1", "decision", {"chosen": {}},
                cycle_id="c1", ts=10.0,
            ),
            _FakeEvent(
                "l1", "llm_call",
                {"cost_usd": "nope"},
                cycle_id="c1", ts=5.0,
            ),
        ]
        a = dat.DecisionAuditor(recent_fn=_make_recent(events))
        trail = a.build("d1")
        self.assertEqual(trail.metrics["llm_cost_usd"], 0.0)


class TestPerKindCounts(unittest.TestCase):
    def test_count_by_kind(self) -> None:
        events = [
            _FakeEvent("d1", "decision", {"chosen": {}},
                       cycle_id="c", ts=10),
            _FakeEvent("p1", "phase",
                       {"name": "a", "status": "ok"},
                       cycle_id="c", ts=5),
            _FakeEvent("p2", "phase",
                       {"name": "b", "status": "ok"},
                       cycle_id="c", ts=6),
            _FakeEvent("o1", "outcome",
                       {"kpi": "x", "value": 1},
                       cycle_id="c", ts=15),
        ]
        a = dat.DecisionAuditor(recent_fn=_make_recent(events))
        trail = a.build("d1")
        self.assertEqual(trail.metrics["by_kind"]["phase"], 2)
        self.assertEqual(trail.metrics["by_kind"]["outcome"], 1)


class TestChainText(unittest.TestCase):
    def test_renders_markdown(self) -> None:
        events = [
            _FakeEvent(
                "d1", "decision",
                {"chosen": {"action": "scale"}},
                cycle_id="c1", ts=10.0,
            ),
            _FakeEvent(
                "p1", "phase",
                {"name": "fetch", "status": "ok"},
                cycle_id="c1", ts=8.0,
            ),
            _FakeEvent(
                "o1", "outcome",
                {"kpi": "roas", "value": 2.5},
                cycle_id="c1", ts=15.0,
            ),
        ]
        a = dat.DecisionAuditor(
            recent_fn=_make_recent(events),
            credit_lookup_fn=lambda did: {"total_credit": 50.0},
        )
        trail = a.build("d1")
        text = a.chain_text(trail)
        self.assertIn("scale", text)
        self.assertIn("complete", text)
        self.assertIn("Trail", text)

    def test_unknown_text(self) -> None:
        a = dat.DecisionAuditor(recent_fn=_make_recent([]))
        text = a.chain_text(a.build("missing"))
        self.assertIn("no trail found", text)


class TestSafeFailure(unittest.TestCase):
    def test_recent_failure_handled(self) -> None:
        def boom(**k):
            raise RuntimeError("db dead")

        a = dat.DecisionAuditor(recent_fn=boom)
        trail = a.build("d1")
        self.assertEqual(trail.verdict, "unknown")

    def test_credit_lookup_failure_handled(self) -> None:
        events = [
            _FakeEvent(
                "d1", "decision", {"chosen": {}},
                cycle_id="c", ts=10,
            ),
            _FakeEvent(
                "o1", "outcome", {"kpi": "x", "value": 1},
                cycle_id="c", ts=11,
            ),
            _FakeEvent(
                "p1", "phase", {"name": "a", "status": "ok"},
                cycle_id="c", ts=9,
            ),
        ]

        def bad_credit(_did):
            raise RuntimeError("nope")

        a = dat.DecisionAuditor(
            recent_fn=_make_recent(events),
            credit_lookup_fn=bad_credit,
        )
        trail = a.build("d1")
        # Trail still complete, credits silent-empty.
        self.assertEqual(trail.verdict, "complete")
        self.assertEqual(trail.metrics["credits"], {})


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        events = [
            _FakeEvent(
                "d1", "decision",
                {"chosen": {"action": "x"}},
                cycle_id="c", ts=10,
            ),
        ]
        a = dat.DecisionAuditor(recent_fn=_make_recent(events))
        d = a.build("d1").as_dict()
        self.assertIn("contributors", d)
        self.assertIn("metrics", d)


if __name__ == "__main__":
    unittest.main()
