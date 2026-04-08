"""Tests for audit-pass-40 fixes — defensive hardening + real
logic bug fixes across 4 autonomous-loop intelligence modules
(campaign_optimizer, competitor_intelligence, kpi_tracker,
forecasting).

These 4 modules are all called directly by EventReactor's
built-in handlers (pass 38 hardened those), so bugs here can
crash a webhook-driven reaction path.

Real bugs fixed:

  * competitor_intelligence._assess_threat scored the threats
    correctly as "low"/"medium"/"high" strings, but the
    ``top_threat`` field was then picked via
    ``max(analyses, key=lambda a: a["threat_level"])`` —
    lexicographic string comparison. ``"medium" > "high"``
    alphabetically, so a "medium" competitor was always
    flagged as the top threat over a genuinely "high"
    competitor. Now uses a numeric _THREAT_ORDER rank.

  * campaign_optimizer rule 4 (``2.0 <= roas < 3.0 and
    ctr < 2.0``) reduced the budget on campaigns with CTR=0,
    i.e. campaigns that had no clicks YET — typically a
    brand-new campaign with no impression data. Reducing
    budget on a starved-of-data campaign makes no sense. Now
    requires ``ctr > 0``.

  * campaign_optimizer.get_campaign_health divided
    ``total_revenue`` by ``max(total_spend, 0.01)`` for
    portfolio_roas. A zero-spend portfolio with e.g. $500 in
    organic revenue reported a ROAS of 50000x. Now guards
    and returns 0.

  * kpi_tracker.get_revenue_kpis ran ``int(e.get("conversions",
    0))`` which crashed on None / non-numeric strings from
    corrupted JSON. Now uses safe_int.

  * forecasting.forecast() assumed ``values`` was a clean list
    of numbers; a list with None / strings / dicts from a
    misbehaving webhook crashed the arithmetic in
    _exponential_smoothing / _linear_trend / _seasonal_forecast.
    Now coerces via _coerce_values.

Plus the usual defensive None-input / non-dict-item coercion
on every public entry point.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from core.intelligence.campaign_optimizer import CampaignOptimizer
from core.intelligence.competitor_intelligence import CompetitorIntelligence
from core.intelligence.forecasting import Forecasting


# ═══════════════════════════════════════════════════════════
# CampaignOptimizer
# ═══════════════════════════════════════════════════════════


class TestCampaignOptimizer:
    def test_none_campaigns_does_not_crash(self):
        co = CampaignOptimizer()
        assert co.optimize(None) == []
        assert co.get_campaign_health(None) == {"status": "no_campaigns"}

    def test_non_list_campaigns_does_not_crash(self):
        co = CampaignOptimizer()
        assert co.optimize("not a list") == []
        assert co.get_campaign_health({"not": "a list"}) == {"status": "no_campaigns"}

    def test_mixed_campaigns_list_skips_non_dict(self):
        co = CampaignOptimizer()
        actions = co.optimize([
            "not a dict",
            None,
            {"campaign_id": "c1", "roas": 5.0, "budget": 100, "ctr": 3.0},
            ["also not a dict"],
        ])
        assert any(a["campaign_id"] == "c1" for a in actions)

    def test_reduce_budget_requires_nonzero_ctr(self):
        """Regression: pre-audit rule 4 fired when CTR == 0,
        treating a no-clicks-yet campaign as "low CTR"."""
        co = CampaignOptimizer()
        # Borderline ROAS 2.5, CTR 0 (no data). Should NOT
        # recommend reduce_budget.
        actions = co.optimize([
            {"campaign_id": "new_campaign", "roas": 2.5, "ctr": 0, "budget": 100, "spend": 5},
        ])
        assert not any(a["action"] == "reduce_budget" for a in actions)
        # But with CTR 1.5 (genuinely low), it SHOULD fire.
        actions2 = co.optimize([
            {"campaign_id": "bad_creative", "roas": 2.5, "ctr": 1.5, "budget": 100, "spend": 50},
        ])
        assert any(a["action"] == "reduce_budget" for a in actions2)

    def test_zero_spend_portfolio_roas_not_inflated(self):
        """Regression: pre-audit divided revenue by
        ``max(total_spend, 0.01)`` giving absurd ROAS numbers
        for zero-spend portfolios."""
        co = CampaignOptimizer()
        health = co.get_campaign_health([
            {"campaign_id": "organic", "roas": 0, "ctr": 0, "budget": 0,
             "spend": 0, "revenue": 500, "status": "active"},
        ])
        assert health["total_spend"] == 0
        assert health["portfolio_roas"] == 0  # Not 50000


# ═══════════════════════════════════════════════════════════
# CompetitorIntelligence
# ═══════════════════════════════════════════════════════════


class TestCompetitorIntelligence:
    def test_none_inputs_do_not_crash(self):
        ci = CompetitorIntelligence()
        assert "error" in ci.analyze_competitors(None, None)
        assert "error" in ci.analyze_competitors({}, None)

    def test_threat_level_uses_numeric_rank_not_lexicographic(self):
        """Regression: pre-audit ``max(...,
        key=lambda a: a["threat_level"])`` compared strings
        alphabetically. ``"medium" > "high"`` → a medium
        competitor was always flagged over a genuinely high
        one."""
        ci = CompetitorIntelligence()
        # Use the internal threat classifier to pick scores
        # directly, so the test is independent of the
        # scoring heuristic.
        ci2 = CompetitorIntelligence()
        # Monkey-patch analyses via the underlying primitive.
        analyses = [
            {"competitor": "HighThreat", "threat_level": "high", "avg_price": 30, "unique_categories": []},
            {"competitor": "MediumOne", "threat_level": "medium", "avg_price": 50, "unique_categories": []},
            {"competitor": "LowOne", "threat_level": "low", "avg_price": 60, "unique_categories": []},
        ]
        # Directly exercise the ordering logic via the
        # ``_THREAT_ORDER`` import.
        from core.intelligence.competitor_intelligence import _THREAT_ORDER
        top = max(analyses, key=lambda a: _THREAT_ORDER.get(a["threat_level"], 0))
        assert top["competitor"] == "HighThreat"

        # Also check via the full public method with a fixture
        # that produces real high / medium threat scores.
        # Scoring rules (from _assess_threat):
        #   +2 if price_index in (90, 110)  — similar pricing
        #   +3 if price_index < 90          — we are cheaper
        #   +1 if product_count > 50
        #   +2 if overlap_count > 3
        # score >= 5 → "high", >= 3 → "medium", else "low".
        #
        # HighThreat: similar pricing (+2) + >50 products (+1)
        #   + overlap > 3 (+2) = 5 → high.
        # MediumOne: similar pricing (+2) + 1 overlap (+0) = 2
        #   → low (below medium threshold), or with more
        #   overlap landing at medium.
        our_store = {
            "products": [
                {"category": f"cat{i}", "price": 100}
                for i in range(10)
            ],
        }
        competitors = [
            {
                "name": "HighThreat",
                "products": (
                    [{"category": f"cat{i}", "price": 100} for i in range(10)]
                    + [{"category": "junk", "price": 100}] * 55
                ),
            },
            {
                # Similar pricing (+2) + overlap > 3 (+2) = 4
                # → medium. Not enough products to tip to
                # high.
                "name": "MediumOne",
                "products": [
                    {"category": f"cat{i}", "price": 100}
                    for i in range(5)
                ],
            },
        ]
        result = ci2.analyze_competitors(our_store, competitors)
        high_comps = [c for c in result["competitors"] if c["threat_level"] == "high"]
        medium_comps = [c for c in result["competitors"] if c["threat_level"] == "medium"]
        assert high_comps, f"no high threat found: {result['competitors']}"
        assert medium_comps, f"no medium threat found: {result['competitors']}"
        # The fix: top_threat must be the "high" competitor,
        # not the "medium" one (lexicographic max would have
        # picked "medium" because "m" > "h").
        assert result["top_threat"] == high_comps[0]["competitor"]
        assert result["top_threat"] != medium_comps[0]["competitor"]

    def test_nonnumeric_price_does_not_crash(self):
        """Regression: ``float(p.get("price", 0))`` used to
        crash on "$99.99" / "N/A" / None."""
        ci = CompetitorIntelligence()
        result = ci.analyze_competitors(
            {"products": [{"category": "cat1", "price": "$50.00"}]},
            [
                {
                    "name": "C",
                    "products": [
                        {"category": "cat1", "price": "$30.00"},
                        {"category": "cat1", "price": "N/A"},
                        {"category": "cat1", "price": None},
                        {"category": "cat1", "price": 40},
                    ],
                },
            ],
        )
        assert "competitors" in result
        assert result["competitors"][0]["avg_price"] > 0

    def test_price_comparison_handles_missing_prices(self):
        ci = CompetitorIntelligence()
        result = ci.price_comparison(
            [{"name": "p1", "category": "cat1", "price": "not a number"}],
            [{"name": "c1", "category": "cat1", "price": "N/A"}],
        )
        assert isinstance(result, dict)
        # No crash, comparison just has 0 matches (comp_price is 0).
        assert result["summary"]["products_compared"] == 0

    def test_non_dict_items_in_lists_skipped(self):
        ci = CompetitorIntelligence()
        result = ci.analyze_competitors(
            {"products": ["not a dict", None, {"category": "cat1", "price": 50}]},
            [
                "also not a dict",
                None,
                {"name": "C", "products": ["bad", {"category": "cat1", "price": 30}]},
            ],
        )
        assert "competitors" in result


# ═══════════════════════════════════════════════════════════
# KPITracker
# ═══════════════════════════════════════════════════════════


class TestKPITracker:
    @pytest.fixture
    def tracker(self, tmp_path, monkeypatch):
        import core.intelligence.kpi_tracker as mod
        monkeypatch.setattr(mod, "_KPI_DIR", str(tmp_path))
        return mod.KPITracker()

    def test_none_decision_outcome_does_not_crash(self, tracker):
        tracker.record_decision_outcome(
            decision_id=None,
            decision_type=None,
            confidence=None,
            confidence_score=None,
            success=None,
            data_quality=None,
        )
        # Should not crash.

    def test_nonnumeric_revenue_event_does_not_crash(self, tracker):
        tracker.record_revenue_event(
            decision_id="d1",
            revenue="not a number",
            cost=None,
            conversion_count="bad",
            impression_count=None,
            click_count="hi",
        )
        kpis = tracker.get_revenue_kpis()
        assert kpis["total_revenue"] == 0
        assert kpis["total_cost"] == 0

    def test_corrupted_json_backed_up_not_silently_overwritten(self, tracker, tmp_path):
        """Regression: pre-audit ``_load`` silently returned
        [] for corrupted JSON, then ``_append`` silently
        overwrote the corrupted file. Audit pass 39/40 pattern
        requires the corrupted file to be moved to
        ``<path>.corrupted.<ts>`` so an operator can inspect
        what went wrong."""
        path = os.path.join(str(tmp_path), "decisions.json")
        with open(path, "w") as f:
            f.write("{not valid json")

        # Append should trigger a backup.
        tracker.record_decision_outcome(
            decision_id="d1",
            decision_type="test",
            confidence="high",
            confidence_score=80,
            success=True,
            data_quality=70,
        )
        # Original corrupted file should be moved aside.
        backups = [
            f for f in os.listdir(str(tmp_path))
            if f.startswith("decisions.json.corrupted.")
        ]
        assert len(backups) >= 1

    def test_non_list_json_backed_up(self, tracker, tmp_path):
        """A valid JSON file that's an object (not a list)
        should also be treated as corrupted."""
        path = os.path.join(str(tmp_path), "revenue_events.json")
        with open(path, "w") as f:
            json.dump({"accidentally": "an object"}, f)

        tracker.record_revenue_event("d1", revenue=100)
        backups = [
            f for f in os.listdir(str(tmp_path))
            if f.startswith("revenue_events.json.corrupted.")
        ]
        assert len(backups) >= 1


# ═══════════════════════════════════════════════════════════
# Forecasting
# ═══════════════════════════════════════════════════════════


class TestForecasting:
    def test_none_values_returns_error(self):
        f = Forecasting()
        r = f.forecast(None)
        assert "error" in r

    def test_non_list_values_returns_error(self):
        f = Forecasting()
        r = f.forecast("not a list")
        assert "error" in r

    def test_mixed_values_list_does_not_crash(self):
        """Regression: pre-audit assumed ``values`` was a
        clean list of numbers. A webhook payload with None /
        strings / dicts crashed the arithmetic."""
        f = Forecasting()
        r = f.forecast([10, None, "12.5", "N/A", {}, 14, 15, 16])
        assert "forecast" in r
        assert len(r["forecast"]) == 7

    def test_string_prices_parsed(self):
        """Common webhook form: order.total_price as a
        string like "$99.99"."""
        f = Forecasting()
        r = f.forecast(["$10.00", "$12.50", "$15.00", "$18.00", "$22.00"])
        assert "forecast" in r

    def test_nan_and_inf_dropped(self):
        f = Forecasting()
        r = f.forecast([10.0, float("nan"), float("inf"), 12.0, 14.0, 16.0])
        assert "forecast" in r
        assert r["historical_points"] == 4  # nan + inf dropped

    def test_bool_values_not_silently_coerced(self):
        """``bool`` is a subclass of ``int`` in Python. Pre-
        audit ``isinstance(v, (int, float))`` silently coerced
        booleans to 0/1. We reject them explicitly."""
        f = Forecasting()
        r = f.forecast([True, False, True, True, False])
        assert "error" in r  # Fewer than 3 real values.

    def test_revenue_forecast_handles_non_numeric(self):
        f = Forecasting()
        r = f.revenue_forecast([100, "200", None, 300, "$400", 500, 600])
        assert "revenue_summary" in r

    def test_demand_forecast_handles_non_numeric(self):
        f = Forecasting()
        r = f.demand_forecast([10, None, "15", 20, "bad", 25, 30])
        assert "demand_summary" in r

    def test_invalid_periods_coerced_to_default(self):
        f = Forecasting()
        r = f.forecast([10, 20, 30, 40, 50], periods=-5)
        assert "forecast" in r
        assert len(r["forecast"]) == 7  # default period count

    def test_invalid_method_falls_back(self):
        f = Forecasting()
        r = f.forecast([10, 20, 30, 40, 50], method=None)
        assert "forecast" in r
