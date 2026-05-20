"""Tests for ``engines.store_setup.loyalty_tiers``.

Produces niche-tuned loyalty program config dicts that are
drop-in compatible with
``loyalty.program_designer.design_program``.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: 4 tiers always (bronze/silver/gold/platinum).
  3. Generator: every niche has full per-tier shape (name +
     min_points + multiplier + benefits).
  4. Generator: tier thresholds are monotonically increasing.
  5. Generator: tier multipliers are monotonically
     increasing.
  6. Generator: niche-tuned thresholds (jewelry > beauty
     > food at gold tier).
  7. Generator: niche-specific benefits surface in benefits
     list (e.g. "vet_consultations" in pets gold).
  8. Generator: benefits accumulate up the tiers (platinum
     inherits everything from lower tiers).
  9. Generator: points_per_dollar varies by niche (jewelry
     1.0, beauty 10.0).
 10. Generator: unknown niche falls back to general.
 11. `hand_off_to_program_designer`: produces a config dict
     that drop-in works with the existing
     `program_designer.design_program`.
 12. `hand_off_to_program_designer`: extra_config merges but
     doesn't stomp niche-tuned fields.
"""
from __future__ import annotations

from engines.loyalty.program_designer import design_program
from engines.loyalty.tier_manager import manage_tiers
from engines.store_setup.loyalty_tiers import (
    _NICHE_TIER_TUNING,
    _TIER_MULTIPLIERS,
    _TIER_NAMES,
    generate_tier_template,
    hand_off_to_program_designer,
    hand_off_to_tier_manager,
)


# ── Generator empty ──────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_tier_template(store_name="") == {}
        assert (
            generate_tier_template(store_name="   ") == {}
        )
        assert (
            generate_tier_template(store_name=None) == {}
        )


# ── Generator shape ──────────────────────────────────────────


class TestGeneratorShape:

    def test_four_tiers(self):
        for niche in _NICHE_TIER_TUNING:
            spec = generate_tier_template(
                store_name="Acme", niche=niche,
            )
            assert len(spec["tiers"]) == 4
            names = [t["name"] for t in spec["tiers"]]
            assert names == list(_TIER_NAMES)

    def test_every_tier_has_full_shape(self):
        for niche in _NICHE_TIER_TUNING:
            spec = generate_tier_template(
                store_name="Acme", niche=niche,
            )
            for tier in spec["tiers"]:
                assert tier["name"], niche
                assert isinstance(tier["min_points"], int)
                assert isinstance(tier["multiplier"], float)
                assert isinstance(tier["benefits"], list)
                assert len(tier["benefits"]) >= 1, niche

    def test_thresholds_monotonic(self):
        for niche in _NICHE_TIER_TUNING:
            spec = generate_tier_template(
                store_name="Acme", niche=niche,
            )
            mins = [t["min_points"] for t in spec["tiers"]]
            assert mins == sorted(mins), niche
            # bronze must always be 0
            assert mins[0] == 0, niche

    def test_multipliers_monotonic(self):
        for niche in _NICHE_TIER_TUNING:
            spec = generate_tier_template(
                store_name="Acme", niche=niche,
            )
            mults = [t["multiplier"] for t in spec["tiers"]]
            assert mults == sorted(mults), niche
            # bronze is always 1.0
            assert mults[0] == 1.0

    def test_multipliers_match_constants(self):
        """The 4 multipliers should match _TIER_MULTIPLIERS
        regardless of niche."""
        for niche in _NICHE_TIER_TUNING:
            spec = generate_tier_template(
                store_name="Acme", niche=niche,
            )
            for tier in spec["tiers"]:
                assert tier["multiplier"] == (
                    _TIER_MULTIPLIERS[tier["name"]]
                )


# ── Niche-specific tuning ────────────────────────────────────


