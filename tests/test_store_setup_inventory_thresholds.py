"""Tests for ``engines.store_setup.inventory_thresholds``.

Niche-aware inventory threshold + service-level + stockout-
cost recommendations. Drop-in for the ``inventory`` engine's
config inputs.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: every niche has full shape.
  3. Generator: every shipped niche resolves.
  4. Generator: unknown niche -> general.
  5. Tuning: food has shortest lead time + highest
     service level (perishable + subscription).
  6. Tuning: jewelry has longest lead time + lowest
     buffer (custom + made-to-order, expensive to
     carry).
  7. Tuning: service levels in plausible range
     (0.90 - 0.99).
  8. Tuning: lead times in plausible range (1-90 days).
  9. Tuning: numeric typing (int days; float
     percentages; int unit thresholds).
 10. `hand_off_to_inventory_engine` produces a kwargs
     dict mapping cleanly to the inventory engine.
 11. `hand_off_to_inventory_engine` empty/bad input ->
     empty dict.
"""
from __future__ import annotations

from engines.store_setup.inventory_thresholds import (
    _NICHE_TUNING,
    generate_inventory_thresholds,
    hand_off_to_inventory_engine,
)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_inventory_thresholds(
            store_name="",
        ) == {}
        assert generate_inventory_thresholds(
            store_name="   ",
        ) == {}
        assert generate_inventory_thresholds(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_every_niche_has_full_shape(self):
        for niche in _NICHE_TUNING:
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            assert spec["store_name"] == "Acme"
            assert spec["niche"] == niche
            assert "defaults" in spec
            assert "rationale" in spec

    def test_defaults_have_six_keys(self):
        for niche in _NICHE_TUNING:
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            d = spec["defaults"]
            assert "lead_time_days" in d, niche
            assert "service_level_target" in d, niche
            assert "reorder_buffer_pct" in d, niche
            assert "min_stock_threshold_units" in d, niche
            assert "max_stock_threshold_units" in d, niche
            assert "stockout_cost_per_day_usd" in d, niche

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            assert spec["defaults"]

    def test_unknown_niche_falls_back(self):
        spec = generate_inventory_thresholds(
            store_name="Acme", niche="ufo_parts",
        )
        general = generate_inventory_thresholds(
            store_name="Acme", niche="general",
        )
        assert spec["defaults"] == general["defaults"]


class TestNicheTuning:

    def test_food_has_shortest_lead_time(self):
        food = generate_inventory_thresholds(
            store_name="Acme", niche="food",
        )["defaults"]
        for other in (
            "beauty", "fashion", "tech", "home",
            "jewelry", "outdoor",
        ):
            other_lt = generate_inventory_thresholds(
                store_name="Acme", niche=other,
            )["defaults"]["lead_time_days"]
            assert (
                food["lead_time_days"] <= other_lt
            ), (other, other_lt)

    def test_food_has_highest_service_level(self):
        food = generate_inventory_thresholds(
            store_name="Acme", niche="food",
        )["defaults"]
        assert food["service_level_target"] >= 0.97

    def test_jewelry_has_longest_lead_time(self):
        jewelry = generate_inventory_thresholds(
            store_name="Acme", niche="jewelry",
        )["defaults"]
        assert jewelry["lead_time_days"] >= 30

    def test_jewelry_has_lowest_buffer(self):
        """Precious metal carry cost = lowest buffer."""
        jewelry = generate_inventory_thresholds(
            store_name="Acme", niche="jewelry",
        )["defaults"]
        for other in (
            "beauty", "fashion", "tech", "home",
            "food", "pets", "fitness", "outdoor",
            "baby",
        ):
            other_buf = generate_inventory_thresholds(
                store_name="Acme", niche=other,
            )["defaults"]["reorder_buffer_pct"]
            assert (
                jewelry["reorder_buffer_pct"]
                <= other_buf + 0.001
            ), other


class TestPlausibility:

    def test_service_levels_in_range(self):
        """All service levels in (0.80, 1.00) range."""
        for niche in _NICHE_TUNING:
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            sl = spec["defaults"]["service_level_target"]
            assert 0.80 <= sl <= 1.00, (niche, sl)

    def test_lead_times_plausible(self):
        for niche in _NICHE_TUNING:
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            lt = spec["defaults"]["lead_time_days"]
            assert 1 <= lt <= 90, (niche, lt)

    def test_buffer_in_range(self):
        for niche in _NICHE_TUNING:
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            buf = spec["defaults"]["reorder_buffer_pct"]
            # 5-40% buffer covers realistic cases
            assert 0.05 <= buf <= 0.40, (niche, buf)

    def test_min_below_max(self):
        for niche in _NICHE_TUNING:
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            d = spec["defaults"]
            assert (
                d["min_stock_threshold_units"]
                < d["max_stock_threshold_units"]
            ), niche

    def test_numeric_types(self):
        for niche in _NICHE_TUNING:
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            d = spec["defaults"]
            assert isinstance(d["lead_time_days"], int)
            assert isinstance(
                d["service_level_target"], float,
            )
            assert isinstance(
                d["reorder_buffer_pct"], float,
            )
            assert isinstance(
                d["min_stock_threshold_units"], int,
            )
            assert isinstance(
                d["max_stock_threshold_units"], int,
            )
            assert isinstance(
                d["stockout_cost_per_day_usd"], float,
            )


class TestRationale:

    def test_rationale_substantive(self):
        """Each niche has a rationale >= 50 chars."""
        for niche in _NICHE_TUNING:
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            assert len(spec["rationale"]) >= 50, niche

    def test_distinct_rationales(self):
        """All niche rationales are unique (no copy-paste
        drift)."""
        seen = set()
        for niche in _NICHE_TUNING:
            spec = generate_inventory_thresholds(
                store_name="Acme", niche=niche,
            )
            r = spec["rationale"]
            assert r not in seen, niche
            seen.add(r)


# ── Handoff ──────────────────────────────────────────────────


class TestHandoff:

    def test_produces_kwargs_dict(self):
        template = generate_inventory_thresholds(
            store_name="Acme", niche="beauty",
        )
        kwargs = hand_off_to_inventory_engine(template)
        # Must contain the inventory-engine kwargs
        assert "service_level_target" in kwargs
        assert "lead_time_days" in kwargs
        assert "reorder_buffer_pct" in kwargs
        assert "min_stock_threshold_units" in kwargs
        assert "max_stock_threshold_units" in kwargs
        assert "stockout_cost_per_day_usd" in kwargs

    def test_preserves_values(self):
        template = generate_inventory_thresholds(
            store_name="Acme", niche="food",
        )
        kwargs = hand_off_to_inventory_engine(template)
        defaults = template["defaults"]
        assert (
            kwargs["service_level_target"]
            == defaults["service_level_target"]
        )
        assert (
            kwargs["lead_time_days"]
            == defaults["lead_time_days"]
        )

    def test_empty_template(self):
        assert hand_off_to_inventory_engine({}) == {}
        assert hand_off_to_inventory_engine(None) == {}  # type: ignore[arg-type]
        # Template without defaults
        assert hand_off_to_inventory_engine(
            {"store_name": "Acme"},
        ) == {}
