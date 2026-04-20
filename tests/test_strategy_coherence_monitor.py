"""Strategy coherence monitor tests."""
from __future__ import annotations

import unittest

from core.brain import strategy_coherence_monitor as scm


class TestClause(unittest.TestCase):
    def test_bad_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            scm.StrategyClause(
                id="x", kind="bogus",  # type: ignore[arg-type]
                value="t",
            )

    def test_bad_tag_value_raises(self) -> None:
        with self.assertRaises(ValueError):
            scm.StrategyClause(
                id="x", kind="required_tag", value="",
            )

    def test_bad_numeric_value_raises(self) -> None:
        with self.assertRaises(ValueError):
            scm.StrategyClause(
                id="x",
                kind="max_stake_sum", value="NaN-string",
            )


class TestDeclare(unittest.TestCase):
    def setUp(self) -> None:
        self.m = scm.StrategyCoherenceMonitor()

    def test_blank_name_raises(self) -> None:
        clauses = [scm.StrategyClause(
            id="c", kind="required_tag", value="x",
        )]
        with self.assertRaises(ValueError):
            self.m.declare(name="", clauses=clauses)

    def test_empty_clauses_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.declare(name="x", clauses=[])

    def test_declare_stores(self) -> None:
        s = self.m.declare(
            name="high_aov_focus",
            clauses=[scm.StrategyClause(
                id="c", kind="required_tag",
                value="high_aov",
            )],
        )
        self.assertTrue(s.active)
        self.assertEqual(self.m.stats()["strategies"], 1)


class TestRecordAction(unittest.TestCase):
    def setUp(self) -> None:
        self.m = scm.StrategyCoherenceMonitor()
        self.m.declare(
            name="high_aov",
            strategy_id="s1",
            clauses=[scm.StrategyClause(
                id="req_high_aov",
                kind="required_tag",
                value="high_aov",
            )],
        )

    def test_blank_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record_action(kind="", stake=0.1)

    def test_bad_stake_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record_action(
                kind="k", stake=1.5,
            )

    def test_required_tag_missing_alerts(self) -> None:
        alerts = self.m.record_action(
            kind="launch", stake=0.1,
            tags=["low_aov"],
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].strategy_id, "s1")

    def test_required_tag_present_ok(self) -> None:
        alerts = self.m.record_action(
            kind="launch", stake=0.1,
            tags=["high_aov"],
        )
        self.assertEqual(alerts, [])

    def test_forbidden_tag(self) -> None:
        m = scm.StrategyCoherenceMonitor()
        m.declare(
            name="no_risky",
            clauses=[scm.StrategyClause(
                id="c", kind="forbidden_tag",
                value="risky",
            )],
        )
        alerts = m.record_action(
            kind="k", stake=0.1, tags=["risky"],
        )
        self.assertEqual(len(alerts), 1)

    def test_max_stake_sum(self) -> None:
        m = scm.StrategyCoherenceMonitor()
        m.declare(
            name="cap_spend",
            clauses=[scm.StrategyClause(
                id="cap",
                kind="max_stake_sum",
                value=1.0,
            )],
        )
        m.record_action(kind="k", stake=0.6)
        # cumulative = 0.6 — OK
        alerts = m.record_action(kind="k", stake=0.5)
        # cumulative = 1.1 > 1.0 — violation
        self.assertEqual(len(alerts), 1)

    def test_deactivated_strategy_skipped(self) -> None:
        self.m.deactivate("s1")
        alerts = self.m.record_action(
            kind="k", stake=0.1, tags=["low_aov"],
        )
        self.assertEqual(alerts, [])


class TestQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.m = scm.StrategyCoherenceMonitor()
        self.m.declare(
            name="s",
            strategy_id="s1",
            clauses=[scm.StrategyClause(
                id="c", kind="forbidden_tag", value="bad",
            )],
        )

    def test_strategy_get(self) -> None:
        self.assertIsNotNone(self.m.strategy("s1"))
        self.assertIsNone(self.m.strategy("nope"))

    def test_active_strategies(self) -> None:
        self.assertEqual(len(self.m.active_strategies()), 1)
        self.m.deactivate("s1")
        self.assertEqual(len(self.m.active_strategies()), 0)

    def test_alerts(self) -> None:
        self.m.record_action(
            kind="k", stake=0.1, tags=["bad"],
        )
        self.assertEqual(len(self.m.alerts()), 1)

    def test_violation_rate(self) -> None:
        self.m.record_action(
            kind="k", stake=0.1, tags=["bad"],
        )
        self.m.record_action(
            kind="k", stake=0.1, tags=["good"],
        )
        self.assertEqual(self.m.violation_rate(), 0.5)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        m = scm.StrategyCoherenceMonitor()
        m.declare(
            name="s",
            clauses=[scm.StrategyClause(
                id="c", kind="required_tag", value="x",
            )],
        )
        s = m.stats()
        self.assertEqual(s["strategies"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        m = scm.StrategyCoherenceMonitor()
        m.declare(
            name="s",
            clauses=[scm.StrategyClause(
                id="c", kind="required_tag", value="x",
            )],
        )
        m.record_action(kind="k", stake=0.1)
        self.assertGreater(m.reset(), 0)


class TestDict(unittest.TestCase):
    def test_clause_serialises(self) -> None:
        c = scm.StrategyClause(
            id="c", kind="required_tag", value="x",
        )
        d = c.as_dict()
        self.assertEqual(d["kind"], "required_tag")

    def test_strategy_serialises(self) -> None:
        m = scm.StrategyCoherenceMonitor()
        s = m.declare(
            name="s",
            clauses=[scm.StrategyClause(
                id="c", kind="required_tag", value="x",
            )],
        )
        d = s.as_dict()
        self.assertIn("clauses", d)

    def test_alert_serialises(self) -> None:
        m = scm.StrategyCoherenceMonitor()
        m.declare(
            name="s",
            clauses=[scm.StrategyClause(
                id="c", kind="forbidden_tag", value="bad",
            )],
        )
        alerts = m.record_action(
            kind="k", stake=0.1, tags=["bad"],
        )
        d = alerts[0].as_dict()
        self.assertIn("reason", d)


if __name__ == "__main__":
    unittest.main()
