"""Five-pillar structured decision framework tests.

Covers the module the owner asked for (2026-04-21): an
AGI-level structured thinking pipeline for every
significant ShopAI decision. Tests each pillar in
isolation + the aggregate Deliberation pipeline + the
rationale-ledger integration + the MCP surface.
"""
from __future__ import annotations

import math
import unittest

from core.brain.structured_decision import (
    Constraint,
    Deliberation,
    OutcomeSpec,
    RefineStep,
    SelfAwareness,
    ThinkingDirection,
    default_scorer,
    deliberate,
    recent_deliberations,
    record_deliberation,
    reset_recent_for_tests,
)


# ── Pillar 1 — OutcomeSpec ───────────────────────────────


class TestOutcomeSpec(unittest.TestCase):
    def test_valid(self):
        o = OutcomeSpec(
            what="activate campaign",
            why="winner signals strong",
            measurable="7-day ROAS ≥ 1.5",
            value_usd=120.0,
        )
        d = o.as_dict()
        self.assertEqual(d["what"], "activate campaign")
        self.assertEqual(d["value_usd"], 120.0)

    def test_missing_what_raises(self):
        with self.assertRaises(ValueError):
            OutcomeSpec(what="", why="y", measurable="m")

    def test_missing_why_raises(self):
        with self.assertRaises(ValueError):
            OutcomeSpec(what="w", why="", measurable="m")

    def test_missing_measurable_raises(self):
        with self.assertRaises(ValueError):
            OutcomeSpec(what="w", why="y", measurable="")


# ── Pillar 2 — ThinkingDirection ─────────────────────────


class TestThinkingDirection(unittest.TestCase):
    def test_valid(self):
        d = ThinkingDirection(
            label="aggressive",
            action={"budget": 100},
            reasoning="ride momentum",
            expected_value=50.0,
            confidence=0.7,
        )
        payload = d.as_dict()
        self.assertEqual(payload["label"], "aggressive")
        self.assertEqual(payload["confidence"], 0.7)

    def test_empty_label_raises(self):
        with self.assertRaises(ValueError):
            ThinkingDirection(
                label="", action={}, reasoning="r",
            )

    def test_bad_confidence_raises(self):
        with self.assertRaises(ValueError):
            ThinkingDirection(
                label="x", action={},
                reasoning="r", confidence=1.5,
            )


# ── Pillar 3 — Constraint ────────────────────────────────


class TestConstraint(unittest.TestCase):
    def test_hard_vs_soft(self):
        h = Constraint(
            name="budget_cap", kind="hard",
            reason="tripwire",
        )
        s = Constraint(
            name="style", kind="soft",
            reason="brand voice",
        )
        self.assertEqual(h.kind, "hard")
        self.assertEqual(s.kind, "soft")

    def test_bad_kind_raises(self):
        with self.assertRaises(ValueError):
            Constraint(
                name="x", kind="medium", reason="r",
            )

    def test_evaluator_default_is_advisory(self):
        c = Constraint(
            name="x", kind="hard", reason="r",
        )
        direction = ThinkingDirection(
            label="x", action={}, reasoning="r",
        )
        ok, headroom, detail = c.evaluate(direction)
        self.assertTrue(ok)
        self.assertEqual(headroom, 1.0)
        self.assertEqual(detail, "advisory")

    def test_evaluator_called(self):
        seen = []

        def _eval(d):
            seen.append(d.label)
            return (True, 0.8, "ok")

        c = Constraint(
            name="x", kind="soft",
            reason="r", evaluator=_eval,
        )
        direction = ThinkingDirection(
            label="a", action={}, reasoning="r",
        )
        ok, headroom, detail = c.evaluate(direction)
        self.assertEqual(seen, ["a"])
        self.assertTrue(ok)
        self.assertAlmostEqual(headroom, 0.8)
        self.assertEqual(detail, "ok")

    def test_evaluator_exception_returns_violation(self):
        def _eval(d):
            raise RuntimeError("boom")

        c = Constraint(
            name="x", kind="hard",
            reason="r", evaluator=_eval,
        )
        direction = ThinkingDirection(
            label="x", action={}, reasoning="r",
        )
        ok, headroom, detail = c.evaluate(direction)
        self.assertFalse(ok)
        self.assertEqual(headroom, 0.0)
        self.assertIn("boom", detail)

    def test_evaluator_wrong_shape_rejected(self):
        c = Constraint(
            name="x", kind="hard",
            reason="r", evaluator=lambda d: "not a tuple",
        )
        direction = ThinkingDirection(
            label="x", action={}, reasoning="r",
        )
        ok, _, detail = c.evaluate(direction)
        self.assertFalse(ok)
        self.assertIn("shape", detail)


