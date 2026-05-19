"""Tests for ``engines.store_setup.subscription_templates``.

Niche-aware subscription / selling-plan recommendations.

Coverage:
  1. Empty store_name -> empty dict.
  2. Every niche has at least 1 plan.
  3. Each plan has full shape (8 fields).
  4. Frequency uses ISO-8601 duration.
  5. Discount % in plausible range (5-30).
  6. Priority >= 1.
  7. Niche-specific tuning: food has weekly, baby
     has monthly diapers, pets has monthly food,
     fitness has supplements.
  8. Every niche resolves.
  9. Pitch strategy present per niche.
 10. Renderer: empty / non-dict.
 11. Renderer: produces plan sections + pitch
     strategy note.
 12. Renderer: HTML escape.
 13. Applier: empty short-circuit.
 14. Applier: success + Pattern Z.
 15. Applier: failure modes.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.subscription_templates import (
    _NICHE_PLANS,
    _PITCH_STRATEGIES,
    apply_subscription_templates,
    generate_subscription_templates,
    render_subscription_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_subscription_templates(
            store_name="",
        ) == {}
        assert generate_subscription_templates(
            store_name="   ",
        ) == {}
        assert generate_subscription_templates(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_every_niche_has_plans(self):
        for niche in _NICHE_PLANS:
            spec = generate_subscription_templates(
                store_name="Acme", niche=niche,
            )
            assert spec["plans"], niche

    def test_each_plan_has_full_shape(self):
        for niche in _NICHE_PLANS:
            spec = generate_subscription_templates(
                store_name="Acme", niche=niche,
            )
            for p in spec["plans"]:
                assert p["name"], niche
                assert p["frequency"], niche
                assert p["frequency_label"], niche
                assert isinstance(
                    p["discount_pct"], int,
                )
                assert isinstance(
                    p["eligible_categories"], list,
                )
                assert p["cancel_policy"], niche
                assert p["rationale"], niche
                assert p["priority"] >= 1


class TestFrequencyFormat:

    def test_iso_8601_durations(self):
        """All frequency values follow ISO-8601:
        P[number]W/M/D."""
        valid_starts = ("P1W", "P2W", "P1M", "P3M", "P6M")
        for niche in _NICHE_PLANS:
            spec = generate_subscription_templates(
                store_name="Acme", niche=niche,
            )
            for p in spec["plans"]:
                assert (
                    p["frequency"] in valid_starts
                ), (niche, p["frequency"])


class TestDiscountBounds:

    def test_discount_in_plausible_range(self):
        """Subscription discount typically 5-30%."""
        for niche in _NICHE_PLANS:
            spec = generate_subscription_templates(
                store_name="Acme", niche=niche,
            )
            for p in spec["plans"]:
                assert 5 <= p["discount_pct"] <= 30, (
                    niche, p["discount_pct"],
                )


class TestNicheTuning:

    def test_food_has_weekly(self):
        spec = generate_subscription_templates(
            store_name="Acme", niche="food",
        )
        freqs = {p["frequency"] for p in spec["plans"]}
        assert "P1W" in freqs

    def test_baby_has_monthly_diapers(self):
        spec = generate_subscription_templates(
            store_name="Acme", niche="baby",
        )
        baby_plans = spec["plans"]
        # First baby plan = Monthly Essentials with
        # diapers / wipes / formula
        first = baby_plans[0]
        assert first["frequency"] == "P1M"
        assert any(
            cat in first["eligible_categories"]
            for cat in ("diapers", "wipes", "formula")
        )

    def test_pets_has_monthly_food(self):
        spec = generate_subscription_templates(
            store_name="Acme", niche="pets",
        )
        plans = spec["plans"]
        monthly_food = [
            p for p in plans
            if p["frequency"] == "P1M"
            and "food" in p["eligible_categories"]
        ]
        assert monthly_food

    def test_fitness_has_supplements(self):
        spec = generate_subscription_templates(
            store_name="Acme", niche="fitness",
        )
        plans = spec["plans"]
        assert any(
            "supplements" in p["eligible_categories"]
            for p in plans
        )

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_subscription_templates(
                store_name="Acme", niche=niche,
            )
            assert spec["plans"]


class TestPitchStrategy:

    def test_every_niche_has_pitch_strategy(self):
        for niche in _NICHE_PLANS:
            spec = generate_subscription_templates(
                store_name="Acme", niche=niche,
            )
            assert spec["pitch_strategy"]
            assert len(spec["pitch_strategy"]) >= 20

    def test_food_pitch_is_above_fold(self):
        """Food has highest subscription LTV; pitch
        strategy should say so."""
        spec = generate_subscription_templates(
            store_name="Acme", niche="food",
        )
        strategy = spec["pitch_strategy"].lower()
        assert (
            "above the fold" in strategy
            or "highest-ltv" in strategy
        )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_subscription_html({}) == ""
        assert render_subscription_html(None) == ""  # type: ignore[arg-type]

    def test_renders_plan_sections(self):
        spec = generate_subscription_templates(
            store_name="Acme Pets", niche="pets",
        )
        html_out = render_subscription_html(spec)
        assert "Acme Pets" in html_out
        # Each plan rendered as h2
        expected_count = len(spec["plans"])
        h2_count = html_out.count("<h2>")
        assert h2_count == expected_count
        # Pitch strategy block present
        assert "Pitch strategy" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "pets",
            "plans": [
                {
                    "name": "<b>P</b>",
                    "frequency": "P1M",
                    "frequency_label": "monthly",
                    "discount_pct": 10,
                    "eligible_categories": ["food"],
                    "cancel_policy": "x & y",
                    "rationale": "<i>r</i>",
                    "priority": 1,
                },
            ],
            "pitch_strategy": "<em>s</em>",
        }
        html_out = render_subscription_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>P</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_subscription_templates({})
        assert out["applied"] is False
        assert out["error"] == "no_subscription_spec"

    def test_non_dict(self):
        out = apply_subscription_templates(None)  # type: ignore[arg-type]
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_subscription_templates(
            store_name="Acme", niche="pets",
        )
        with patch(
            "engines.store_setup."
            "subscription_templates._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup."
            "subscription_templates.record_writeback",
        ) as record_mock:
            out = apply_subscription_templates(spec)
        assert out["applied"] is True
        assert out["handle"] == "subscription-plans"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["niche"] == "pets"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_subscription_templates(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup."
            "subscription_templates._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup."
            "subscription_templates.record_writeback",
        ):
            out = apply_subscription_templates(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_subscription_templates(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup."
            "subscription_templates._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup."
            "subscription_templates.record_writeback",
        ):
            out = apply_subscription_templates(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_subscription_templates(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup."
            "subscription_templates._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup."
            "subscription_templates.record_writeback",
        ) as record_mock:
            apply_subscription_templates(
                spec, store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
