"""Tests for engines.cro_variants — W963-11."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.cro_variants import CroVariantsEngine
from engines.cro_variants.variant_generator import (
    description_variants,
    price_variants,
    title_variants,
)


# ── Title variant generation ──────────────────────────────


class TestTitleVariants:
    def test_empty_title_returns_empty(self):
        assert title_variants(title="") == []

    def test_three_angles_returned(self):
        v = title_variants(
            title="Vitamin C Serum",
            category="skincare",
        )
        angles = {x.angle for x in v}
        assert angles == {"feature", "benefit", "urgency"}

    def test_benefit_uses_category_phrase(self):
        v = title_variants(
            title="Bamboo Spice Rack",
            category="kitchen",
        )
        benefit = next(x for x in v if x.angle == "benefit")
        assert "Cook" in benefit.text  # kitchen phrase

    def test_unknown_category_falls_back(self):
        v = title_variants(
            title="Mystery Item", category="unknown_cat",
        )
        benefit = next(x for x in v if x.angle == "benefit")
        assert benefit.text  # non-empty

    def test_urgency_includes_limited(self):
        v = title_variants(title="Test Product")
        urgency = next(x for x in v if x.angle == "urgency")
        assert "Limited" in urgency.text or "Fast" in urgency.text


# ── Description variant generation ────────────────────────


class TestDescriptionVariants:
    def test_empty_title_returns_empty(self):
        v = description_variants(
            description="x", title="",
        )
        assert v == []

    def test_three_strategies(self):
        v = description_variants(
            description="Daily moisturizer.",
            title="Hydra Cream",
            category="skincare",
        )
        strats = {x.strategy for x in v}
        assert strats == {
            "short", "value_prop", "social_proof",
        }

    def test_strips_html(self):
        v = description_variants(
            description="<p>Plain after strip.</p>",
            title="Test",
        )
        short = next(x for x in v if x.strategy == "short")
        # Short variant re-wraps in <p>, but the inner content
        # should NOT contain raw original tags.
        assert "<p><strong>Plain after strip.</strong></p>" in short.text

    def test_empty_description_synthesizes(self):
        v = description_variants(
            description="", title="Bamboo Spice Rack",
        )
        short = next(x for x in v if x.strategy == "short")
        assert "spice rack" in short.text.lower()


# ── Price variant generation ──────────────────────────────


class TestPriceVariants:
    def test_zero_price_returns_empty(self):
        assert price_variants(current_price=0) == []

    def test_three_labels(self):
        v = price_variants(current_price=19.99)
        labels = {x.label for x in v}
        assert labels == {
            "current", "discount_10", "premium_15",
        }

    def test_current_price_preserved(self):
        v = price_variants(current_price=29.50)
        cur = next(x for x in v if x.label == "current")
        assert cur.price == 29.50

    def test_discount_rounds_to_99(self):
        v = price_variants(current_price=20.00)
        d = next(x for x in v if x.label == "discount_10")
        # 20 * 0.9 = 18 -> round to 17.99 (.99 ending)
        assert str(d.price).endswith(".99")

    def test_premium_higher_than_current(self):
        v = price_variants(current_price=10.00)
        cur = next(x for x in v if x.label == "current").price
        prem = next(
            x for x in v if x.label == "premium_15"
        ).price
        assert prem > cur


# ── Engine Pattern Q envelope ─────────────────────────────


class TestEngineEnvelope:
    def test_empty_input_error(self):
        result = CroVariantsEngine().run({})
        assert result["status"] == "error"

    def test_none_input_error(self):
        result = CroVariantsEngine().run(None)
        # Empty becomes {} -> no product -> error
        assert result["status"] == "error"

    def test_non_dict_error(self):
        result = CroVariantsEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = CroVariantsEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_missing_title_error(self):
        result = CroVariantsEngine().run({
            "data": {"product": {"description": "x"}},
        })
        assert result["status"] == "error"


# ── Engine happy path ─────────────────────────────────────


class TestEngineHappyPath:
    def test_synthetic_product_all_strategies(self):
        result = CroVariantsEngine().run({
            "data": {"product": {
                "title": "Vitamin C Serum",
                "description": "Daily brightening serum.",
                "category": "skincare",
                "price": 19.99,
            }},
        })
        assert result["status"] == "success"
        d = result["data"]
        assert len(d["variants"]["title"]) == 3
        assert len(d["variants"]["description"]) == 3
        assert len(d["variants"]["price"]) == 3

    def test_strategy_filter(self):
        result = CroVariantsEngine().run({
            "data": {
                "product": {"title": "T", "price": 10},
                "strategies": ["title"],
            },
        })
        assert "title" in result["data"]["variants"]
        assert "description" not in result["data"]["variants"]
        assert "price" not in result["data"]["variants"]

    def test_strategies_string_csv(self):
        result = CroVariantsEngine().run({
            "data": {
                "product": {"title": "T", "price": 10},
                "strategies": "title,price",
            },
        })
        assert set(result["data"]["variants"].keys()) == {
            "title", "price",
        }


class TestEngineHydration:
    def test_hydrate_via_router_success(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={
                "title": "Hydrated Product",
                "body_html": "<p>desc</p>",
                "product_type": "skincare",
                "price": 25.00,
            },
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ):
            result = CroVariantsEngine().run({
                "data": {"product_id": "gid://shopify/Product/1"},
            })
        assert result["status"] == "success"
        assert result["data"]["product_title"] == "Hydrated Product"

    def test_hydrate_failure_yields_error(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=False, data=None, error="not found",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ):
            result = CroVariantsEngine().run({
                "data": {"product_id": "gid://shopify/Product/X"},
            })
        assert result["status"] == "error"
