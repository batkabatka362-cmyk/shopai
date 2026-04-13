"""Tests for audit-pass-10 fixes in IntelligenceLoop.

  1. _stage_decide() referenced an undefined `top` variable on
     the avoid_below_score gate, so any cycle where the outcome
     tracker had set that field would crash with NameError.
  2. _stage_clean() rebound `data[key] = cleaned` but the empty-
     removal check below still used the OLD `val`, so a list
     whose every item got filtered out would leave a zombie
     empty list in `data` instead of being removed.
  3-5. _stage_analyze forecasting + _stage_decide strategy
     weights + _stage_track all swallowed exceptions silently
     with bare `except Exception: pass`.
"""
import pytest


def _loop():
    from core.intelligence_loop import IntelligenceLoop
    return IntelligenceLoop()


# ── _stage_decide NameError on `top` ─────────────────────────


class TestDecideTopVariable:
    def test_avoid_below_score_no_longer_crashes(self, monkeypatch):
        """Regression: previously line 439 referenced an undefined
        `top` variable. Any past_advice with avoid_below_score
        triggered NameError. Now `top` is hoisted to the top of
        the method."""
        loop = _loop()

        # Force _get_past_learning to return a dict that triggers
        # the avoid_below_score gate.
        monkeypatch.setattr(
            loop, "_get_past_learning",
            lambda goal: {
                "success_rate": 0.4,
                "avoid_below_score": 5.0,
            },
        )

        analysis = {
            "products": {
                "total": 3,
                "viable": 1,
                "top_product": {"name": "X", "total_score": 6.5, "margin_pct": 30},
                "avg_score": 5.5,
            },
            "customers": {"total": 0, "at_risk": 0, "repeat_rate": 0},
            "revenue": {"total": 100, "orders": 5, "aov": 20},
            "forecast": {},
            "opportunity_score": 50,
            "findings": [],
        }
        clean_result = {"quality_score": 80, "data": {}}

        # Must not raise NameError
        decision = loop._stage_decide(analysis, clean_result, "maximize_profit")
        assert "recommended_action" in decision

    def test_decide_works_without_top_product(self):
        """When products has no top_product, the new top extraction
        still produces a usable empty dict and the decide stage
        finishes normally."""
        loop = _loop()
        analysis = {
            "products": {"total": 0, "viable": 0, "top_product": None},
            "customers": {"total": 0, "at_risk": 0, "repeat_rate": 0},
            "revenue": {"total": 0, "orders": 0, "aov": 0},
            "forecast": {},
            "opportunity_score": 30,
            "findings": [],
        }
        decision = loop._stage_decide(
            analysis, {"quality_score": 50, "data": {}}, "maximize_profit",
        )
        assert "recommended_action" in decision


# ── _stage_clean stale-val empty-list removal ────────────────


class TestCleanEmptyListRemoval:
    def test_list_emptied_by_cleaning_is_removed(self):
        """Regression: previously a list whose items were all
        filtered out (e.g. all unnamed products) would leave a
        zombie empty list in data because the empty-check used
        the original `val` not the cleaned list."""
        loop = _loop()
        result = loop._stage_clean({
            # Three product items with no name/id/title — all
            # filtered out by the cleaner.
            "products": [
                {"price": 10},
                {"price": 20},
                {"price": 30},
            ],
            "store_id": "x",
        })
        # The cleaned products list became empty and must NOT be
        # in the resulting data dict.
        assert "products" not in result["data"]
        assert "store_id" in result["data"]
        # The fix log should record the removal.
        assert any("products" in f and "removed" in f for f in result["fixes"])

    def test_list_with_some_valid_items_kept(self):
        loop = _loop()
        result = loop._stage_clean({
            "products": [
                {"name": "Good", "price": 10},
                {"price": 20},  # filtered: no name/id
                {"id": "p3", "price": 30},
            ],
        })
        # 2 valid items survive
        assert len(result["data"]["products"]) == 2

    def test_truly_empty_list_removed(self):
        loop = _loop()
        result = loop._stage_clean({"products": [], "x": 1})
        assert "products" not in result["data"]


# ── Silent-swallow promotions ────────────────────────────────


class TestSilentSwallowPromotion:
    def test_forecasting_failure_logged(self, monkeypatch):
        """Forecasting failures previously hid silently. Now they
        log a WARNING with the failure type + message."""
        from core.intelligence_loop import IntelligenceLoop
        import core.intelligence_loop as il_mod

        warnings: list[str] = []
        monkeypatch.setattr(
            il_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        # Force Forecasting to raise
        class _BrokenFC:
            def forecast(self, *a, **k):
                raise RuntimeError("forecast exploded")

        import core.intelligence.forecasting as fc_mod
        monkeypatch.setattr(fc_mod, "Forecasting", lambda: _BrokenFC())

        loop = IntelligenceLoop()
        loop._stage_analyze(
            {"orders": [
                {"total": 10}, {"total": 20}, {"total": 30},
                {"total": 40}, {"total": 50},
            ]},
            "maximize_profit",
        )
        assert any("forecasting failed" in w for w in warnings)

    def test_strategy_optimizer_failure_logged(self, monkeypatch):
        from core.intelligence_loop import IntelligenceLoop
        import core.intelligence_loop as il_mod

        warnings: list[str] = []
        monkeypatch.setattr(
            il_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        class _BrokenOpt:
            def get_adjusted_weights(self, goal):
                raise RuntimeError("optimizer dead")

        import core.intelligence.strategy_optimizer as so_mod
        monkeypatch.setattr(so_mod, "StrategyOptimizer", lambda: _BrokenOpt())

        loop = IntelligenceLoop()
        # Drive through _stage_decide with a minimal analysis that
        # produces at least one option.
        analysis = {
            "products": {
                "total": 1, "viable": 1,
                "top_product": {"name": "p", "total_score": 7, "margin_pct": 25},
                "avg_score": 7,
            },
            "customers": {"total": 0, "at_risk": 0, "repeat_rate": 0},
            "revenue": {"total": 100, "orders": 5, "aov": 20},
            "forecast": {},
            "opportunity_score": 50,
            "findings": [],
        }
        loop._stage_decide(analysis, {"quality_score": 80, "data": {}}, "maximize_profit")
        assert any("strategy_optimizer" in w for w in warnings)

    def test_track_failure_logged(self, monkeypatch):
        from core.intelligence_loop import IntelligenceLoop
        import core.intelligence_loop as il_mod

        warnings: list[str] = []
        monkeypatch.setattr(
            il_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        class _BrokenTracker:
            def record_decision(self, *a, **k):
                raise RuntimeError("tracker offline")

        import core.learning.outcome_tracker as ot_mod
        monkeypatch.setattr(ot_mod, "OutcomeTracker", lambda: _BrokenTracker())

        loop = IntelligenceLoop()
        loop._stage_track("loop_x", {
            "decision": {"recommended_action": "x", "confidence": "high"},
            "analysis": {"products": {"viable": 1}},
            "clean": {"quality_score": 80},
            "goal": "maximize_profit",
        })
        assert any("outcome tracking failed" in w for w in warnings)
        assert any("learn flywheel may stall" in w for w in warnings)