# ── Pillar 5 — SelfAwareness ─────────────────────────────


class TestSelfAwareness(unittest.TestCase):
    def test_valid(self):
        aw = SelfAwareness(
            loop_check="aligned",
            dollar_distance=1,
            plumbing_vs_capability="capability",
            notes=("note 1",),
        )
        d = aw.as_dict()
        self.assertEqual(d["loop_check"], "aligned")
        self.assertEqual(d["dollar_distance"], 1)

    def test_bad_loop_check(self):
        with self.assertRaises(ValueError):
            SelfAwareness(
                loop_check="confused",
                dollar_distance=2,
                plumbing_vs_capability="capability",
            )

    def test_bad_plumbing_vs_capability(self):
        with self.assertRaises(ValueError):
            SelfAwareness(
                loop_check="aligned",
                dollar_distance=2,
                plumbing_vs_capability="refactor",
            )


# ── Default scorer ───────────────────────────────────────


class TestDefaultScorer(unittest.TestCase):
    def _make_outcome(self, value=0.0):
        return OutcomeSpec(
            what="w", why="y",
            measurable="m", value_usd=value,
        )

    def _make_direction(self, ev=50.0, conf=0.5):
        return ThinkingDirection(
            label="x", action={},
            reasoning="r",
            expected_value=ev,
            confidence=conf,
        )

    def test_no_constraints_returns_ev_times_conf(self):
        score, hard, soft = default_scorer(
            self._make_direction(ev=100, conf=0.8),
            self._make_outcome(),
            (),
        )
        self.assertEqual(hard, ())
        self.assertAlmostEqual(score, 80.0)
        self.assertEqual(soft, 0.0)

    def test_hard_violation_negative_infinity(self):
        c = Constraint(
            name="no",
            kind="hard",
            reason="r",
            evaluator=lambda d: (False, 0.0, "x"),
        )
        score, hard, _ = default_scorer(
            self._make_direction(),
            self._make_outcome(),
            (c,),
        )
        self.assertEqual(score, -math.inf)
        self.assertEqual(hard, ("no",))

    def test_soft_violation_subtracts(self):
        c = Constraint(
            name="s",
            kind="soft",
            reason="r",
            evaluator=lambda d: (False, 0.3, "low"),
        )
        score, hard, soft = default_scorer(
            self._make_direction(ev=100, conf=1.0),
            self._make_outcome(),
            (c,),
        )
        # base 100 - soft_penalty (1-0.3)=0.7 → 99.3
        self.assertAlmostEqual(score, 99.3)
        self.assertAlmostEqual(soft, 0.7)
        self.assertEqual(hard, ())

    def test_outcome_value_biases_score(self):
        score_low, _, _ = default_scorer(
            self._make_direction(ev=10, conf=1.0),
            self._make_outcome(value=0),
            (),
        )
        score_high, _, _ = default_scorer(
            self._make_direction(ev=10, conf=1.0),
            self._make_outcome(value=100),
            (),
        )
        self.assertGreater(score_high, score_low)


# ── deliberate() end-to-end ──────────────────────────────


def _outcome():
    return OutcomeSpec(
        what="activate",
        why="roas signal strong",
        measurable="7d ROAS ≥ 1.5",
        value_usd=100.0,
    )


def _dirs():
    return [
        ThinkingDirection(
            label="aggressive",
            action={"budget": 100},
            reasoning="ride momentum",
            expected_value=80, confidence=0.7,
        ),
        ThinkingDirection(
            label="conservative",
            action={"budget": 20},
            reasoning="preserve cap",
            expected_value=15, confidence=0.9,
        ),
    ]


