"""Deliberation observation → predict_outcome calibration wire tests.

When the order webhook back-fills a Deliberation, it now also
reports a predicted/actual pair to the engine_outcome_bus so
world_model_calibration can improve its predictions. Without
this wire, predict_outcome returns uncalibrated estimates
forever (the bus only calibrates when ``predicted`` is set on
the outcome; nothing else supplied that before this commit).

Test locks:
  * back-fill succeeds → calibration feed fires with
    predicted=deliberation.outcome.value_usd, actual=revenue
  * predicted=0 (no $-value goal declared) → no feed (noise)
  * missing decision_id → no back-fill, no feed
  * calibration sink failure isolated from back-fill
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.webhooks.order_handler import OrderWebhookHandler
from core.brain.structured_decision import (
    Constraint,
    Deliberation,
    OutcomeSpec,
    RefineStep,
    SelfAwareness,
    ThinkingDirection,
    record_deliberation,
    reset_recent_for_tests,
)


def _make_order(
    *, decision_id: str = "", total: str = "49.99",
):
    order: dict = {
        "id": "ord-calib-1",
        "total_price": total,
        "subtotal_price": total,
        "line_items": [{"sku": "S1", "quantity": 1}],
        "customer": {"id": "c-1"},
    }
    if decision_id:
        order["note_attributes"] = [{
            "name": "shopai_decision_id",
            "value": decision_id,
        }]
    return order


def _record_fake_deliberation(
    decision_id: str, *, value_usd: float = 0.0,
) -> Deliberation:
    """Stash a Deliberation in the recent log so the
    order_handler's back-fill path finds it. Constructed
    directly (not via ``deliberate()``) so we don't depend on
    a scorer and the fields stay minimal."""
    outcome = OutcomeSpec(
        what=f"test {decision_id}",
        why="calibration wire test",
        measurable="order revenue",
        value_usd=value_usd,
    )
    direction = ThinkingDirection(
        label="test",
        action="noop",
        reasoning="test-only",
    )
    d = Deliberation(
        outcome=outcome,
        directions=(direction,),
        constraints=(),
        refines=(),
        awareness=SelfAwareness(
            loop_check="aligned",
            dollar_distance=1,
            plumbing_vs_capability="capability",
        ),
        decision=direction,
        decision_id=decision_id,
    )
    record_deliberation(d)
    return d


class TestCalibrationWire(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_backfill_feeds_calibration_when_value_set(self):
        _record_fake_deliberation(
            "dec_wire_1", value_usd=45.0,
        )
        handler = OrderWebhookHandler()
        fake_bus = MagicMock()
        with patch(
            "core.integration.engine_outcome_bus"
            ".get_engine_outcome_bus",
            return_value=fake_bus,
        ):
            out = handler.handle_order_paid(
                _make_order(
                    decision_id="dec_wire_1",
                    total="49.99",
                ),
            )
        self.assertTrue(out.get("deliberation_observed"))
        self.assertTrue(out.get("calibration_fed"))
        # The bus saw one or more calls — find the calibration
        # one (engine=deliberation_calibration).
        calib_calls = [
            c for c in fake_bus.report.call_args_list
            if c.args
            and c.args[0].engine
            == "deliberation_calibration"
        ]
        self.assertEqual(len(calib_calls), 1)
        event = calib_calls[0].args[0]
        self.assertEqual(event.kpi, "revenue")
        self.assertAlmostEqual(event.value, 49.99, places=2)
        self.assertAlmostEqual(event.predicted, 45.0, places=2)
        self.assertEqual(event.rationale_id, "dec_wire_1")

    def test_zero_predicted_skips_calibration_feed(self):
        """Deliberations declared without a $-value outcome
        shouldn't spam the calibrator with predicted=0 pairs —
        that would bias the mean to zero."""
        _record_fake_deliberation(
            "dec_wire_2", value_usd=0.0,
        )
        handler = OrderWebhookHandler()
        fake_bus = MagicMock()
        with patch(
            "core.integration.engine_outcome_bus"
            ".get_engine_outcome_bus",
            return_value=fake_bus,
        ):
            out = handler.handle_order_paid(
                _make_order(
                    decision_id="dec_wire_2",
                    total="29.00",
                ),
            )
        self.assertTrue(out.get("deliberation_observed"))
        # calibration_fed not set or False
        self.assertFalse(out.get("calibration_fed", False))
        calib_calls = [
            c for c in fake_bus.report.call_args_list
            if c.args
            and c.args[0].engine
            == "deliberation_calibration"
        ]
        self.assertEqual(calib_calls, [])

    def test_no_decision_id_no_feed(self):
        handler = OrderWebhookHandler()
        fake_bus = MagicMock()
        with patch(
            "core.integration.engine_outcome_bus"
            ".get_engine_outcome_bus",
            return_value=fake_bus,
        ):
            out = handler.handle_order_paid(
                _make_order(total="20.00"),
            )
        # No decision_id → no back-fill attempted
        self.assertFalse(
            out.get("deliberation_observed", False),
        )
        calib_calls = [
            c for c in fake_bus.report.call_args_list
            if c.args
            and c.args[0].engine
            == "deliberation_calibration"
        ]
        self.assertEqual(calib_calls, [])

    def test_calibration_exception_isolated(self):
        """§4b.E failure isolation: a broken bus sink must
        not break the webhook."""
        _record_fake_deliberation(
            "dec_wire_3", value_usd=30.0,
        )

        def raising_bus():
            bus = MagicMock()
            bus.report.side_effect = RuntimeError("boom")
            return bus

        handler = OrderWebhookHandler()
        with patch(
            "core.integration.engine_outcome_bus"
            ".get_engine_outcome_bus",
            raising_bus,
        ):
            out = handler.handle_order_paid(
                _make_order(
                    decision_id="dec_wire_3",
                    total="35.00",
                ),
            )
        # Back-fill succeeded
        self.assertTrue(out.get("deliberation_observed"))
        # Calibration feed failed → recorded but didn't raise
        self.assertFalse(
            out.get("calibration_fed", True),
        )

    def test_unknown_decision_id_no_feed(self):
        """Decision_id supplied but no matching Deliberation
        → no back-fill, no calibration feed."""
        handler = OrderWebhookHandler()
        fake_bus = MagicMock()
        with patch(
            "core.integration.engine_outcome_bus"
            ".get_engine_outcome_bus",
            return_value=fake_bus,
        ):
            out = handler.handle_order_paid(
                _make_order(
                    decision_id="dec_nonexistent",
                    total="15.00",
                ),
            )
        self.assertFalse(
            out.get("deliberation_observed"),
        )
        calib_calls = [
            c for c in fake_bus.report.call_args_list
            if c.args
            and c.args[0].engine
            == "deliberation_calibration"
        ]
        self.assertEqual(calib_calls, [])


if __name__ == "__main__":
    unittest.main()
