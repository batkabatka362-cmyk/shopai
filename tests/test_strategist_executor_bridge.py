"""Tests for engines.strategist_executor_bridge — W963-37."""
from __future__ import annotations

import os
from unittest.mock import patch

from engines.strategist_executor_bridge import (
    StrategistExecutorBridgeEngine,
)
from engines.strategist_executor_bridge.bridge import (
    BridgeReport,
    _impact_score,
    run_bridge,
    signal_template_map,
)


def _fake_strategist_data(
    source_signal="funnel",
    impact="high",
    confidence=0.9,
):
    return {
        "store_id": "x",
        "verdict": "intervene",
        "context": {"total_revenue_7d": 100.0},
        "recommendations": [
            {
                "action": "do X",
                "drill_command": "shopai x",
                "confidence": confidence,
                "impact": impact,
                "reasoning": "...",
                "source_signal": source_signal,
                "priority_score": confidence * (
                    1.0 if impact == "high"
                    else 0.6 if impact == "medium" else 0.3
                ),
            },
        ],
    }


# ── _impact_score ─────────────────────────────────────────


class TestImpactScore:
    def test_high(self):
        assert _impact_score("high") == 1.0

    def test_medium(self):
        assert _impact_score("medium") == 0.6

    def test_low(self):
        assert _impact_score("low") == 0.3


# ── signal_template_map ───────────────────────────────────


class TestSignalTemplateMap:
    def test_known_signals_present(self):
        m = signal_template_map()
        assert m["funnel"] == "increase_conversion"
        assert m["cold_start"] == "cold_start"


# ── run_bridge ────────────────────────────────────────────


class TestRunBridge:
    def test_empty_fleet(self):
        with patch(
            "engines.strategist_executor_bridge.bridge."
            "_list_fleet_stores",
            return_value=[],
        ):
            r = run_bridge(confirmed=False)
        assert r.total_stores_scanned == 0

    def test_strategist_failure_marks_error(self):
        with patch(
            "engines.strategist_executor_bridge.bridge."
            "_list_fleet_stores",
            return_value=["s1"],
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_strategist_for_store",
            return_value=None,
        ):
            r = run_bridge(confirmed=False)
        assert r.skip_reasons.get("strategist_failed") == 1
        assert r.decisions[0].verdict == "error"

    def test_no_recommendations_skipped(self):
        with patch(
            "engines.strategist_executor_bridge.bridge."
            "_list_fleet_stores",
            return_value=["s1"],
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_strategist_for_store",
            return_value={"recommendations": []},
        ):
            r = run_bridge(confirmed=False)
        assert (
            r.skip_reasons.get("no_recommendations") == 1
        )

    def test_below_floor_skipped(self):
        # confidence=0.3 × impact=low (0.3) = 0.09 < floor 0.6
        with patch(
            "engines.strategist_executor_bridge.bridge."
            "_list_fleet_stores",
            return_value=["s1"],
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_strategist_for_store",
            return_value=_fake_strategist_data(
                confidence=0.3, impact="low",
            ),
        ):
            r = run_bridge(confirmed=False)
        assert r.skip_reasons.get("below_floor") == 1

    def test_unknown_signal_skipped(self):
        with patch(
            "engines.strategist_executor_bridge.bridge."
            "_list_fleet_stores",
            return_value=["s1"],
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_strategist_for_store",
            return_value=_fake_strategist_data(
                source_signal="xyz_unknown",
            ),
        ):
            r = run_bridge(confirmed=False)
        assert (
            r.skip_reasons.get("no_template_for_signal")
            == 1
        )

    def test_high_score_composes_dry_run(self):
        with patch(
            "engines.strategist_executor_bridge.bridge."
            "_list_fleet_stores",
            return_value=["s1"],
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_strategist_for_store",
            return_value=_fake_strategist_data(),
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_execute_template",
            return_value=("plan_xyz", 0, ""),
        ):
            r = run_bridge(confirmed=False)
        assert r.composed_only == 1
        assert r.decisions[0].verdict == "composed"

    def test_confirmed_enqueues(self):
        with patch(
            "engines.strategist_executor_bridge.bridge."
            "_list_fleet_stores",
            return_value=["s1"],
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_strategist_for_store",
            return_value=_fake_strategist_data(),
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_execute_template",
            return_value=("plan_xyz", 5, ""),
        ):
            r = run_bridge(confirmed=True)
        assert r.enqueued_total == 5

    def test_executor_error_captured(self):
        with patch(
            "engines.strategist_executor_bridge.bridge."
            "_list_fleet_stores",
            return_value=["s1"],
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_strategist_for_store",
            return_value=_fake_strategist_data(),
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_execute_template",
            return_value=("", 0, "executor_error: X"),
        ):
            r = run_bridge(confirmed=True)
        assert r.decisions[0].verdict == "error"

    def test_store_filter_short_circuits(self):
        with patch(
            "engines.strategist_executor_bridge.bridge."
            "_list_fleet_stores",
            return_value=["s1", "s2", "s3"],
        ) as list_mock, patch(
            "engines.strategist_executor_bridge.bridge."
            "_strategist_for_store",
            return_value=_fake_strategist_data(),
        ), patch(
            "engines.strategist_executor_bridge.bridge."
            "_execute_template",
            return_value=("plan_x", 0, ""),
        ):
            r = run_bridge(
                confirmed=False, store_filter="onlyme",
            )
        assert not list_mock.called
        assert r.total_stores_scanned == 1
        assert r.decisions[0].store_id == "onlyme"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = StrategistExecutorBridgeEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = StrategistExecutorBridgeEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = StrategistExecutorBridgeEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = StrategistExecutorBridgeEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = StrategistExecutorBridgeEngine().run({})
        assert (
            r["meta"]["engine"]
            == "strategist_executor_bridge"
        )


class TestEngineActions:
    def test_double_gate_blocks(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(
                "SHOPAI_STRATEGIST_EXECUTOR_BRIDGE", None,
            )
            r = StrategistExecutorBridgeEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is False

    def test_both_gates_set(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_STRATEGIST_EXECUTOR_BRIDGE": "1"},
            clear=False,
        ):
            r = StrategistExecutorBridgeEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is True

    def test_invalid_floor_falls_back(self):
        r = StrategistExecutorBridgeEngine().run({
            "data": {"confidence_floor": "abc"},
        })
        assert r["data"]["confidence_floor"] == 0.6

    def test_floor_clamped_to_unit(self):
        r = StrategistExecutorBridgeEngine().run({
            "data": {"confidence_floor": 5.0},
        })
        assert r["data"]["confidence_floor"] == 1.0
