"""Temporal logic tests."""
from __future__ import annotations

import unittest

from core.brain import temporal_logic as tl


class TestAlways(unittest.TestCase):
    def test_holds_everywhere_true(self) -> None:
        trace = [{"kind": "a"}, {"kind": "a"}, {"kind": "a"}]
        r = tl.evaluate(tl.Always(tl.kind_is("a"), name="all_a"), trace)
        self.assertTrue(r.ok)

    def test_broken_at_step(self) -> None:
        trace = [{"kind": "a"}, {"kind": "b"}, {"kind": "a"}]
        r = tl.evaluate(tl.Always(tl.kind_is("a")), trace)
        self.assertFalse(r.ok)
        self.assertEqual(r.violation_index, 1)


class TestEventually(unittest.TestCase):
    def test_witness_found(self) -> None:
        trace = [{"kind": "a"}, {"kind": "b"}, {"kind": "c"}]
        r = tl.evaluate(tl.Eventually(tl.kind_is("c")), trace)
        self.assertTrue(r.ok)
        self.assertEqual(r.witness_index, 2)

    def test_never_witnessed_false(self) -> None:
        trace = [{"kind": "a"}, {"kind": "b"}]
        r = tl.evaluate(tl.Eventually(tl.kind_is("c")), trace)
        self.assertFalse(r.ok)


class TestNever(unittest.TestCase):
    def test_never_triggered(self) -> None:
        trace = [{"kind": "a"}, {"kind": "a"}]
        r = tl.evaluate(tl.Never(tl.kind_is("refund")), trace)
        self.assertTrue(r.ok)

    def test_triggered_once_fails(self) -> None:
        trace = [{"kind": "order"}, {"kind": "refund"}]
        r = tl.evaluate(tl.Never(tl.kind_is("refund")), trace)
        self.assertFalse(r.ok)
        self.assertEqual(r.violation_index, 1)


class TestNext(unittest.TestCase):
    def test_next_holds(self) -> None:
        trace = [{"kind": "a"}, {"kind": "b"}]
        r = tl.evaluate(tl.Next(tl.kind_is("b")), trace)
        self.assertTrue(r.ok)

    def test_next_fails(self) -> None:
        trace = [{"kind": "a"}, {"kind": "c"}]
        r = tl.evaluate(tl.Next(tl.kind_is("b")), trace)
        self.assertFalse(r.ok)

    def test_next_requires_successor(self) -> None:
        r = tl.evaluate(tl.Next(tl.kind_is("anything")), [{"kind": "a"}])
        self.assertFalse(r.ok)


class TestImplies(unittest.TestCase):
    def test_implication_satisfied(self) -> None:
        trace = [
            {"kind": "kill"}, {"kind": "wait"},
            {"kind": "launch"},
        ]
        r = tl.evaluate(tl.Implies(
            antecedent=tl.kind_is("kill"),
            consequent=tl.kind_is("launch"),
        ), trace)
        self.assertTrue(r.ok)

    def test_implication_violated(self) -> None:
        trace = [
            {"kind": "kill"}, {"kind": "wait"}, {"kind": "wait"},
        ]
        r = tl.evaluate(tl.Implies(
            antecedent=tl.kind_is("kill"),
            consequent=tl.kind_is("launch"),
        ), trace)
        self.assertFalse(r.ok)

    def test_within_window(self) -> None:
        # Antecedent at 0, consequent at 5 — outside within=2 window
        trace = [
            {"kind": "kill"},
            {"kind": "wait"}, {"kind": "wait"},
            {"kind": "wait"}, {"kind": "wait"},
            {"kind": "launch"},
        ]
        r = tl.evaluate(tl.Implies(
            antecedent=tl.kind_is("kill"),
            consequent=tl.kind_is("launch"),
            within=2,
        ), trace)
        self.assertFalse(r.ok)

    def test_no_antecedent_vacuously_true(self) -> None:
        trace = [{"kind": "a"}, {"kind": "b"}]
        r = tl.evaluate(tl.Implies(
            antecedent=tl.kind_is("never"),
            consequent=tl.kind_is("a"),
        ), trace)
        self.assertTrue(r.ok)


class TestPredicates(unittest.TestCase):
    def test_kind_in(self) -> None:
        trace = [{"kind": "a"}, {"kind": "b"}]
        pred = tl.kind_in({"a", "b"})
        self.assertTrue(pred(trace[0]))
        self.assertTrue(pred(trace[1]))

    def test_field_matches(self) -> None:
        pred = tl.field_matches("status", "active")
        self.assertTrue(pred({"status": "active"}))
        self.assertFalse(pred({"status": "killed"}))

    def test_all_of_and_any_of(self) -> None:
        pred_all = tl.all_of(
            tl.kind_is("a"), tl.field_matches("x", 1),
        )
        pred_any = tl.any_of(
            tl.kind_is("z"), tl.field_matches("x", 1),
        )
        ev = {"kind": "a", "x": 1}
        self.assertTrue(pred_all(ev))
        self.assertTrue(pred_any(ev))

    def test_predicate_errors_handled(self) -> None:
        def boom(ev):
            raise RuntimeError("bad")
        trace = [{"kind": "a"}]
        r = tl.evaluate(tl.Always(boom), trace)
        self.assertFalse(r.ok)


class TestBatchCheckRules(unittest.TestCase):
    def test_check_rules_returns_one_per_rule(self) -> None:
        trace = [{"kind": "a"}, {"kind": "b"}]
        rules = [
            tl.Always(tl.kind_in({"a", "b"})),
            tl.Eventually(tl.kind_is("b")),
            tl.Never(tl.kind_is("refund")),
        ]
        results = tl.check_rules(trace, rules)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.ok for r in results))


class TestDict(unittest.TestCase):
    def test_result_as_dict(self) -> None:
        trace = [{"kind": "a"}]
        r = tl.evaluate(
            tl.Always(tl.kind_is("a"), name="all_a"), trace,
        )
        d = r.as_dict()
        self.assertEqual(d["formula"], "always:all_a")
        self.assertTrue(d["ok"])


if __name__ == "__main__":
    unittest.main()
