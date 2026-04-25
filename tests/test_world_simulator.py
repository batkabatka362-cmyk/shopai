"""World simulator tests."""
from __future__ import annotations

import unittest

from core.brain import world_simulator as ws


class TestRegister(unittest.TestCase):
    def test_blank_kind_raises(self) -> None:
        s = ws.WorldSimulator()
        with self.assertRaises(ValueError):
            s.register("", lambda st, a: st)

    def test_duplicate_rejected(self) -> None:
        s = ws.WorldSimulator()
        s.register("k", lambda st, a: st)
        with self.assertRaises(ValueError):
            s.register("k", lambda st, a: st)

    def test_overwrite_allowed(self) -> None:
        s = ws.WorldSimulator()
        s.register("k", lambda st, a: st)
        s.register("k", lambda st, a: st, overwrite=True)

    def test_unregister(self) -> None:
        s = ws.WorldSimulator()
        s.register("k", lambda st, a: st)
        self.assertTrue(s.unregister("k"))
        self.assertFalse(s.unregister("k"))

    def test_kinds_sorted(self) -> None:
        s = ws.WorldSimulator()
        s.register("b", lambda st, a: st)
        s.register("a", lambda st, a: st)
        self.assertEqual(s.kinds(), ["a", "b"])


class TestSeedAndReset(unittest.TestCase):
    def test_seed_deep_copies(self) -> None:
        s = ws.WorldSimulator()
        original = {"x": [1, 2, 3]}
        s.seed(original)
        original["x"].append(4)
        self.assertEqual(s.state()["x"], [1, 2, 3])

    def test_reset_clears(self) -> None:
        s = ws.WorldSimulator()
        s.seed({"a": 1})
        s.reset()
        self.assertEqual(s.state(), {})


class TestApply(unittest.TestCase):
    def test_apply_known_kind(self) -> None:
        s = ws.WorldSimulator()
        s.register(
            "inc",
            lambda st, a: {**st, "n": st.get("n", 0) + a.get("by", 0)},
        )
        s.seed({"n": 0})
        report = s.apply([
            {"kind": "inc", "by": 2},
            {"kind": "inc", "by": 3},
        ])
        self.assertEqual(s.state()["n"], 5)
        self.assertEqual(len(report.applied), 2)

    def test_apply_unknown_kind_skipped(self) -> None:
        s = ws.WorldSimulator()
        report = s.apply([{"kind": "ghost"}])
        self.assertEqual(len(report.applied), 0)
        self.assertEqual(len(report.skipped), 1)
        self.assertIn("no transition", report.skipped[0]["reason"])

    def test_missing_kind_skipped(self) -> None:
        s = ws.WorldSimulator()
        report = s.apply([{"x": 1}])
        self.assertEqual(len(report.skipped), 1)
        self.assertIn("missing kind", report.skipped[0]["reason"])

    def test_raising_transition_captured(self) -> None:
        def boom(st, a):
            raise RuntimeError("x")

        s = ws.WorldSimulator()
        s.register("bad", boom)
        report = s.apply([{"kind": "bad"}])
        self.assertEqual(len(report.applied), 0)
        self.assertEqual(len(report.skipped), 1)
        self.assertIn("raised", report.skipped[0]["reason"])

    def test_non_dict_return_skipped(self) -> None:
        s = ws.WorldSimulator()
        s.register("weird", lambda st, a: "not a dict")
        report = s.apply([{"kind": "weird"}])
        self.assertEqual(len(report.skipped), 1)


class TestPreview(unittest.TestCase):
    def test_preview_does_not_mutate(self) -> None:
        s = ws.WorldSimulator()
        s.register(
            "inc",
            lambda st, a: {**st, "n": st.get("n", 0) + 1},
        )
        s.seed({"n": 5})
        report = s.preview([{"kind": "inc"}, {"kind": "inc"}])
        self.assertEqual(report.final_state["n"], 7)
        # Stored state untouched
        self.assertEqual(s.state()["n"], 5)


class TestDiff(unittest.TestCase):
    def test_diff_changed_keys(self) -> None:
        s = ws.WorldSimulator()
        s.register("set_x", lambda st, a: {**st, "x": a["v"]})
        s.seed({"x": 1})
        report = s.apply([{"kind": "set_x", "v": 2}])
        self.assertIn("x", report.applied[0].changed_keys)

    def test_diff_added_keys(self) -> None:
        s = ws.WorldSimulator()
        s.register(
            "add_y",
            lambda st, a: {**st, "y": 1},
        )
        s.seed({})
        report = s.apply([{"kind": "add_y"}])
        self.assertIn("y", report.applied[0].added_keys)


class TestDefaultTransitions(unittest.TestCase):
    def setUp(self) -> None:
        self.s = ws.WorldSimulator()
        for k, fn in ws.default_transitions().items():
            self.s.register(k, fn)

    def test_set_price_updates_products(self) -> None:
        self.s.seed({"products": {"p1": {"price": 10.0}}})
        self.s.apply([
            {"kind": "set_price", "sku": "p1", "price": 25.0},
        ])
        self.assertEqual(
            self.s.state()["products"]["p1"]["price"], 25.0,
        )

    def test_adjust_inventory(self) -> None:
        self.s.seed({"products": {"p1": {"on_hand": 10}}})
        self.s.apply([
            {"kind": "adjust_inventory", "sku": "p1", "delta": -3},
        ])
        self.assertEqual(
            self.s.state()["products"]["p1"]["on_hand"], 7,
        )

    def test_set_ad_budget(self) -> None:
        self.s.apply([
            {"kind": "set_ad_budget", "ad_id": "a1",
             "daily_usd": 20.0},
        ])
        self.assertEqual(
            self.s.state()["ads"]["a1"]["daily_usd"], 20.0,
        )

    def test_blank_sku_noop(self) -> None:
        before = self.s.state()
        self.s.apply([
            {"kind": "set_price", "sku": "", "price": 1},
        ])
        self.assertEqual(self.s.state(), before)


class TestStatsDict(unittest.TestCase):
    def test_stats_shape(self) -> None:
        s = ws.WorldSimulator()
        s.register("k", lambda st, a: st)
        s.seed({"x": 1})
        stats = s.stats()
        self.assertEqual(stats["registered_kinds"], 1)
        self.assertIn("x", stats["state_keys"])

    def test_report_serialises(self) -> None:
        s = ws.WorldSimulator()
        s.register("set_x", lambda st, a: {**st, "x": 1})
        report = s.apply([{"kind": "set_x"}])
        d = report.as_dict()
        self.assertIn("applied", d)
        self.assertIn("skipped", d)


if __name__ == "__main__":
    unittest.main()
