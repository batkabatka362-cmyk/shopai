"""Tests for ``engines.store_setup.thank_you_card``.

Niche-aware physical-insert thank-you card content.

Coverage:
  1. Empty store_name -> empty dict.
  2. Card has all 7 base fields.
  3. Every niche resolves.
  4. Niche-specific ask_type (review/share/subscribe/etc.).
  5. Discount code threaded when supplied.
  6. No code = no discount block.
  7. Design notes per niche.
  8. Liquid placeholders preserved.
  9. Renderer: empty / non-dict.
 10. Renderer: full card content + design notes.
 11. Renderer: discount block when present.
 12. Renderer: HTML escape.
 13. Applier: empty short-circuit.
 14. Applier: success + Pattern Z (ask_type metric).
 15. Applier: failure modes.
 16. Store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.thank_you_card import (
    _NICHE_CARDS,
    apply_thank_you_card_content,
    generate_thank_you_card_content,
    render_card_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_thank_you_card_content(
            store_name="",
        ) == {}
        assert generate_thank_you_card_content(
            store_name="   ",
        ) == {}
        assert generate_thank_you_card_content(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_card_has_base_fields(self):
        spec = generate_thank_you_card_content(
            store_name="Acme", niche="beauty",
        )
        card = spec["card"]
        for field in (
            "greeting", "value_statement", "ask_type",
            "ask_copy", "qr_target_url", "signature",
        ):
            assert card[field], field

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_thank_you_card_content(
                store_name="Acme", niche=niche,
            )
            assert spec["card"]

    def test_design_notes_present(self):
        for niche in _NICHE_CARDS:
            spec = generate_thank_you_card_content(
                store_name="Acme", niche=niche,
            )
            assert spec["design_notes"]
            assert len(spec["design_notes"]) >= 30


class TestNicheTuning:

    def test_beauty_ask_is_review_with_photo(self):
        spec = generate_thank_you_card_content(
            store_name="Acme", niche="beauty",
        )
        assert (
            spec["card"]["ask_type"]
            == "review_with_photo"
        )

    def test_food_pets_ask_is_subscribe(self):
        for niche in ("food", "pets"):
            spec = generate_thank_you_card_content(
                store_name="Acme", niche=niche,
            )
            assert (
                spec["card"]["ask_type"]
                == "subscribe_and_save"
            )

    def test_tech_ask_is_warranty(self):
        spec = generate_thank_you_card_content(
            store_name="Acme", niche="tech",
        )
        assert (
            spec["card"]["ask_type"]
            == "warranty_registration"
        )

    def test_jewelry_ask_is_care_guide(self):
        spec = generate_thank_you_card_content(
            store_name="Acme", niche="jewelry",
        )
        assert (
            spec["card"]["ask_type"] == "care_guide"
        )

    def test_fitness_ask_is_referral(self):
        spec = generate_thank_you_card_content(
            store_name="Acme", niche="fitness",
        )
        assert spec["card"]["ask_type"] == "referral"

    def test_baby_ask_is_age_stage(self):
        spec = generate_thank_you_card_content(
            store_name="Acme", niche="baby",
        )
        assert (
            spec["card"]["ask_type"]
            == "age_stage_signup"
        )

    def test_unknown_niche_falls_back(self):
        spec = generate_thank_you_card_content(
            store_name="Acme", niche="ufo_parts",
        )
        # general's ask is "review"
        assert spec["card"]["ask_type"] == "review"


class TestDiscountIntegration:

    def test_discount_code_threaded(self):
        spec = generate_thank_you_card_content(
            store_name="Acme",
            discount_code="THANKS10",
            discount_pct=10,
        )
        card = spec["card"]
        assert card["discount_code"] == "THANKS10"
        assert card["discount_pct"] == 10
        assert "THANKS10" in card["discount_copy"]
        assert "10%" in card["discount_copy"]

    def test_no_code_no_discount_block(self):
        spec = generate_thank_you_card_content(
            store_name="Acme",
        )
        card = spec["card"]
        assert card["discount_code"] is None
        assert card["discount_pct"] is None
        assert card["discount_copy"] is None

    def test_code_uppercased(self):
        spec = generate_thank_you_card_content(
            store_name="Acme",
            discount_code="thanks10",
            discount_pct=10,
        )
        assert spec["card"]["discount_code"] == "THANKS10"

    def test_zero_pct_ignored(self):
        spec = generate_thank_you_card_content(
            store_name="Acme",
            discount_code="THANKS0",
            discount_pct=0,
        )
        # 0 pct -> no discount block
        assert spec["card"]["discount_code"] is None


class TestLiquidPlaceholders:

    def test_first_name_in_greeting(self):
        spec = generate_thank_you_card_content(
            store_name="Acme",
        )
        assert (
            "{{first_name}}"
            in spec["card"]["greeting"]
        )

    def test_qr_target_uses_shop_url(self):
        spec = generate_thank_you_card_content(
            store_name="Acme", niche="beauty",
        )
        # Most niches use {{shop.url}} or
        # https://instagram... templates
        url = spec["card"]["qr_target_url"]
        assert (
            "{{shop.url}}" in url
            or url.startswith("https://")
        )

    def test_signature_uses_store_name(self):
        spec = generate_thank_you_card_content(
            store_name="Acme Beauty",
        )
        assert "Acme Beauty" in spec["card"]["signature"]


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_card_html({}) == ""
        assert render_card_html(None) == ""  # type: ignore[arg-type]

    def test_renders_card_copy_section(self):
        spec = generate_thank_you_card_content(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_card_html(spec)
        assert "Acme Beauty" in html_out
        assert "Card Copy" in html_out
        assert "Design Notes" in html_out
        # Ask type rendered
        assert "review_with_photo" in html_out

    def test_renders_discount_block_when_present(self):
        spec = generate_thank_you_card_content(
            store_name="Acme",
            discount_code="THANKS10",
            discount_pct=10,
        )
        html_out = render_card_html(spec)
        assert "Discount Block" in html_out
        assert "THANKS10" in html_out

    def test_no_discount_block_when_absent(self):
        spec = generate_thank_you_card_content(
            store_name="Acme",
        )
        html_out = render_card_html(spec)
        assert "Discount Block" not in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "card": {
                "greeting": "<b>Hi</b>",
                "value_statement": "x & y",
                "ask_type": "test",
                "ask_copy": "<i>ask</i>",
                "qr_target_url": "<a>url</a>",
                "discount_code": None,
                "discount_pct": None,
                "discount_copy": None,
                "signature": "sig",
            },
            "design_notes": "<em>notes</em>",
        }
        html_out = render_card_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>Hi</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_thank_you_card_content({})
        assert out["applied"] is False
        assert out["error"] == "no_thank_you_spec"

    def test_non_dict(self):
        out = apply_thank_you_card_content(None)  # type: ignore[arg-type]
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_thank_you_card_content(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.thank_you_card."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.thank_you_card."
            "record_writeback",
        ) as record_mock:
            out = apply_thank_you_card_content(spec)
        assert out["applied"] is True
        assert out["handle"] == "thank-you-card-content"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert (
            kwargs["metrics"]["ask_type"]
            == "review_with_photo"
        )


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_thank_you_card_content(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.thank_you_card."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.thank_you_card."
            "record_writeback",
        ):
            out = apply_thank_you_card_content(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_thank_you_card_content(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.thank_you_card."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.thank_you_card."
            "record_writeback",
        ):
            out = apply_thank_you_card_content(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_thank_you_card_content(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.thank_you_card."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.thank_you_card."
            "record_writeback",
        ) as record_mock:
            apply_thank_you_card_content(
                spec, store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
