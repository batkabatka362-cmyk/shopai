"""Behaviour tree tests."""
from __future__ import annotations

import unittest

from core.brain import behaviour_tree as bt


class TestSequence(unittest.TestCase):
    def test_all_succeed(self) -> None:
        seq = bt.Sequence(
            "s",
            children=[
                bt.Action("a", lambda c: bt.BTStatus.SUCCESS),
                bt.Action("b", lambda c: bt.BTStatus.SUCCESS),
            ],
        )
        self.assertEqual(seq.tick({}), bt.BTStatus.SUCCESS)

    def test_first_failure_short_circuits(self) -> None:
        called: list[str] = []

        def make(name, status):
            def fn(_c):
                called.append(name)
                return status
            return fn

        seq = bt.Sequence(
            "s",
            children=[
                bt.Action("a", make("a", bt.BTStatus.SUCCESS)),
                bt.Action("b", make("b", bt.BTStatus.FAILURE)),
                bt.Action("c", make("c", bt.BTStatus.SUCCESS)),
            ],
        )
        self.assertEqual(seq.tick({}), bt.BTStatus.FAILURE)
        # c should NOT be called
        self.assertEqual(called, ["a", "b"])

    def test_running_propagates(self) -> None:
        seq = bt.Sequence(
            "s",
            children=[
                bt.Action("a", lambda c: bt.BTStatus.RUNNING),
                bt.Action("b", lambda c: bt.BTStatus.SUCCESS),
            ],
        )
        self.assertEqual(seq.tick({}), bt.BTStatus.RUNNING)


class TestSelector(unittest.TestCase):
    def test_first_success_short_circuits(self) -> None:
        called: list[str] = []

        def make(name, status):
            def fn(_c):
                called.append(name)
                return status
            return fn

        sel = bt.Selector(
            "s",
            children=[
                bt.Action("a", make("a", bt.BTStatus.FAILURE)),
                bt.Action("b", make("b", bt.BTStatus.SUCCESS)),
                bt.Action("c", make("c", bt.BTStatus.SUCCESS)),
            ],
        )
        self.assertEqual(sel.tick({}), bt.BTStatus.SUCCESS)
        self.assertEqual(called, ["a", "b"])  # c skipped

    def test_all_fail_returns_failure(self) -> None:
        sel = bt.Selector(
            "s",
            children=[
                bt.Action("a", lambda c: bt.BTStatus.FAILURE),
                bt.Action("b", lambda c: bt.BTStatus.FAILURE),
            ],
        )
        self.assertEqual(sel.tick({}), bt.BTStatus.FAILURE)


class TestParallel(unittest.TestCase):
    def test_required_successes_met(self) -> None:
        par = bt.Parallel(
            "p",
            children=[
                bt.Action("a", lambda c: bt.BTStatus.SUCCESS),
                bt.Action("b", lambda c: bt.BTStatus.FAILURE),
                bt.Action("c", lambda c: bt.BTStatus.SUCCESS),
            ],
            required_successes=2,
        )
        self.assertEqual(par.tick({}), bt.BTStatus.SUCCESS)

    def test_required_unmet_returns_failure(self) -> None:
        par = bt.Parallel(
            "p",
            children=[
                bt.Action("a", lambda c: bt.BTStatus.SUCCESS),
                bt.Action("b", lambda c: bt.BTStatus.FAILURE),
            ],
            required_successes=2,
        )
        self.assertEqual(par.tick({}), bt.BTStatus.FAILURE)

    def test_running_keeps_alive(self) -> None:
        par = bt.Parallel(
            "p",
            children=[
                bt.Action("a", lambda c: bt.BTStatus.SUCCESS),
                bt.Action("b", lambda c: bt.BTStatus.RUNNING),
            ],
            required_successes=2,
        )
        self.assertEqual(par.tick({}), bt.BTStatus.RUNNING)


class TestInverter(unittest.TestCase):
    def test_flips_success_to_failure(self) -> None:
        inv = bt.Inverter(
            "i",
            child=bt.Action("a", lambda c: bt.BTStatus.SUCCESS),
        )
        self.assertEqual(inv.tick({}), bt.BTStatus.FAILURE)

    def test_flips_failure_to_success(self) -> None:
        inv = bt.Inverter(
            "i",
            child=bt.Action("a", lambda c: bt.BTStatus.FAILURE),
        )
        self.assertEqual(inv.tick({}), bt.BTStatus.SUCCESS)

    def test_running_passthrough(self) -> None:
        inv = bt.Inverter(
            "i",
            child=bt.Action("a", lambda c: bt.BTStatus.RUNNING),
        )
        self.assertEqual(inv.tick({}), bt.BTStatus.RUNNING)


