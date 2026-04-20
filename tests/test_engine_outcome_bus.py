"""Tests for core.integration.engine_outcome_bus (A wire-in)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.integration.engine_outcome_bus import (
    BusReport,
    EngineOutcome,
    EngineOutcomeBus,
    get_engine_outcome_bus,
    reset_engine_outcome_bus_for_tests,
)


def _outcome(**kw):
    defaults = dict(
        engine="pricing_engine",
        kpi="margin",
        value=0.22,
        ok=True,
    )
    defaults.update(kw)
    return EngineOutcome(**defaults)


def _bus(**deps):
    defaults = dict(
        rulebook=MagicMock(),
        pattern_miner=MagicMock(
            mine=MagicMock(
                return_value=MagicMock(
                    proposals_emitted=0,
                ),
            ),
        ),
        world_calibration=MagicMock(),
        trust_calibrator=MagicMock(),
        freshness_tracker=MagicMock(),
        mine_every=3,
        pattern_window=20,
        now_fn=lambda: 1_000_000.0,
    )
    defaults.update(deps)
    return EngineOutcomeBus(**defaults)


class TestConfig(unittest.TestCase):
    def test_bad_mine_every(self):
        with self.assertRaises(ValueError):
            EngineOutcomeBus(mine_every=0)

    def test_pattern_window_smaller_than_mine_every(self):
        with self.assertRaises(ValueError):
            EngineOutcomeBus(
                mine_every=10, pattern_window=5,
            )


class TestReport(unittest.TestCase):
    def test_requires_engine_and_kpi(self):
        bus = _bus()
        with self.assertRaises(ValueError):
            bus.report(
                EngineOutcome(
                    engine="", kpi="k",
                    value=1, ok=True,
                ),
            )

    def test_non_engineoutcome_raises(self):
        bus = _bus()
        with self.assertRaises(TypeError):
            bus.report({"engine": "x"})

    def test_happy_path_fans_out(self):
        bus = _bus()
        report = bus.report(_outcome(source="cj"))
        self.assertIn("source_trust", report.sinks_invoked)
        self.assertIn("freshness", report.sinks_invoked)

    def test_no_source_skips_trust(self):
        bus = _bus()
        report = bus.report(_outcome(source=""))
        self.assertNotIn(
            "source_trust", report.sinks_invoked,
        )
        self.assertIn(
            "freshness", report.sinks_invoked,
        )

    def test_no_predicted_skips_calibration(self):
        bus = _bus()
        report = bus.report(_outcome())
        self.assertNotIn(
            "world_calibration",
            report.sinks_invoked,
        )

    def test_predicted_triggers_calibration(self):
        calib = MagicMock()
        bus = _bus(world_calibration=calib)
        bus.report(_outcome(predicted=2.0, value=1.5))
        calib.record_outcome.assert_called_once_with(
            "margin", predicted=2.0, actual=1.5,
        )

    def test_sink_exception_captured(self):
        broken_trust = MagicMock()
        broken_trust.record_outcome.side_effect = (
            RuntimeError("db gone")
        )
        bus = _bus(trust_calibrator=broken_trust)
        report = bus.report(_outcome(source="cj"))
        self.assertIn(
            "source_trust", report.sink_errors,
        )
        self.assertIn(
            "freshness", report.sinks_invoked,
        )

    def test_ts_auto_populated(self):
        bus = _bus()
        o = _outcome()
        self.assertEqual(o.ts, 0.0)
        bus.report(o)
        self.assertEqual(o.ts, 1_000_000.0)


class TestPatternMining(unittest.TestCase):
    def test_mines_every_n_reports(self):
        miner = MagicMock()
        miner.mine.return_value = MagicMock(
            proposals_emitted=2,
        )
        bus = _bus(pattern_miner=miner, mine_every=3)
        bus.report(_outcome())
        bus.report(_outcome())
        self.assertEqual(miner.mine.call_count, 0)
        report = bus.report(_outcome())
        self.assertTrue(report.pattern_miner_ran)
        self.assertEqual(report.pattern_proposals, 2)
        self.assertEqual(miner.mine.call_count, 1)

    def test_miner_exception_captured(self):
        miner = MagicMock()
        miner.mine.side_effect = RuntimeError("oops")
        bus = _bus(pattern_miner=miner, mine_every=1)
        report = bus.report(_outcome())
        self.assertIn(
            "pattern_miner", report.sink_errors,
        )

    def test_miner_receives_buffer_snapshot(self):
        miner = MagicMock()
        miner.mine.return_value = MagicMock(
            proposals_emitted=0,
        )
        bus = _bus(pattern_miner=miner, mine_every=2)
        bus.report(_outcome(kpi="margin", value=0.1))
        bus.report(_outcome(kpi="roas", value=2.0))
        events = miner.mine.call_args.args[0]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kpi"], "margin")
        self.assertEqual(events[1]["kpi"], "roas")


class TestBuffer(unittest.TestCase):
    def test_buffer_bounded(self):
        bus = _bus(
            mine_every=5, pattern_window=5,
        )
        for i in range(10):
            bus.report(_outcome(value=float(i)))
        self.assertEqual(bus.stats()["buffer_size"], 5)

    def test_recent_returns_tail(self):
        bus = _bus(
            mine_every=10, pattern_window=10,
        )
        for i in range(4):
            bus.report(_outcome(value=float(i)))
        out = bus.recent(limit=2)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[-1].value, 3.0)


class TestSingleton(unittest.TestCase):
    def test_singleton(self):
        reset_engine_outcome_bus_for_tests()
        try:
            a = get_engine_outcome_bus()
            b = get_engine_outcome_bus()
            self.assertIs(a, b)
        finally:
            reset_engine_outcome_bus_for_tests()


class TestDicts(unittest.TestCase):
    def test_outcome_dict(self):
        o = _outcome()
        d = o.as_dict()
        self.assertIn("engine", d)

    def test_report_dict(self):
        r = BusReport(event_count=3)
        d = r.as_dict()
        self.assertEqual(d["event_count"], 3)


if __name__ == "__main__":
    unittest.main()