class TestNicheTuning:

    def test_jewelry_higher_thresholds_than_beauty(self):
        """Jewelry should require significantly more points
        to reach gold than beauty (mirror the AOV gap)."""
        jewelry = generate_tier_template(
            store_name="Acme", niche="jewelry",
        )
        beauty = generate_tier_template(
            store_name="Acme", niche="beauty",
        )
        j_gold = next(
            t for t in jewelry["tiers"]
            if t["name"] == "gold"
        )["min_points"]
        b_gold = next(
            t for t in beauty["tiers"]
            if t["name"] == "gold"
        )["min_points"]
        assert j_gold >= b_gold

    def test_food_lower_thresholds_for_frequency(self):
        """Food's high purchase cadence means lower
        thresholds (faster feedback)."""
        food = generate_tier_template(
            store_name="Acme", niche="food",
        )
        # Food silver at 800 vs general silver at 1000
        food_silver = next(
            t for t in food["tiers"]
            if t["name"] == "silver"
        )["min_points"]
        assert food_silver < 1000

    def test_points_per_dollar_varies(self):
        """jewelry 1.0; beauty 10.0; tech 5.0."""
        jewelry = generate_tier_template(
            store_name="Acme", niche="jewelry",
        )
        beauty = generate_tier_template(
            store_name="Acme", niche="beauty",
        )
        tech = generate_tier_template(
            store_name="Acme", niche="tech",
        )
        assert jewelry["points_per_dollar"] == 1.0
        assert beauty["points_per_dollar"] == 10.0
        assert tech["points_per_dollar"] == 5.0


class TestNicheBenefits:

    def test_pets_gold_has_vet_consultations(self):
        pets = generate_tier_template(
            store_name="Acme", niche="pets",
        )
        gold = next(
            t for t in pets["tiers"]
            if t["name"] == "gold"
        )
        assert "vet_consultations" in gold["benefits"]

    def test_jewelry_silver_has_free_resize(self):
        jewelry = generate_tier_template(
            store_name="Acme", niche="jewelry",
        )
        silver = next(
            t for t in jewelry["tiers"]
            if t["name"] == "silver"
        )
        assert "free_resize" in silver["benefits"]

    def test_benefits_accumulate_up_tiers(self):
        """Platinum inherits everything from gold + silver
        + bronze; no benefit ever appears in a higher tier
        but not the highest tier."""
        for niche in _NICHE_TIER_TUNING:
            spec = generate_tier_template(
                store_name="Acme", niche=niche,
            )
            tiers_by_name = {
                t["name"]: t for t in spec["tiers"]
            }
            for lower, higher in (
                ("bronze", "silver"),
                ("silver", "gold"),
                ("gold", "platinum"),
            ):
                lower_b = set(
                    tiers_by_name[lower]["benefits"]
                )
                higher_b = set(
                    tiers_by_name[higher]["benefits"]
                )
                assert lower_b.issubset(higher_b), (
                    niche, lower, higher,
                )

    def test_no_duplicate_benefits_in_a_tier(self):
        for niche in _NICHE_TIER_TUNING:
            spec = generate_tier_template(
                store_name="Acme", niche=niche,
            )
            for tier in spec["tiers"]:
                bens = tier["benefits"]
                assert len(bens) == len(set(bens)), (
                    niche, tier["name"],
                )


class TestFallbacks:

    def test_unknown_niche_uses_general(self):
        unknown = generate_tier_template(
            store_name="Acme", niche="ufo_parts",
        )
        general = generate_tier_template(
            store_name="Acme", niche="general",
        )
        # tier thresholds + points_per_dollar match
        assert (
            [t["min_points"] for t in unknown["tiers"]]
            == [t["min_points"] for t in general["tiers"]]
        )
        assert (
            unknown["points_per_dollar"]
            == general["points_per_dollar"]
        )

    def test_blank_niche_uses_general(self):
        unknown = generate_tier_template(
            store_name="Acme", niche="",
        )
        general = generate_tier_template(
            store_name="Acme", niche="general",
        )
        assert (
            unknown["points_per_dollar"]
            == general["points_per_dollar"]
        )


# ── hand_off_to_program_designer ────────────────────────────


