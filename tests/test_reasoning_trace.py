"""Reasoning trace tests."""
from __future__ import annotations

import unittest

from core.brain import reasoning_trace as rt


class TestTraceNode(unittest.TestCase):
    def test_blank_subsystem_raises(self) -> None:
        with self.assertRaises(ValueError):
            rt.TraceNode(subsystem="", note="x")

    def test_negative_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            rt.TraceNode(subsystem="x", note="y", weight=-1)

    def test_ts_auto_filled(self) -> None:
        n = rt.TraceNode(subsystem="x", note="y")
        self.assertGreater(n.ts, 0)


class TestStart(unittest.TestCase):
    def test_start_returns_id(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("should we kill ad 42?")
        self.assertTrue(tid)
        self.assertTrue(t.is_active(tid))

    def test_blank_question_raises(self) -> None:
        t = rt.ReasoningTracer()
        with self.assertRaises(ValueError):
            t.start("")

    def test_explicit_trace_id(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("q", trace_id="custom")
        self.assertEqual(tid, "custom")

    def test_duplicate_trace_id_raises(self) -> None:
        t = rt.ReasoningTracer()
        t.start("q", trace_id="dup")
        with self.assertRaises(ValueError):
            t.start("q2", trace_id="dup")


class TestAdd(unittest.TestCase):
    def setUp(self) -> None:
        self.t = rt.ReasoningTracer()
        self.tid = self.t.start("q")

    def test_add_node(self) -> None:
        self.t.add(
            self.tid,
            subsystem="case_based",
            note="found 3 similar",
            output={"count": 3},
        )
        trace = self.t.get(self.tid)
        self.assertEqual(len(trace.nodes), 1)
        self.assertEqual(trace.nodes[0].subsystem, "case_based")

    def test_add_unknown_trace_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.add("nope", subsystem="x", note="y")

    def test_add_after_commit_raises(self) -> None:
        self.t.commit(self.tid, verdict="ok")
        with self.assertRaises(ValueError):
            self.t.add(
                self.tid, subsystem="x", note="post-commit",
            )


class TestCommit(unittest.TestCase):
    def setUp(self) -> None:
        self.t = rt.ReasoningTracer()

    def test_commit_closes_trace(self) -> None:
        tid = self.t.start("q")
        self.t.add(tid, subsystem="x", note="y")
        finalised = self.t.commit(
            tid, verdict="confident", action={"kind": "kill"},
        )
        self.assertEqual(finalised.final_verdict, "confident")
        self.assertEqual(
            finalised.final_action, {"kind": "kill"},
        )
        self.assertFalse(self.t.is_active(tid))

    def test_commit_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.commit("nope", verdict="x")


class TestAbandon(unittest.TestCase):
    def test_abandon_drops_trace(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("q")
        self.assertTrue(t.abandon(tid))
        self.assertFalse(t.is_active(tid))

    def test_abandon_unknown_false(self) -> None:
        t = rt.ReasoningTracer()
        self.assertFalse(t.abandon("nope"))


class TestQuery(unittest.TestCase):
    def test_get_defensive_copy(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("q")
        t.add(tid, subsystem="x", note="y")
        snapshot = t.get(tid)
        # Mutating the returned copy must not affect the live trace
        snapshot.nodes.clear()
        self.assertEqual(len(t.get(tid).nodes), 1)

    def test_recent_newest_first(self) -> None:
        t = rt.ReasoningTracer()
        for i in range(3):
            tid = t.start(f"q{i}")
            t.commit(tid, verdict="x")
        recent = t.recent(limit=2)
        self.assertEqual(len(recent), 2)

    def test_recent_committed_only_default(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("open")
        # Commit one, leave one open
        tid2 = t.start("closed")
        t.commit(tid2, verdict="x")
        recent = t.recent(committed_only=True)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].trace_id, tid2)
        _ = tid   # silence

    def test_subsystems_consulted(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("q")
        t.add(tid, subsystem="a", note="x")
        t.add(tid, subsystem="b", note="y")
        t.add(tid, subsystem="a", note="again")
        trace = t.get(tid)
        self.assertEqual(trace.subsystems_consulted, ["a", "b"])


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("q1")
        t.start("q2")
        t.commit(tid, verdict="x")
        s = t.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["committed"], 1)
        self.assertEqual(s["active"], 1)


class TestClear(unittest.TestCase):
    def test_clear(self) -> None:
        t = rt.ReasoningTracer()
        t.start("a")
        t.start("b")
        self.assertEqual(t.clear(), 2)
        self.assertEqual(t.stats()["total"], 0)


class TestDuration(unittest.TestCase):
    def test_duration_zero_before_commit(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("q")
        self.assertEqual(t.get(tid).duration_s, 0.0)

    def test_duration_positive_after_commit(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("q")
        t.commit(tid, verdict="x")
        self.assertGreaterEqual(t.get(tid).duration_s, 0.0)


class TestDict(unittest.TestCase):
    def test_trace_serialises(self) -> None:
        t = rt.ReasoningTracer()
        tid = t.start("q")
        t.add(tid, subsystem="a", note="n")
        t.commit(tid, verdict="v", action={"kind": "x"})
        d = t.get(tid).as_dict()
        self.assertIn("nodes", d)
        self.assertIn("final_action", d)
        self.assertEqual(d["subsystems_consulted"], ["a"])

    def test_node_serialises(self) -> None:
        n = rt.TraceNode(
            subsystem="s", note="x",
            output={"k": 1}, weight=0.5,
        )
        d = n.as_dict()
        self.assertEqual(d["weight"], 0.5)


if __name__ == "__main__":
    unittest.main()
