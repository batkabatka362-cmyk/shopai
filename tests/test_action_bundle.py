"""Action bundle tests."""
from __future__ import annotations

import unittest

from core.brain import action_bundle as ab


class TestAction(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            ab.BundleAction(name="", execute=lambda c: {})


class TestBundle(unittest.TestCase):
    def test_blank_bundle_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            ab.ActionBundle("")

    def test_add_and_list(self) -> None:
        bundle = ab.ActionBundle("b")
        bundle.add(ab.BundleAction(
            name="a", execute=lambda c: {},
        ))
        self.assertEqual(len(bundle.actions()), 1)


class TestHappyPath(unittest.TestCase):
    def test_all_succeed_no_rollback(self) -> None:
        calls: list[str] = []

        def mk(name):
            def exec_(ctx):
                calls.append(name)
                return {name + "_done": True}
            return exec_

        bundle = ab.ActionBundle(
            "launch",
            actions=[
                ab.BundleAction(name="a", execute=mk("a")),
                ab.BundleAction(name="b", execute=mk("b")),
                ab.BundleAction(name="c", execute=mk("c")),
            ],
        )
        report = bundle.run()
        self.assertTrue(report.success)
        self.assertFalse(report.rolled_back)
        self.assertEqual(calls, ["a", "b", "c"])

    def test_output_flows_into_context(self) -> None:
        seen_in_second: dict[str, Any] = {}

        def first(ctx):
            return {"shared_key": "value"}

        def second(ctx):
            seen_in_second.update(ctx["context"])
            return {}

        bundle = ab.ActionBundle(
            "b",
            actions=[
                ab.BundleAction(name="first", execute=first),
                ab.BundleAction(name="second", execute=second),
            ],
        )
        bundle.run()
        self.assertEqual(seen_in_second.get("shared_key"), "value")


class TestRollback(unittest.TestCase):
    def test_failure_triggers_compensation(self) -> None:
        compensated: list[str] = []

        def mk_ok(name):
            return lambda ctx: {name: True}

        def mk_comp(name):
            def comp(ctx):
                compensated.append(name)
            return comp

        def failing(ctx):
            raise RuntimeError("boom")

        bundle = ab.ActionBundle(
            "b",
            actions=[
                ab.BundleAction(
                    name="a", execute=mk_ok("a"),
                    compensate=mk_comp("a"),
                ),
                ab.BundleAction(
                    name="b", execute=mk_ok("b"),
                    compensate=mk_comp("b"),
                ),
                ab.BundleAction(
                    name="fails", execute=failing,
                ),
                ab.BundleAction(
                    name="c", execute=mk_ok("c"),
                ),
            ],
        )
        report = bundle.run()
        self.assertFalse(report.success)
        self.assertTrue(report.rolled_back)
        # Compensation walks backwards: b then a
        self.assertEqual(compensated, ["b", "a"])
        # c never executed
        c_step = next(s for s in report.steps if s.name == "c")
        self.assertEqual(c_step.status, "skipped")

    def test_no_compensate_still_records_ok(self) -> None:
        def failing(ctx):
            raise RuntimeError("x")

        bundle = ab.ActionBundle(
            "b",
            actions=[
                ab.BundleAction(
                    name="a", execute=lambda c: {},
                ),   # no compensator
                ab.BundleAction(name="bad", execute=failing),
            ],
        )
        report = bundle.run()
        self.assertFalse(report.success)
        self.assertFalse(report.rolled_back)
        # a remains ok (no compensator to call)
        a_step = next(s for s in report.steps if s.name == "a")
        self.assertEqual(a_step.status, "ok")

    def test_compensate_failure_recorded(self) -> None:
        def bad_comp(ctx):
            raise RuntimeError("rollback failed")

        def failing(ctx):
            raise RuntimeError("boom")

        bundle = ab.ActionBundle(
            "b",
            actions=[
                ab.BundleAction(
                    name="a",
                    execute=lambda c: {"key": 1},
                    compensate=bad_comp,
                ),
                ab.BundleAction(name="bad", execute=failing),
            ],
        )
        report = bundle.run()
        self.assertFalse(report.success)
        a_step = next(s for s in report.steps if s.name == "a")
        self.assertIn("compensate_failed", a_step.error)


class TestOptional(unittest.TestCase):
    def test_optional_failure_does_not_stop_bundle(self) -> None:
        calls: list[str] = []

        def notify(ctx):
            raise RuntimeError("slack down")

        def final(ctx):
            calls.append("final")
            return {}

        bundle = ab.ActionBundle(
            "b",
            actions=[
                ab.BundleAction(
                    name="core", execute=lambda c: calls.append("core") or {},
                ),
                ab.BundleAction(
                    name="notify", execute=notify, optional=True,
                ),
                ab.BundleAction(name="final", execute=final),
            ],
        )
        report = bundle.run()
        self.assertTrue(report.success)
        self.assertEqual(calls, ["core", "final"])


class TestNonDictReturn(unittest.TestCase):
    def test_non_dict_wrapped_as_result(self) -> None:
        bundle = ab.ActionBundle(
            "b",
            actions=[
                ab.BundleAction(
                    name="x", execute=lambda c: "plain string",
                ),
            ],
        )
        report = bundle.run()
        step = report.steps[0]
        self.assertEqual(
            step.output, {"result": "plain string"},
        )


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        bundle = ab.ActionBundle(
            "b",
            actions=[
                ab.BundleAction(
                    name="a", execute=lambda c: {},
                    compensate=lambda ctx: None,
                ),
                ab.BundleAction(
                    name="b", execute=lambda c: {},
                    optional=True,
                ),
            ],
        )
        s = bundle.stats()
        self.assertEqual(s["step_count"], 2)
        self.assertEqual(s["steps_with_compensate"], 1)
        self.assertEqual(s["optional_steps"], 1)


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        bundle = ab.ActionBundle(
            "b",
            actions=[
                ab.BundleAction(name="a", execute=lambda c: {}),
            ],
        )
        d = bundle.run().as_dict()
        self.assertIn("steps", d)
        self.assertIn("success", d)


if __name__ == "__main__":
    unittest.main()