class TestDeliberate(unittest.TestCase):
    def test_picks_highest_score_no_violation(self):
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
        )
        self.assertIsNotNone(d.decision)
        # Aggressive 80 × 0.7 = 56 + bias beats
        # conservative 15 × 0.9 = 13.5 + bias
        self.assertEqual(
            d.decision.label, "aggressive",
        )

    def test_hard_violation_disqualifies(self):
        def _no_aggressive(direction):
            if direction.label == "aggressive":
                return (False, 0.0, "over cap")
            return (True, 1.0, "ok")

        c = Constraint(
            name="budget_cap", kind="hard",
            reason="tripwire",
            evaluator=_no_aggressive,
        )
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
            constraints=[c],
        )
        self.assertEqual(
            d.decision.label, "conservative",
        )
        blocked = next(
            r for r in d.refines
            if r.direction_label == "aggressive"
        )
        self.assertEqual(
            blocked.hard_violations, ("budget_cap",),
        )

    def test_all_blocked_returns_no_decision(self):
        c = Constraint(
            name="all_no", kind="hard",
            reason="freeze",
            evaluator=lambda d: (False, 0.0, "nope"),
        )
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
            constraints=[c],
        )
        self.assertIsNone(d.decision)

    def test_empty_directions_raises(self):
        with self.assertRaises(ValueError):
            deliberate(
                outcome=_outcome(),
                directions=[],
            )

    def test_custom_scorer_injected(self):
        def _flat(direction, outcome, constraints):
            return (1.0 if direction.label == "x" else 0.0,
                    (), 0.0)

        dirs = [
            ThinkingDirection(
                label="x", action={}, reasoning="r",
            ),
            ThinkingDirection(
                label="y", action={}, reasoning="r",
            ),
        ]
        d = deliberate(
            outcome=_outcome(),
            directions=dirs,
            scorer=_flat,
        )
        self.assertEqual(d.decision.label, "x")

    def test_awareness_defaults(self):
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
        )
        self.assertEqual(
            d.awareness.loop_check, "aligned",
        )
        self.assertEqual(
            d.awareness.plumbing_vs_capability,
            "balanced",
        )

    def test_awareness_override(self):
        aw = SelfAwareness(
            loop_check="plumbing",
            dollar_distance=5,
            plumbing_vs_capability="plumbing",
        )
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
            awareness=aw,
        )
        self.assertEqual(
            d.awareness.loop_check, "plumbing",
        )

    def test_refine_steps_one_per_direction(self):
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
        )
        self.assertEqual(len(d.refines), 2)
        self.assertEqual(d.refines[0].iteration, 1)
        self.assertEqual(d.refines[1].iteration, 2)


# ── Rationale ledger integration ─────────────────────────


class TestRationaleEntries(unittest.TestCase):
    def test_entries_cover_every_pillar(self):
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
            constraints=[
                Constraint(
                    name="cap", kind="hard",
                    reason="tripwire",
                ),
            ],
        )
        entries = d.as_rationale_entries()
        kinds = [e["kind"] for e in entries]
        self.assertIn("goal", kinds)
        self.assertIn("option", kinds)
        self.assertIn("constraint", kinds)
        self.assertIn("gate", kinds)
        self.assertIn("meta", kinds)

    def test_no_gate_entry_when_all_blocked(self):
        c = Constraint(
            name="x", kind="hard", reason="r",
            evaluator=lambda d: (False, 0, "no"),
        )
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
            constraints=[c],
        )
        entries = d.as_rationale_entries()
        kinds = [e["kind"] for e in entries]
        self.assertNotIn("gate", kinds)


# ── Recent log ──────────────────────────────────────────


class TestRecentLog(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_record_and_retrieve(self):
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
        )
        record_deliberation(d)
        got = recent_deliberations(limit=5)
        self.assertEqual(len(got), 1)
        self.assertIs(got[0], d)

    def test_bounded_at_200(self):
        for _ in range(250):
            record_deliberation(deliberate(
                outcome=_outcome(),
                directions=_dirs(),
            ))
        got = recent_deliberations(limit=250)
        self.assertEqual(len(got), 200)

    def test_limit_clamped(self):
        record_deliberation(deliberate(
            outcome=_outcome(),
            directions=_dirs(),
        ))
        self.assertEqual(
            len(recent_deliberations(limit=10000)), 1,
        )


# ── MCP tool ────────────────────────────────────────────


class TestMcpTool(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_registered(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        names = {s.name for s in reg.list_tools()}
        self.assertIn("recent_deliberations", names)

    def test_empty_returns_zero(self):
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="recent_deliberations",
        ))
        self.assertTrue(res.ok)
        self.assertEqual(res.content["count"], 0)

    def test_records_surface(self):
        d = deliberate(
            outcome=_outcome(),
            directions=_dirs(),
        )
        record_deliberation(d)
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="recent_deliberations",
            arguments={"limit": 5},
        ))
        self.assertEqual(res.content["count"], 1)
        first = res.content["deliberations"][0]
        self.assertIn("outcome", first)
        self.assertIn("directions", first)
        self.assertIn("awareness", first)


if __name__ == "__main__":
    unittest.main()
