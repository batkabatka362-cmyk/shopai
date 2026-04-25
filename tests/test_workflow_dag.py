"""Workflow DAG tests."""
from __future__ import annotations

import unittest

from core.system import workflow_dag as wdag


class TestBasic(unittest.TestCase):
    def test_simple_chain(self) -> None:
        w = wdag.WorkflowDAG()
        w.add("a", lambda ctx, ins: 1)
        w.add("b", lambda ctx, ins: ins["a"] + 1, deps=["a"])
        rep = w.execute()
        self.assertEqual(rep.status, "ok")
        self.assertEqual(rep.outcome("b").output, 2)

    def test_parallel_branches(self) -> None:
        w = wdag.WorkflowDAG()
        w.add("root", lambda ctx, ins: {})
        w.add("a", lambda ctx, ins: "a", deps=["root"])
        w.add("b", lambda ctx, ins: "b", deps=["root"])
        w.add("join", lambda ctx, ins: ins["a"] + ins["b"],
              deps=["a", "b"])
        rep = w.execute()
        self.assertEqual(rep.outcome("join").output, "ab")

    def test_context_passed(self) -> None:
        w = wdag.WorkflowDAG()
        w.add("echo", lambda ctx, ins: ctx["x"])
        rep = w.execute(context={"x": 42})
        self.assertEqual(rep.outcome("echo").output, 42)

    def test_blank_name_raises(self) -> None:
        w = wdag.WorkflowDAG()
        with self.assertRaises(ValueError):
            w.add("", lambda ctx, ins: None)

    def test_duplicate_name_raises(self) -> None:
        w = wdag.WorkflowDAG()
        w.add("x", lambda ctx, ins: 1)
        with self.assertRaises(ValueError):
            w.add("x", lambda ctx, ins: 2)


class TestDependencies(unittest.TestCase):
    def test_unknown_dep_raises(self) -> None:
        w = wdag.WorkflowDAG()
        w.add("x", lambda ctx, ins: 1, deps=["missing"])
        with self.assertRaises(ValueError):
            w.execute()

    def test_cycle_detected(self) -> None:
        w = wdag.WorkflowDAG()
        w.add("a", lambda ctx, ins: 1, deps=["b"])
        w.add("b", lambda ctx, ins: 1, deps=["a"])
        with self.assertRaises(ValueError):
            w.execute()


class TestFailure(unittest.TestCase):
    def test_failure_skips_downstream(self) -> None:
        w = wdag.WorkflowDAG()
        def boom(ctx, ins):
            raise RuntimeError("oops")
        w.add("bad", boom)
        w.add("after", lambda ctx, ins: "ok", deps=["bad"])
        rep = w.execute()
        self.assertEqual(rep.status, "partial")
        self.assertEqual(rep.outcome("bad").status, "failed")
        self.assertEqual(rep.outcome("after").status, "skipped")

    def test_retries_then_success(self) -> None:
        calls = {"n": 0}
        def flaky(ctx, ins):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("transient")
            return "finally"
        w = wdag.WorkflowDAG()
        w.add("flaky", flaky, retries=3)
        rep = w.execute()
        self.assertEqual(rep.outcome("flaky").status, "ok")
        self.assertEqual(rep.outcome("flaky").attempts, 3)

    def test_exhausted_retries_fail(self) -> None:
        def always_bad(ctx, ins):
            raise RuntimeError("nope")
        w = wdag.WorkflowDAG()
        w.add("x", always_bad, retries=2)
        rep = w.execute()
        self.assertEqual(rep.outcome("x").status, "failed")
        self.assertEqual(rep.outcome("x").attempts, 3)

    def test_abort_stops_workflow(self) -> None:
        def boom(ctx, ins):
            raise RuntimeError("abort trigger")
        w = wdag.WorkflowDAG()
        w.add("a", boom, on_fail="abort")
        w.add("later", lambda ctx, ins: "never", deps=["a"])
        rep = w.execute()
        self.assertEqual(rep.status, "aborted")
        # Even downstream "later" should be marked skipped
        self.assertEqual(rep.outcome("later").status, "skipped")

    def test_optional_failure_does_not_block(self) -> None:
        def flaky(ctx, ins):
            raise RuntimeError("oops")
        w = wdag.WorkflowDAG()
        w.add("optional_step", flaky, optional=True)
        w.add("main", lambda ctx, ins: "ok")
        rep = w.execute()
        self.assertEqual(rep.outcome("main").status, "ok")


class TestVisualise(unittest.TestCase):
    def test_visualise_lists_root_and_deps(self) -> None:
        w = wdag.WorkflowDAG()
        w.add("root", lambda ctx, ins: 1)
        w.add("child", lambda ctx, ins: 1, deps=["root"])
        text = w.visualise()
        self.assertIn("root  ← (root)", text)
        self.assertIn("child  ← root", text)


class TestReport(unittest.TestCase):
    def test_as_dict(self) -> None:
        w = wdag.WorkflowDAG()
        w.add("a", lambda ctx, ins: 1)
        rep = w.execute()
        d = rep.as_dict()
        self.assertEqual(d["status"], "ok")
        self.assertIn("outcomes", d)


if __name__ == "__main__":
    unittest.main()
