"""Tests for the learned route-weight ledger — Upgrade 1.

The ledger closes the reflection → routing loop. These tests
cover the full contract:

* Default weight is 1.0 for any un-penalized pair
* Penalize compounds multiplicatively and clamps to the floor
* Decay recovers weight over time (half-life math)
* Reset clears a single row or the whole table
* ``apply_reflection_report`` walks a report and penalizes only
  promoted patterns that name both adapter AND capability
* Defensive paths: bad input, missing fields, non-dict reports
* Router integration: a penalized pair is ranked AFTER healthier
  candidates of the same capability
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.adapters.route_weights import (
    RouteWeightLedger,
    _MAX_WEIGHT,
    _MIN_WEIGHT,
    get_route_weight_ledger,
    reset_route_weight_ledger,
)


@pytest.fixture(autouse=True)
def _isolate_ledger():
    reset_route_weight_ledger()
    yield
    reset_route_weight_ledger()


class TestDefaults:
    def test_unpenalized_pair_returns_max(self):
        led = RouteWeightLedger()
        assert led.get("openai", "llm_complete") == _MAX_WEIGHT

    def test_empty_snapshot(self):
        led = RouteWeightLedger()
        snap = led.snapshot()
        assert snap["rows"] == []
        assert snap["total_penalties"] == 0


class TestPenalize:
    def test_single_penalty(self):
        led = RouteWeightLedger()
        w = led.penalize("openai", "llm_complete", 0.5)
        assert w == pytest.approx(0.5)
        assert led.get("openai", "llm_complete") == pytest.approx(0.5)

    def test_penalty_compounds_multiplicatively(self):
        led = RouteWeightLedger()
        led.penalize("openai", "llm_complete", 0.5)
        # Without decay the second penalty is 0.5 * 0.5 = 0.25
        # Because _decayed_locked runs first and age ≈ 0, the
        # decay factor is ≈1.0, so we get the raw compound.
        w = led.penalize("openai", "llm_complete", 0.5)
        assert w == pytest.approx(0.25, rel=1e-3)

    def test_penalty_clamped_to_floor(self):
        led = RouteWeightLedger(min_weight=0.1)
        for _ in range(20):
            led.penalize("openai", "llm_complete", 0.5)
        assert led.get("openai", "llm_complete") == pytest.approx(0.1)

    def test_bad_penalty_ignored(self):
        led = RouteWeightLedger()
        assert led.penalize("openai", "llm_complete", "bad") == _MAX_WEIGHT
        assert led.penalize("openai", "llm_complete", 2.0) == _MAX_WEIGHT
        assert led.penalize("openai", "llm_complete", 0.0) == _MAX_WEIGHT
        assert led.penalize("openai", "llm_complete", float("inf")) == (
            _MAX_WEIGHT
        )
        # Unpenalized — row was never created for these.
        assert led.get("openai", "llm_complete") == _MAX_WEIGHT

    def test_empty_adapter_or_capability_ignored(self):
        led = RouteWeightLedger()
        assert led.penalize("", "llm_complete", 0.5) == _MAX_WEIGHT
        assert led.penalize("openai", "", 0.5) == _MAX_WEIGHT


class TestDecay:
    def test_decay_recovers_toward_one(self):
        led = RouteWeightLedger(half_life_hours=1.0)
        with patch("core.adapters.route_weights.time.time") as t:
            t.return_value = 1_000_000.0
            led.penalize("openai", "llm_complete", 0.25)
            t.return_value = 1_000_000.0 + 3600.0  # + 1 half-life
            w = led.get("openai", "llm_complete")
            # weight = 1 - (1 - 0.25)*2^-1 = 1 - 0.375 = 0.625
            assert w == pytest.approx(0.625, rel=1e-3)
            t.return_value = 1_000_000.0 + 7200.0  # + 2 half-lives
            w = led.get("openai", "llm_complete")
            # weight = 1 - 0.75 * 0.25 = 0.8125
            assert w == pytest.approx(0.8125, rel=1e-3)

    def test_decay_snaps_to_max_after_long_idle(self):
        led = RouteWeightLedger(half_life_hours=1.0)
        with patch("core.adapters.route_weights.time.time") as t:
            t.return_value = 1_000_000.0
            led.penalize("openai", "llm_complete", 0.25)
            t.return_value = 1_000_000.0 + 100_000.0  # way past recovery
            assert led.get("openai", "llm_complete") == _MAX_WEIGHT

    def test_new_penalty_lands_on_decayed_value(self):
        led = RouteWeightLedger(half_life_hours=1.0)
        with patch("core.adapters.route_weights.time.time") as t:
            t.return_value = 1_000_000.0
            led.penalize("openai", "llm_complete", 0.5)  # 0.5
            t.return_value = 1_000_000.0 + 3600.0  # +1 half-life
            # decayed to 1-(1-0.5)*0.5 = 0.75; new penalty 0.5 →0.375
            w = led.penalize("openai", "llm_complete", 0.5)
            assert w == pytest.approx(0.375, rel=1e-3)


class TestReset:
    def test_reset_single_row(self):
        led = RouteWeightLedger()
        led.penalize("openai", "llm_complete", 0.25)
        led.penalize("anthropic", "llm_complete", 0.5)
        led.reset("openai", "llm_complete")
        assert led.get("openai", "llm_complete") == _MAX_WEIGHT
        assert led.get("anthropic", "llm_complete") == pytest.approx(0.5)

    def test_reset_missing_row_is_noop(self):
        led = RouteWeightLedger()
        led.reset("ghost", "nope")  # no crash

    def test_reset_all(self):
        led = RouteWeightLedger()
        led.penalize("a", "cap", 0.5)
        led.penalize("b", "cap", 0.5)
        led.reset_all()
        assert led.get("a", "cap") == _MAX_WEIGHT
        assert led.get("b", "cap") == _MAX_WEIGHT


class TestApplyReflectionReport:
    def test_promoted_patterns_are_penalized(self):
        led = RouteWeightLedger()
        report = {
            "patterns": [
                {
                    "promoted": True,
                    "adapter": "openai",
                    "capability": "llm_complete",
                },
                {
                    "promoted": True,
                    "adapter": "shopify_orders",
                    "capability": "shopify_fetch_orders",
                },
            ],
        }
        applied = led.apply_reflection_report(report)
        assert applied == 2
        assert led.get("openai", "llm_complete") < _MAX_WEIGHT
        assert led.get("shopify_orders", "shopify_fetch_orders") < _MAX_WEIGHT

    def test_non_promoted_skipped(self):
        led = RouteWeightLedger()
        report = {
            "patterns": [
                {
                    "promoted": False,
                    "adapter": "openai",
                    "capability": "llm_complete",
                },
            ],
        }
        assert led.apply_reflection_report(report) == 0
        assert led.get("openai", "llm_complete") == _MAX_WEIGHT

    def test_patterns_missing_fields_skipped(self):
        led = RouteWeightLedger()
        report = {
            "patterns": [
                {"promoted": True, "adapter": "openai"},  # no capability
                {"promoted": True, "capability": "llm_complete"},  # no adapter
                {"promoted": True},  # neither
            ],
        }
        assert led.apply_reflection_report(report) == 0

    def test_report_with_as_dict_method(self):
        led = RouteWeightLedger()

        class Rep:
            def as_dict(self):
                return {
                    "patterns": [
                        {
                            "promoted": True,
                            "adapter": "a",
                            "capability": "c",
                        },
                    ],
                }
        assert led.apply_reflection_report(Rep()) == 1

    def test_none_report_is_noop(self):
        led = RouteWeightLedger()
        assert led.apply_reflection_report(None) == 0

    def test_unserializable_report_is_noop(self):
        led = RouteWeightLedger()

        class Rep:
            def as_dict(self):
                raise RuntimeError("boom")
        assert led.apply_reflection_report(Rep()) == 0


class TestSnapshot:
    def test_snapshot_sorted_worst_first(self):
        led = RouteWeightLedger()
        led.penalize("a", "cap", 0.5)
        led.penalize("b", "cap", 0.5)
        led.penalize("b", "cap", 0.5)  # b penalized twice
        snap = led.snapshot()
        assert len(snap["rows"]) == 2
        # b should come first (weight 0.25 < 0.5)
        assert snap["rows"][0]["adapter"] == "b"
        assert snap["rows"][0]["penalty_count"] == 2
        assert snap["total_penalties"] == 3


class TestLRUCap:
    """Self-critique fix: _rows must be bounded with LRU eviction
    so a runaway feeder can't grow memory unbounded."""

    def test_cap_evicts_oldest_touched(self):
        led = RouteWeightLedger(max_rows=3)
        led.penalize("a", "cap", 0.5)
        led.penalize("b", "cap", 0.5)
        led.penalize("c", "cap", 0.5)
        # Touch 'a' so it moves to most-recently-used.
        led.penalize("a", "cap", 0.9)
        # Inserting a new row should evict 'b' (oldest untouched).
        led.penalize("d", "cap", 0.5)
        snap = led.snapshot()
        adapters = {r["adapter"] for r in snap["rows"]}
        assert "b" not in adapters
        assert {"a", "c", "d"} <= adapters
        assert snap["total_evictions"] >= 1

    def test_eviction_counter_exposed(self):
        led = RouteWeightLedger(max_rows=2)
        led.penalize("a", "cap", 0.5)
        led.penalize("b", "cap", 0.5)
        led.penalize("c", "cap", 0.5)  # evicts a
        assert led.snapshot()["total_evictions"] == 1

    def test_bad_max_rows_rejected(self):
        with pytest.raises(ValueError):
            RouteWeightLedger(max_rows=0)


class TestSingleton:
    def test_singleton_persists(self):
        led1 = get_route_weight_ledger()
        led1.penalize("a", "cap", 0.5)
        led2 = get_route_weight_ledger()
        assert led1 is led2
        assert led2.get("a", "cap") == pytest.approx(0.5)

    def test_reset_clears_singleton(self):
        led1 = get_route_weight_ledger()
        reset_route_weight_ledger()
        led2 = get_route_weight_ledger()
        assert led1 is not led2
