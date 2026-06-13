"""W963-172: revenue_projector cold-start key-schema parity.

W963-161 added a cold-start fallback so empty / unpriced product
input doesn't crash the discount_strategy cycle. The fallback
INITIALLY used a different key schema from the success path,
which would silently KeyError any downstream consumer reading
projection['base_revenue_daily'] / projection_confidence /
etc. on cold-start. W963-172 unified the two schemas.

This test pins the contract so a future refactor that
diverges the keys triggers a CI failure instead of a silent
downstream crash.
"""
from __future__ import annotations

from engines.discount_strategy.revenue_projector import (
    project_revenue,
)


# The canonical key set the success path emits. Any new key
# added to the success path MUST be added here AND mirrored
# in the cold-start fallback at revenue_projector.py:81.
_SUCCESS_PROJECTION_KEYS = {
    "base_revenue_daily",
    "projected_revenue_daily",
    "revenue_change_pct",
    "margin_loss_per_unit",
    "volume_lift_multiplier",
    "break_even_volume",
    "break_even_achievable",
    "net_profit_impact",
    "projection_confidence",
}


class TestColdStartParity:
    def test_cold_start_returns_success_status(self):
        """W963-161: empty product list -> success-skip
        envelope rather than status=error."""
        result = project_revenue(
            margin_analyses=[],
            sweet_spot_pct=0.10,
            volume_lift=1.2,
            margin_at_sweet_spot=0.3,
            duration_hours=720,
            target_reach_pct=0.5,
            response_rate=0.1,
            cannibalization_impact_pct=0.05,
        )
        assert result["status"] == "success"
        assert result["error"] == ""

    def test_cold_start_emits_success_path_schema(self):
        """W963-172: cold-start fallback must emit the same
        key set as the success path so downstream consumers
        don't KeyError."""
        result = project_revenue(
            margin_analyses=[],
            sweet_spot_pct=0.10,
            volume_lift=1.2,
            margin_at_sweet_spot=0.3,
            duration_hours=720,
            target_reach_pct=0.5,
            response_rate=0.1,
            cannibalization_impact_pct=0.05,
        )
        projection = result["projection"]
        # Every canonical key present
        missing = _SUCCESS_PROJECTION_KEYS - set(
            projection.keys(),
        )
        assert not missing, (
            f"cold-start missing keys: {sorted(missing)}"
        )
        # No legacy/stale keys leaked
        stale_keys = {
            "baseline_daily_revenue",
            "discounted_daily_revenue",
            "incremental_daily_revenue",
            "baseline_daily_profit",
            "discounted_daily_profit",
            "incremental_daily_profit",
            "campaign_total_revenue",
            "campaign_total_profit",
            "expected_volume_lift",
            "confidence",
            "rationale",
        }
        leaked = stale_keys & set(projection.keys())
        assert not leaked, (
            f"cold-start leaked legacy keys: "
            f"{sorted(leaked)}"
        )

    def test_cold_start_values_are_safe_defaults(self):
        """Cold-start consumers reading numeric fields
        should see safe zero / unit values rather than
        garbage."""
        result = project_revenue(
            margin_analyses=[],
            sweet_spot_pct=0.10,
            volume_lift=1.2,
            margin_at_sweet_spot=0.3,
            duration_hours=720,
            target_reach_pct=0.5,
            response_rate=0.1,
            cannibalization_impact_pct=0.05,
        )
        p = result["projection"]
        assert p["base_revenue_daily"] == 0.0
        assert p["projected_revenue_daily"] == 0.0
        assert p["revenue_change_pct"] == 0.0
        assert p["volume_lift_multiplier"] == 1.0
        assert p["break_even_achievable"] is False
        # Low confidence flags cold-start state for
        # confidence-gated consumers
        assert p["projection_confidence"] == 0.1