class TestHandoffProgramDesigner:

    def test_basic_handoff(self):
        template = generate_tier_template(
            store_name="Acme", niche="beauty",
        )
        config = hand_off_to_program_designer(template)
        # design_program expects tier_thresholds, not tiers.
        assert "tier_thresholds" in config
        assert config["tier_thresholds"]["bronze"] == 0
        assert config["tier_thresholds"]["silver"] == 1000
        assert (
            config["points_per_dollar"]
            == template["points_per_dollar"]
        )

    def test_extra_config_merges(self):
        template = generate_tier_template(
            store_name="Acme", niche="beauty",
        )
        config = hand_off_to_program_designer(
            template,
            extra_config={
                "program_name": "Beauty Rewards",
                "expiration_months": 24,
            },
        )
        assert config["program_name"] == "Beauty Rewards"
        assert config["expiration_months"] == 24
        # niche-tuned fields preserved
        assert "tier_thresholds" in config

    def test_extra_cant_stomp_niche_fields(self):
        """Even if the caller passes their own thresholds /
        points_per_dollar in extra_config, the niche-tuned
        values win."""
        template = generate_tier_template(
            store_name="Acme", niche="jewelry",
        )
        config = hand_off_to_program_designer(
            template,
            extra_config={
                "tier_thresholds": {"bronze": 999},
                "points_per_dollar": 999.0,
            },
        )
        assert config["points_per_dollar"] == 1.0
        # jewelry silver is 2000, not 999
        assert config["tier_thresholds"]["silver"] == 2000

    def test_empty_template(self):
        assert hand_off_to_program_designer({}) == {}
        assert hand_off_to_program_designer(None) == {}  # type: ignore[arg-type]
        # template without tiers
        assert (
            hand_off_to_program_designer(
                {"store_name": "Acme"},
            ) == {}
        )


class TestHandoffTierManager:
    """`hand_off_to_tier_manager` preserves the niche-aware
    multipliers + benefits that `design_program` would
    discard."""

    def test_returns_full_tier_list(self):
        template = generate_tier_template(
            store_name="Acme", niche="beauty",
        )
        tiers = hand_off_to_tier_manager(template)
        assert tiers == template["tiers"]

    def test_empty_template(self):
        assert hand_off_to_tier_manager({}) == []
        assert hand_off_to_tier_manager(None) == []  # type: ignore[arg-type]
        assert hand_off_to_tier_manager(
            {"store_name": "Acme"},
        ) == []


# ── Drop-in compatibility with program_designer ─────────────


class TestProgramDesignerCompat:
    """End-to-end: the handoff dict feeds straight into
    `design_program` and produces a success envelope.
    Confirms the niche template -> loyalty engine pipeline
    is wired correctly."""

    def test_design_program_accepts_template(self):
        template = generate_tier_template(
            store_name="Acme", niche="beauty",
        )
        config = hand_off_to_program_designer(template)
        result = design_program(
            program_config=config,
            customers=[
                {"id": "c1", "total_spent": 200,
                 "order_count": 3},
            ],
        )
        assert result.get("status") == "success"
        # design_program returns the program design at
        # result["design"]["tiers"]
        design = result.get("design") or {}
        out_tiers = design.get("tiers") or []
        names = [t["name"] for t in out_tiers]
        assert "bronze" in names
        assert "platinum" in names
        # And the niche-tuned silver threshold (beauty 1000)
        # made it through.
        silver = next(
            t for t in out_tiers if t["name"] == "silver"
        )
        assert silver["min_points"] == 1000

    def test_design_program_picks_up_niche_rate(self):
        template = generate_tier_template(
            store_name="Acme", niche="jewelry",
        )
        config = hand_off_to_program_designer(template)
        result = design_program(
            program_config=config,
            customers=[],
        )
        design = result.get("design") or {}
        # Jewelry rate is 1.0 (vs default 10.0)
        assert design.get("earning_rate") == 1.0


class TestTierManagerCompat:
    """The tier_manager path preserves the niche-aware
    multipliers + benefits."""

    def test_tier_manager_accepts_full_template(self):
        template = generate_tier_template(
            store_name="Acme", niche="jewelry",
        )
        tiers = hand_off_to_tier_manager(template)
        result = manage_tiers(
            points_calculations=[
                {"customer_id": "c1",
                 "points_balance": 50},  # bronze
                {"customer_id": "c2",
                 "points_balance": 3000},  # silver (2000)
                {"customer_id": "c3",
                 "points_balance": 12000},  # gold (10000)
            ],
            tiers=tiers,
        )
        assert result.get("status") == "success"
        statuses = result.get("statuses") or []
        by_id = {s["customer_id"]: s for s in statuses}
        assert by_id["c1"]["current_tier"] == "bronze"
        assert by_id["c2"]["current_tier"] == "silver"
        assert by_id["c3"]["current_tier"] == "gold"