class TestCondition(unittest.TestCase):
    def test_predicate_true(self) -> None:
        cond = bt.Condition("c", predicate=lambda ctx: ctx.get("ok"))
        self.assertEqual(cond.tick({"ok": True}), bt.BTStatus.SUCCESS)

    def test_predicate_false(self) -> None:
        cond = bt.Condition("c", predicate=lambda ctx: ctx.get("ok"))
        self.assertEqual(cond.tick({}), bt.BTStatus.FAILURE)

    def test_predicate_raise_treated_failure(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        self.assertEqual(
            bt.Condition("c", predicate=boom).tick({}),
            bt.BTStatus.FAILURE,
        )


class TestAction(unittest.TestCase):
    def test_returns_bool(self) -> None:
        self.assertEqual(
            bt.Action("a", fn=lambda c: True).tick({}),
            bt.BTStatus.SUCCESS,
        )
        self.assertEqual(
            bt.Action("a", fn=lambda c: False).tick({}),
            bt.BTStatus.FAILURE,
        )

    def test_returns_none_treated_failure(self) -> None:
        self.assertEqual(
            bt.Action("a", fn=lambda c: None).tick({}),
            bt.BTStatus.FAILURE,
        )

    def test_action_raises_failure(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        self.assertEqual(
            bt.Action("a", fn=boom).tick({}),
            bt.BTStatus.FAILURE,
        )


class TestTree(unittest.TestCase):
    def test_tree_runs_root(self) -> None:
        tree = bt.BehaviourTree(
            "t",
            root=bt.Action("a", lambda c: bt.BTStatus.SUCCESS),
        )
        self.assertEqual(tree.tick({}), bt.BTStatus.SUCCESS)
        self.assertEqual(tree.tick_count, 1)
        self.assertEqual(tree.last_status, bt.BTStatus.SUCCESS)

    def test_tree_stats_reset(self) -> None:
        tree = bt.BehaviourTree(
            "t",
            root=bt.Action("a", lambda c: bt.BTStatus.SUCCESS),
        )
        tree.tick({})
        tree.reset_stats()
        self.assertEqual(tree.tick_count, 0)
        self.assertIsNone(tree.last_status)


class TestComposition(unittest.TestCase):
    def test_real_playbook(self) -> None:
        # If ad has high ROAS → scale; else if has data → kill;
        # else gather more data.
        scale_ran = []
        kill_ran = []
        gather_ran = []

        tree = bt.BehaviourTree(
            "kill_or_scale",
            root=bt.Selector(
                "main",
                children=[
                    bt.Sequence(
                        "scale_path",
                        children=[
                            bt.Condition(
                                "good_roas",
                                predicate=lambda c: c.get("roas", 0) > 2.0,
                            ),
                            bt.Action(
                                "scale",
                                fn=lambda c: scale_ran.append(c) or True,
                            ),
                        ],
                    ),
                    bt.Sequence(
                        "kill_path",
                        children=[
                            bt.Condition(
                                "have_data",
                                predicate=lambda c: c.get("samples", 0) > 30,
                            ),
                            bt.Action(
                                "kill",
                                fn=lambda c: kill_ran.append(c) or True,
                            ),
                        ],
                    ),
                    bt.Action(
                        "gather",
                        fn=lambda c: gather_ran.append(c) or True,
                    ),
                ],
            ),
        )
        # High ROAS → scale chosen
        tree.tick({"roas": 3.0, "samples": 50})
        self.assertEqual(len(scale_ran), 1)
        self.assertEqual(len(kill_ran), 0)
        # Low ROAS but enough data → kill chosen
        tree.tick({"roas": 0.5, "samples": 50})
        self.assertEqual(len(kill_ran), 1)
        # Low ROAS, no data → gather
        tree.tick({"roas": 0.5, "samples": 1})
        self.assertEqual(len(gather_ran), 1)


class TestDict(unittest.TestCase):
    def test_node_serialise(self) -> None:
        seq = bt.Sequence(
            "s",
            children=[
                bt.Condition("c", predicate=lambda c: True),
                bt.Action("a", fn=lambda c: True),
            ],
        )
        d = seq.as_dict()
        self.assertEqual(d["node"], "Sequence")
        self.assertEqual(len(d["children"]), 2)


if __name__ == "__main__":
    unittest.main()
