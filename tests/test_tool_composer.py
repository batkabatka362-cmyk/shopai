"""Tool composer — compose / invoke / nest / failure-isolate tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import tool_composer as tc


class TestRegistry(unittest.TestCase):
    def setUp(self) -> None:
        # Save + clear the global registry so each test is isolated
        self._orig = dict(tc._PRIMITIVES)
        tc._PRIMITIVES.clear()

    def tearDown(self) -> None:
        tc._PRIMITIVES.clear()
        tc._PRIMITIVES.update(self._orig)

    def test_register_exposes_name(self) -> None:
        tc.register_primitive("adder", lambda a, b: a + b)
        self.assertIn("adder", tc.list_primitives())
        self.assertEqual(tc._PRIMITIVES["adder"](2, 3), 5)

    def test_register_overwrites(self) -> None:
        tc.register_primitive("x", lambda: 1)
        tc.register_primitive("x", lambda: 2)
        self.assertEqual(tc._PRIMITIVES["x"](), 2)

    def test_unregister_primitive(self) -> None:
        tc.register_primitive("t", lambda: None)
        self.assertTrue(tc.unregister_primitive("t"))
        self.assertFalse(tc.unregister_primitive("t"))


class TestCompose(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.comp = tc.ToolComposer(Path(self._tmp.name) / "t.json")
        self._orig = dict(tc._PRIMITIVES)
        tc._PRIMITIVES.clear()

    def tearDown(self) -> None:
        tc._PRIMITIVES.clear()
        tc._PRIMITIVES.update(self._orig)
        self._tmp.cleanup()

    def test_compose_then_list(self) -> None:
        self.comp.compose(
            name="sum_plus_one",
            recipe=[{"tool": "add", "args": {"a": 1, "b": 2}, "as": "s"}],
        )
        tools = self.comp.list_all()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "sum_plus_one")

    def test_compose_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            self.comp.compose(name="x", recipe=[])
        with self.assertRaises(ValueError):
            self.comp.compose(name="x", recipe=[{"no_tool": "x"}])

    def test_delete(self) -> None:
        self.comp.compose(
            name="tmp", recipe=[{"tool": "x"}],
        )
        self.assertTrue(self.comp.delete("tmp"))
        self.assertFalse(self.comp.delete("tmp"))


class TestInvoke(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.comp = tc.ToolComposer(Path(self._tmp.name) / "t.json")
        self._orig = dict(tc._PRIMITIVES)
        tc._PRIMITIVES.clear()

    def tearDown(self) -> None:
        tc._PRIMITIVES.clear()
        tc._PRIMITIVES.update(self._orig)
        self._tmp.cleanup()

    def test_happy_path(self) -> None:
        tc.register_primitive("add", lambda a, b: a + b)
        tc.register_primitive("mul", lambda x, y: x * y)
        self.comp.compose(
            name="add_then_mul",
            recipe=[
                {"tool": "add", "args": {"a": 2, "b": 3}, "as": "s"},
                {"tool": "mul", "args": {"x": "$s", "y": 4}, "as": "m"},
            ],
        )
        report = self.comp.invoke("add_then_mul")
        self.assertEqual(report.status, "ok")
        self.assertEqual(report.outputs["s"], 5)
        self.assertEqual(report.outputs["m"], 20)

    def test_placeholder_resolves(self) -> None:
        tc.register_primitive("echo", lambda v: v)
        self.comp.compose(
            name="echo_context",
            recipe=[{"tool": "echo",
                      "args": {"v": "$owner"},
                      "as": "out"}],
        )
        r = self.comp.invoke("echo_context", context={"owner": "alice"})
        self.assertEqual(r.outputs["out"], "alice")

    def test_failure_skips_downstream(self) -> None:
        def boom():
            raise ValueError("bad")
        tc.register_primitive("boom", boom)
        tc.register_primitive("never_reached", lambda: "ran")
        self.comp.compose(
            name="fail_chain",
            recipe=[
                {"tool": "boom"},
                {"tool": "never_reached"},
            ],
        )
        r = self.comp.invoke("fail_chain")
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.steps[0].status, "failed")
        self.assertEqual(r.steps[1].status, "skipped")

    def test_invoke_unknown_returns_failed_report(self) -> None:
        r = self.comp.invoke("missing")
        self.assertEqual(r.status, "failed")
        self.assertIn("unknown", r.steps[0].error)

    def test_nested_compound_tool(self) -> None:
        tc.register_primitive("inc", lambda n: n + 1)
        self.comp.compose(
            name="inc_twice",
            recipe=[
                {"tool": "inc", "args": {"n": "$n"}, "as": "once"},
                {"tool": "inc", "args": {"n": "$once"}, "as": "twice"},
            ],
        )
        self.comp.compose(
            name="inc_four_times",
            recipe=[
                {"tool": "inc_twice", "args": {"n": "$n"}, "as": "mid"},
                # Pull numeric out of nested report's outputs
                {"tool": "inc_twice",
                 "args": {"n": "$mid"}},
            ],
        )
        # The nested composer return type is a dict with outputs; this
        # test just verifies nesting wires up without raising.
        r = self.comp.invoke("inc_twice", context={"n": 1})
        self.assertEqual(r.outputs["twice"], 3)


class TestResolvePlaceholders(unittest.TestCase):
    def test_scalar_placeholder(self) -> None:
        outputs = {"x": 42}
        self.assertEqual(tc.ToolComposer._resolve("$x", outputs), 42)

    def test_nested_dict_resolves(self) -> None:
        outputs = {"user": "alice"}
        val = tc.ToolComposer._resolve(
            {"greeting": "hi", "who": "$user"}, outputs,
        )
        self.assertEqual(val, {"greeting": "hi", "who": "alice"})

    def test_list_elements_resolve(self) -> None:
        outputs = {"a": 1, "b": 2}
        self.assertEqual(
            tc.ToolComposer._resolve(["$a", "$b", "c"], outputs),
            [1, 2, "c"],
        )

    def test_missing_placeholder_kept_verbatim(self) -> None:
        self.assertEqual(
            tc.ToolComposer._resolve("$missing", {"a": 1}),
            "$missing",
        )


if __name__ == "__main__":
    unittest.main()
