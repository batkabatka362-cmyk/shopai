"""Tests for ``engines.store_design.design_recorder``.

This module bridges the store_design engine's recommendation
output into Phase 8 ``record_writeback`` so daily-brief +
engine summary surfaces register design activity, and the
recommendations become traceable in the action log.

Coverage:
  1. Successful run writes one event with aggregated counts.
  2. Failure status records ``success=False`` with the error.
  3. Non-dict / malformed input is ignored gracefully.
  4. store_id flows through to params.
  5. Engine flow integration: ``StoreDesignEngine.run`` now
     calls the recorder for each invocation.
"""
from __future__ import annotations

from unittest.mock import patch

from engines.store_design.design_recorder import (
    record_design_run,
)


class TestRecordDesignRun:

    def test_successful_run_records_aggregates(self):
        envelope = {
            "status": "success",
            "data": {
                "layout_recommendations": [
                    {"page": "homepage", "expected_impact": "10%"},
                    {"page": "collection", "expected_impact": "20%"},
                ],
                "color_palette": {
                    "primary": "#ff0000",
                    "secondary": "#00ff00",
                    "accent": "#0000ff",
                },
                "navigation": {
                    "primary_links": [
                        {"label": "Shop"}, {"label": "About"},
                    ],
                },
                "mobile_optimizations": [
                    {"type": "sticky_cta"},
                ],
                "estimated_conversion_lift": 0.15,
            },
            "meta": {"engine": "store_design"},
            "error": None,
        }
        with patch(
            "engines.store_design.design_recorder.record_writeback",
        ) as record_mock:
            record_design_run(envelope)

        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "store_design"
        assert kwargs["action_type"] == "generate_recommendations"
        assert kwargs["capability"] == (
            "SHOPIFY_DESIGN_RECOMMENDATIONS"
        )
        assert kwargs["success"] is True
        # Counts aggregated from the sub-blocks
        p = kwargs["params"]
        assert p["layout_count"] == 2
        assert p["palette_count"] == 3
        assert p["navigation_count"] == 2
        assert p["mobile_optimization_count"] == 1
        assert p["total_recommendations"] == 8
        # Metrics carry the lift estimate + source tag
        m = kwargs["metrics"]
        assert m["estimated_conversion_lift"] == 0.15
        assert m["lift_source"] == "heuristic_estimate"

    def test_failure_records_error(self):
        envelope = {
            "status": "fail",
            "data": {},
            "meta": {"engine": "store_design"},
            "error": "Brand info is required",
        }
        with patch(
            "engines.store_design.design_recorder.record_writeback",
        ) as record_mock:
            record_design_run(envelope)
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"] == "Brand info is required"
        # Counts zero on failure since data is empty
        assert kwargs["params"]["total_recommendations"] == 0

    def test_non_dict_input_ignored(self):
        with patch(
            "engines.store_design.design_recorder.record_writeback",
        ) as record_mock:
            record_design_run(None)
            record_design_run("not a dict")
            record_design_run(42)
        record_mock.assert_not_called()

    def test_store_id_propagates_to_params(self):
        envelope = {
            "status": "success",
            "data": {},
            "meta": {},
            "error": None,
        }
        with patch(
            "engines.store_design.design_recorder.record_writeback",
        ) as record_mock:
            record_design_run(envelope, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"

    def test_missing_data_field_handled(self):
        """Engine envelope without a ``data`` field shouldn't
        crash -- counts degrade to 0."""
        envelope = {"status": "success"}  # no data, no meta
        with patch(
            "engines.store_design.design_recorder.record_writeback",
        ) as record_mock:
            record_design_run(envelope)
        params = record_mock.call_args.kwargs["params"]
        assert params["total_recommendations"] == 0

    def test_bad_lift_value_falls_back_to_zero(self):
        envelope = {
            "status": "success",
            "data": {
                "estimated_conversion_lift": "not-a-number",
            },
        }
        with patch(
            "engines.store_design.design_recorder.record_writeback",
        ) as record_mock:
            record_design_run(envelope)
        metrics = record_mock.call_args.kwargs["metrics"]
        assert metrics["estimated_conversion_lift"] == 0.0

    def test_failure_without_explicit_error_synthesizes_one(self):
        envelope = {
            "status": "fail",
            "data": {},
            "error": None,
        }
        with patch(
            "engines.store_design.design_recorder.record_writeback",
        ) as record_mock:
            record_design_run(envelope)
        assert (
            record_mock.call_args.kwargs["error"]
            == "design engine failure"
        )


class TestEngineFlowWiring:
    """The store_design engine's flow now calls the recorder
    on every run. Verify the wiring instead of duplicating the
    recorder's own contract."""

    def test_flow_calls_recorder_on_success(self):
        from engines.store_design.flow import StoreDesignEngine

        with patch(
            "engines.store_design.design_recorder."
            "record_design_run",
        ) as recorder_mock:
            StoreDesignEngine().run({
                "status": "success",
                "data": {
                    "brand": {"name": "Test", "tone": "friendly"},
                    "products": [],
                    "analytics": {"bounce_rate": 0.5},
                },
                "meta": {},
                "error": None,
            })
        recorder_mock.assert_called_once()
        # The envelope passed to the recorder should be the
        # full engine output dict.
        envelope = recorder_mock.call_args.args[0]
        assert envelope["status"] == "success"
        assert "layout_recommendations" in envelope["data"]

    def test_recorder_raise_doesnt_break_engine(self):
        """A raising recorder must not propagate into the engine's
        public output. The engine still returns its envelope."""
        from engines.store_design.flow import StoreDesignEngine

        with patch(
            "engines.store_design.design_recorder."
            "record_design_run",
            side_effect=RuntimeError("recorder is broken"),
        ):
            result = StoreDesignEngine().run({
                "status": "success",
                "data": {
                    "brand": {"name": "Test"},
                    "products": [],
                    "analytics": {},
                },
                "meta": {},
                "error": None,
            })
        # Engine still produced a healthy envelope
        assert result["status"] == "success"
        assert "layout_recommendations" in result["data"]
