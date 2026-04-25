"""Behavioral constraint registry tests."""
from __future__ import annotations

import unittest

from core.brain import behavioral_constraint_registry as bcr


class TestConstraint(unittest.TestCase):
    def test_bad_severity_raises(self) -> None:
        with self.assertRaises(ValueError):
            bcr.BehavioralConstraint(
                id="x", name="n",
                predicate=lambda a, c: False,
                severity="urgent",   # type: ignore[arg-type]
            )


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self.r = bcr.BehavioralConstraintRegistry()

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.register(
                name="",
                predicate=lambda a, c: False,
            )

    def test_register_creates(self) -> None:
        c = self.r.register(
            name="no_price_at_night",
            predicate=lambda a, c: True,
        )
        self.assertTrue(c.active)


class TestEvaluate(unittest.TestCase):
    def setUp(self) -> None:
        self.r = bcr.BehavioralConstraintRegistry()
        self.r.register(
            constraint_id="night_price",
            name="no_price_at_night",
            predicate=lambda a, c: (
                a.get("kind") == "update_price"
                and int(c.get("hour", 12)) >= 21
            ),
            severity="warn",
            description="don't touch pricing after 9pm",
        )

    def test_missing_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.evaluate(action={}, context={})

    def test_no_violation(self) -> None:
        result = self.r.evaluate(
            action={"kind": "update_price"},
            context={"hour": 10},
        )
        self.assertEqual(result.alerts, [])

    def test_violation_recorded(self) -> None:
        result = self.r.evaluate(
            action={"kind": "update_price"},
            context={"hour": 23},
        )
        self.assertEqual(len(result.alerts), 1)
        self.assertEqual(
            result.alerts[0].severity, "warn",
        )
        self.assertFalse(result.any_severe)

    def test_severe_flag(self) -> None:
        r = bcr.BehavioralConstraintRegistry()
        r.register(
            name="no_friday_budget",
            predicate=lambda a, c: True,
            severity="severe",
        )
        result = r.evaluate(
            action={"kind": "raise_budget"},
        )
        self.assertTrue(result.any_severe)

    def test_deactivated_skipped(self) -> None:
        cid = list(self.r._constraints.keys())[0]
        self.r.deactivate(cid)
        result = self.r.evaluate(
            action={"kind": "update_price"},
            context={"hour": 23},
        )
        self.assertEqual(result.alerts, [])

    def test_raising_predicate_skipped(self) -> None:
        def boom(a, c):
            raise RuntimeError("bug")

        self.r.register(
            name="bad",
            predicate=boom,
            severity="warn",
        )
        # Should not crash
        result = self.r.evaluate(
            action={"kind": "x"},
        )
        self.assertIsInstance(result.alerts, list)


class TestRemove(unittest.TestCase):
    def test_remove(self) -> None:
        r = bcr.BehavioralConstraintRegistry()
        c = r.register(
            name="x",
            predicate=lambda a, c: True,
        )
        self.assertTrue(r.remove(c.id))
        self.assertFalse(r.remove("nope"))


class TestQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.r = bcr.BehavioralConstraintRegistry()
        self.r.register(
            name="x",
            predicate=lambda a, c: True,
        )

    def test_active_constraints(self) -> None:
        self.assertEqual(
            len(self.r.active_constraints()), 1,
        )

    def test_violation_counts(self) -> None:
        self.r.evaluate(action={"kind": "k"})
        self.r.evaluate(action={"kind": "k"})
        counts = self.r.violation_counts()
        cid = list(counts.keys())[0]
        self.assertEqual(counts[cid], 2)

    def test_recent_alerts(self) -> None:
        self.r.evaluate(action={"kind": "k"})
        self.assertEqual(len(self.r.recent_alerts()), 1)

    def test_stats(self) -> None:
        self.r.evaluate(action={"kind": "k"})
        s = self.r.stats()
        self.assertEqual(s["constraints"], 1)
        self.assertEqual(s["alerts"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        r = bcr.BehavioralConstraintRegistry()
        r.register(
            name="x",
            predicate=lambda a, c: True,
        )
        r.evaluate(action={"kind": "k"})
        self.assertGreater(r.reset(), 0)


class TestDict(unittest.TestCase):
    def test_alert_serialises(self) -> None:
        r = bcr.BehavioralConstraintRegistry()
        r.register(
            name="x",
            predicate=lambda a, c: True,
        )
        result = r.evaluate(action={"kind": "k"})
        d = result.alerts[0].as_dict()
        self.assertIn("severity", d)

    def test_result_serialises(self) -> None:
        r = bcr.BehavioralConstraintRegistry()
        r.register(
            name="x",
            predicate=lambda a, c: True,
        )
        d = r.evaluate(action={"kind": "k"}).as_dict()
        self.assertIn("alerts", d)


if __name__ == "__main__":
    unittest.main()
