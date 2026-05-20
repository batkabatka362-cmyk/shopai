"""Tests for ``engines.store_setup.newsletter_popup``.

Niche-aware popup content for first-visit + exit-intent
modals. Persists as Shopify page (``newsletter-popup``).

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: both variants present.
  3. Generator: full shape per variant.
  4. Generator: niche-aware copy distinct across niches.
  5. Generator: discount_code/pct integration (operator
     override + niche default).
  6. Generator: discount_pct=0 / blank code falls back to
     niche default.
  7. Generator: first_visit_delay_seconds is encoded in
     trigger.
  8. Generator: every niche resolves (no KeyError).
  9. Generator: success_message references the code.
 10. Generator: form CTA label includes the percent.
 11. Renderer: empty / non-dict.
 12. Renderer: both sections render.
 13. Renderer: HTML-escapes content.
 14. Applier: empty short-circuit.
 15. Applier: success + Pattern Z metrics.
 16. Applier: router_unavailable / rejection / raise.
 17. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.newsletter_popup import (
    _NICHE_COPY,
    _extract_pct,
    _swap_pct,
    apply_popups,
    generate_newsletter_popups,
    render_popups_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_newsletter_popups(
            store_name="",
        ) == {}
        assert generate_newsletter_popups(
            store_name="   ",
        ) == {}
        assert generate_newsletter_popups(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_both_variants_present(self):
        spec = generate_newsletter_popups(
            store_name="Acme", niche="beauty",
        )
        assert "first_visit" in spec["variants"]
        assert "exit_intent" in spec["variants"]

    def test_full_shape_per_variant(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
        )
        for key in ("first_visit", "exit_intent"):
            v = spec["variants"][key]
            assert v["headline"], key
            assert v["subhead"], key
            assert v["form_cta_label"], key
            assert v["success_message"], key
            assert v["decline_link_label"], key
            assert v["trigger"], key

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_newsletter_popups(
                store_name="Acme", niche=niche,
            )
            assert spec["variants"]


class TestNicheTone:

    def test_distinct_copy_per_niche(self):
        """The 10 specific niches should each have their
        own distinct first-visit headline."""
        seen: set[str] = set()
        for niche in _NICHE_COPY:
            if niche == "general":
                continue
            headline = _NICHE_COPY[niche][0]
            assert headline not in seen, niche
            seen.add(headline)

    def test_unknown_niche_falls_back(self):
        spec = generate_newsletter_popups(
            store_name="Acme", niche="ufo_parts",
        )
        general_headline = _NICHE_COPY["general"][0]
        assert (
            spec["variants"]["first_visit"]["headline"]
            == general_headline
        )

    def test_niche_specific_cues(self):
        """Each niche surfaces a category-relevant cue
        in headline or subhead text (any of the listed
        snippets matches)."""
        cases = {
            "beauty": ("skincare",),
            "fashion": ("size", "style"),
            "tech": ("tech",),
            "food": ("pantry", "flavour"),
            "pets": ("pet",),
            "fitness": ("performance", "gear"),
            "jewelry": ("metal", "stone"),
            "outdoor": ("trail", "trip", "field-tested",
                        "gear"),
            "baby": ("baby", "parent"),
        }
        for niche, snippets in cases.items():
            spec = generate_newsletter_popups(
                store_name="Acme", niche=niche,
            )
            fv = spec["variants"]["first_visit"]
            ei = spec["variants"]["exit_intent"]
            blob = " ".join((
                fv["headline"], fv["subhead"],
                ei["headline"], ei["subhead"],
            )).lower()
            assert any(s in blob for s in snippets), (
                niche, snippets, blob[:200],
            )


class TestDiscountIntegration:

    def test_default_pct_per_niche(self):
        """Beauty / fashion / pets / fitness / baby = 15%;
        tech / home / food / jewelry / outdoor / general
        = 10%."""
        cases = {
            "beauty": 15, "fashion": 15, "pets": 15,
            "fitness": 15, "baby": 15,
            "tech": 10, "home": 10, "food": 10,
            "jewelry": 10, "outdoor": 10, "general": 10,
        }
        for niche, expected in cases.items():
            spec = generate_newsletter_popups(
                store_name="Acme", niche=niche,
            )
            fv = spec["variants"]["first_visit"]
            assert fv["discount_pct"] == expected, niche
            assert fv["discount_code"] == (
                f"WELCOME{expected}"
            ), niche

    def test_operator_override_pct(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
            niche="tech",  # default 10%
            discount_pct=20,
        )
        fv = spec["variants"]["first_visit"]
        # Percent override surfaced
        assert fv["discount_pct"] == 20
        # Headline updated to "20%"
        assert "20%" in fv["headline"]
        # Default code is WELCOME20 unless overridden
        assert fv["discount_code"] == "WELCOME20"
        # Form CTA reflects the percent
        assert "20%" in fv["form_cta_label"]

    def test_operator_override_code(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
            niche="beauty",
            discount_code="MYCODE",
            discount_pct=25,
        )
        fv = spec["variants"]["first_visit"]
        assert fv["discount_code"] == "MYCODE"
        # Success message references the custom code
        assert "MYCODE" in fv["success_message"]

    def test_zero_pct_uses_niche_default(self):
        """Zero pct override falls back to niche default."""
        spec = generate_newsletter_popups(
            store_name="Acme",
            niche="beauty",
            discount_pct=0,
        )
        fv = spec["variants"]["first_visit"]
        # Beauty default is 15%
        assert fv["discount_pct"] == 15

    def test_code_uppercased(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
            discount_code="mycode10",
            discount_pct=10,
        )
        assert (
            spec["variants"]["first_visit"]["discount_code"]
            == "MYCODE10"
        )


class TestTriggers:

    def test_default_first_visit_delay(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
        )
        trigger = (
            spec["variants"]["first_visit"]["trigger"]
        )
        assert "15s delay" in trigger
        assert "first visit" in trigger

    def test_custom_first_visit_delay(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
            first_visit_delay_seconds=5,
        )
        trigger = (
            spec["variants"]["first_visit"]["trigger"]
        )
        assert "5s delay" in trigger

    def test_exit_intent_trigger_set(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
        )
        trigger = (
            spec["variants"]["exit_intent"]["trigger"]
        )
        assert "exit intent" in trigger

    def test_both_triggers_carry_suppression_window(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
        )
        for key in ("first_visit", "exit_intent"):
            trigger = (
                spec["variants"][key]["trigger"]
            )
            assert "30d" in trigger
            assert "suppressed" in trigger.lower()


class TestSuccessMessageAndCta:

    def test_success_message_includes_code(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
            niche="beauty",
        )
        fv = spec["variants"]["first_visit"]
        # Default code is WELCOME15
        assert "WELCOME15" in fv["success_message"]

    def test_cta_label_includes_percent(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
            niche="beauty",
        )
        fv = spec["variants"]["first_visit"]
        assert "15% off" in fv["form_cta_label"]

    def test_distinct_decline_labels(self):
        """First visit gets a more substantive decline
        label; exit-intent stays terse."""
        spec = generate_newsletter_popups(
            store_name="Acme",
        )
        assert (
            spec["variants"]["first_visit"][
                "decline_link_label"
            ] != (
                spec["variants"]["exit_intent"][
                    "decline_link_label"
                ]
            )
        )


# ── Helpers ──────────────────────────────────────────────────


class TestHelpers:

    def test_extract_pct(self):
        assert _extract_pct("Save 15% on first order") == 15
        assert _extract_pct("Get 10% off") == 10
        assert _extract_pct("No percent here") is None
        assert _extract_pct("") is None

    def test_swap_pct(self):
        assert (
            _swap_pct("Save 15% on first order", 25)
            == "Save 25% on first order"
        )
        # No-match returns unchanged
        assert (
            _swap_pct("Plain text", 10) == "Plain text"
        )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_popups_html({}) == ""
        assert render_popups_html(None) == ""  # type: ignore[arg-type]
        assert (
            render_popups_html({"store_name": "Acme"}) == ""
        )

    def test_both_sections_render(self):
        spec = generate_newsletter_popups(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_popups_html(spec)
        assert "Acme Beauty" in html_out
        assert "First Visit" in html_out
        assert "Exit Intent" in html_out
        # Trigger lines surfaced
        assert "30d" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "variants": {
                "first_visit": {
                    "headline": "<b>h</b>",
                    "subhead": "x & y",
                    "form_cta_label": "ok",
                    "success_message": "<i>m</i>",
                    "decline_link_label": "no",
                    "discount_code": "WELCOME15",
                    "discount_pct": 15,
                    "trigger": "first visit",
                },
            },
        }
        html_out = render_popups_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>h</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_popups({})
        assert out["applied"] is False
        assert out["error"] == "no_popup_spec"

    def test_non_dict(self):
        out = apply_popups(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_variants(self):
        out = apply_popups({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_newsletter_popups(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.newsletter_popup."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.newsletter_popup."
            "record_writeback",
        ) as record_mock:
            out = apply_popups(spec)
        assert out["applied"] is True
        assert out["handle"] == "newsletter-popup"
        params = router.execute.call_args.args[1]
        assert (
            params["title"] == "Newsletter Signup Popup"
        )
        assert params["handle"] == "newsletter-popup"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["variant_count"] == 2
        assert kwargs["metrics"]["niche"] == "beauty"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_newsletter_popups(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.newsletter_popup."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.newsletter_popup."
            "record_writeback",
        ) as record_mock:
            out = apply_popups(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"]
            is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_newsletter_popups(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.newsletter_popup."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.newsletter_popup."
            "record_writeback",
        ):
            out = apply_popups(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_newsletter_popups(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.newsletter_popup."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.newsletter_popup."
            "record_writeback",
        ):
            out = apply_popups(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_newsletter_popups(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.newsletter_popup."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.newsletter_popup."
            "record_writeback",
        ) as record_mock:
            apply_popups(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
