"""Outcome recorder tests."""
from __future__ import annotations

import os
import unittest

from core.attribution import outcome_recorder as rec


class TestEvent(unittest.TestCase):
    def test_serialises(self) -> None:
        e = rec.OutcomeEvent(
            kind="purchase", ok=True, revenue=29.99,
        )
        d = e.as_dict()
        self.assertEqual(d["kind"], "purchase")
        self.assertTrue(d["ok"])


class TestRecordHooksDisabled(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = os.environ.pop("SHOPAI_BRAIN_HOOKS", None)

    def tearDown(self) -> None:
        if self._orig is not None:
            os.environ["SHOPAI_BRAIN_HOOKS"] = self._orig

    def test_blank_kind_raises(self) -> None:
        r = rec.OutcomeRecorder()
        with self.assertRaises(ValueError):
            r.record(rec.OutcomeEvent(kind="", ok=True))

    def test_no_hooks_returns_noop(self) -> None:
        r = rec.OutcomeRecorder()
        result = r.record(rec.OutcomeEvent(
            kind="purchase", ok=True, revenue=29.99,
        ))
        self.assertEqual(result.recorded, {})
        self.assertIn("disabled", result.note)


class TestRecordHooksEnabled(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = os.environ.get("SHOPAI_BRAIN_HOOKS")
        os.environ["SHOPAI_BRAIN_HOOKS"] = "1"
        # Reset singletons so each test starts fresh
        from core.brain import brain_facade
        brain_facade._META_REASONER = None
        brain_facade._WORLD_MODEL_UPDATER = None
        brain_facade._CAPABILITY_REGISTRY = None
        brain_facade._REVENUE_FUNNEL = None
        brain_facade._PREDICTIVE_ALERTER = None
        brain_facade._MOOD_MODEL = None

    def tearDown(self) -> None:
        if self._orig is None:
            os.environ.pop("SHOPAI_BRAIN_HOOKS", None)
        else:
            os.environ["SHOPAI_BRAIN_HOOKS"] = self._orig

    def test_purchase_records_funnel_mood(self) -> None:
        r = rec.OutcomeRecorder()
        result = r.record(rec.OutcomeEvent(
            kind="purchase", ok=True, revenue=50,
            kpi="revenue", kpi_value=50,
        ))
        self.assertTrue(result.recorded.get("funnel"))
        self.assertTrue(result.recorded.get("mood"))
        self.assertTrue(result.recorded.get("kpi"))

    def test_calibration_requires_both(self) -> None:
        r = rec.OutcomeRecorder()
        # Only decision_id without confidence → no calibration
        result = r.record(rec.OutcomeEvent(
            kind="purchase", ok=True,
            decision_id="d1",
        ))
        self.assertNotIn("calibration", result.recorded)
        # Both supplied → calibration fires
        result = r.record(rec.OutcomeEvent(
            kind="purchase", ok=True,
            decision_id="d1", claimed_confidence=0.8,
        ))
        self.assertTrue(result.recorded.get("calibration"))

    def test_signals_recorded(self) -> None:
        r = rec.OutcomeRecorder()
        result = r.record(rec.OutcomeEvent(
            kind="purchase", ok=True,
            decision_id="d1",
            claimed_confidence=0.7,
            signals=("cpm", "ctr"),
        ))
        self.assertTrue(result.recorded.get("signal_use"))

    def test_prediction_pair(self) -> None:
        r = rec.OutcomeRecorder()
        result = r.record(rec.OutcomeEvent(
            kind="purchase", ok=True,
            predictor_id="campaign.c1.roas",
            predicted_value=3.0,
            observed_value=2.5,
        ))
        self.assertTrue(result.recorded.get("prediction"))

    def test_capability_tracked(self) -> None:
        r = rec.OutcomeRecorder()
        # Pre-register the capability
        from core.brain.brain_facade import brain
        brain().register_capability(
            name="launch_sku", scope="shopify",
        )
        result = r.record(rec.OutcomeEvent(
            kind="purchase", ok=True,
            capability_name="launch_sku",
        ))
        self.assertTrue(result.recorded.get("capability"))

    def test_return_records_return_stage(self) -> None:
        r = rec.OutcomeRecorder()
        result = r.record_return(revenue=15)
        self.assertTrue(result.recorded.get("funnel"))
        self.assertTrue(result.recorded.get("mood"))


class TestConvenience(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = os.environ.get("SHOPAI_BRAIN_HOOKS")
        os.environ["SHOPAI_BRAIN_HOOKS"] = "1"
        from core.brain import brain_facade
        brain_facade._META_REASONER = None
        brain_facade._WORLD_MODEL_UPDATER = None
        brain_facade._CAPABILITY_REGISTRY = None
        brain_facade._REVENUE_FUNNEL = None
        brain_facade._PREDICTIVE_ALERTER = None
        brain_facade._MOOD_MODEL = None

    def tearDown(self) -> None:
        if self._orig is None:
            os.environ.pop("SHOPAI_BRAIN_HOOKS", None)
        else:
            os.environ["SHOPAI_BRAIN_HOOKS"] = self._orig

    def test_record_purchase(self) -> None:
        r = rec.OutcomeRecorder()
        result = r.record_purchase(revenue=30)
        self.assertTrue(result.recorded.get("funnel"))

    def test_record_cancel(self) -> None:
        r = rec.OutcomeRecorder()
        result = r.record_cancel(
            decision_id="d1", claimed_confidence=0.5,
        )
        self.assertTrue(result.recorded.get("calibration"))
        self.assertTrue(result.recorded.get("mood"))


class TestStats(unittest.TestCase):
    def test_stats_counter(self) -> None:
        os.environ.pop("SHOPAI_BRAIN_HOOKS", None)
        r = rec.OutcomeRecorder()
        r.record(rec.OutcomeEvent(kind="purchase", ok=True))
        # Disabled so count stays 0
        self.assertEqual(r.stats()["recorded_count"], 0)

    def test_stats_exposes_flag(self) -> None:
        os.environ["SHOPAI_BRAIN_HOOKS"] = "1"
        try:
            r = rec.OutcomeRecorder()
            self.assertTrue(r.stats()["hooks_enabled"])
        finally:
            os.environ.pop("SHOPAI_BRAIN_HOOKS", None)


class TestReset(unittest.TestCase):
    def test_reset_counter(self) -> None:
        os.environ["SHOPAI_BRAIN_HOOKS"] = "1"
        try:
            r = rec.OutcomeRecorder()
            r.record(rec.OutcomeEvent(
                kind="purchase", ok=True,
            ))
            # Counter increments only when hooks enabled
            self.assertEqual(r.reset(), 1)
            self.assertEqual(r.stats()["recorded_count"], 0)
        finally:
            os.environ.pop("SHOPAI_BRAIN_HOOKS", None)


if __name__ == "__main__":
    unittest.main()
