"""Tests for ``engines.store_setup.order_confirmation_content``.

Generator produces order_confirmation + shipping_confirmation
email content blocks; applier persists as a Shopify page.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: both templates always present.
  3. Generator: every variant has subject + preheader +
     pre_receipt_text/html + post_receipt_text/html +
     trigger.
  4. Generator: every niche resolves.
  5. Generator: niche-specific cues distinct across
     niches.
  6. Generator: store_name interpolated into post-
     receipt sign-off.
  7. Generator: Liquid {{first_name}} preserved in
     pre-receipt.
  8. Generator: unknown niche falls back.
  9. Renderer: empty -> empty.
 10. Renderer: produces both sections.
 11. Renderer: HTML-escapes content.
 12. Applier: empty short-circuit.
 13. Applier: success + Pattern Z.
 14. Applier: router_unavailable / rejection / raise.
 15. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.order_confirmation_content import (
    _NICHE_COPY,
    apply_order_confirmation_content,
    generate_order_confirmation_content,
    render_order_emails_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_order_confirmation_content(
            store_name="",
        ) == {}
        assert generate_order_confirmation_content(
            store_name="   ",
        ) == {}
        assert generate_order_confirmation_content(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_both_templates_present(self):
        spec = generate_order_confirmation_content(
            store_name="Acme", niche="beauty",
        )
        assert "order_confirmation" in spec["templates"]
        assert "shipping_confirmation" in spec["templates"]

    def test_every_template_has_full_shape(self):
        spec = generate_order_confirmation_content(
            store_name="Acme",
        )
        for key in (
            "order_confirmation",
            "shipping_confirmation",
        ):
            t = spec["templates"][key]
            assert t["subject"], key
            assert t["preheader"], key
            assert t["pre_receipt_text"], key
            assert t["pre_receipt_html"], key
            assert t["post_receipt_text"], key
            assert t["post_receipt_html"], key
            assert t["trigger"], key

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_order_confirmation_content(
                store_name="Acme", niche=niche,
            )
            assert spec["templates"]

    def test_unknown_niche_falls_back(self):
        spec = generate_order_confirmation_content(
            store_name="Acme", niche="ufo_parts",
        )
        general_subject = _NICHE_COPY["general"][0]
        assert (
            spec["templates"]["order_confirmation"][
                "subject"
            ] == general_subject
        )

    def test_store_name_in_signoff(self):
        spec = generate_order_confirmation_content(
            store_name="Acme Beauty",
        )
        for key in (
            "order_confirmation",
            "shipping_confirmation",
        ):
            t = spec["templates"][key]
            assert "Acme Beauty" in t["post_receipt_text"]
            assert "Acme Beauty" in t["post_receipt_html"]

    def test_liquid_placeholder_preserved(self):
        spec = generate_order_confirmation_content(
            store_name="Acme",
        )
        for key in (
            "order_confirmation",
            "shipping_confirmation",
        ):
            t = spec["templates"][key]
            assert "{{first_name}}" in t["pre_receipt_text"]
            assert "{{first_name}}" in t["pre_receipt_html"]


class TestNicheTone:

    def test_distinct_subjects_per_niche(self):
        """At least half of the 10 specific niches have
        their own OC subject -- some niches reasonably
        share a generic phrasing (home + fashion both say
        'new pieces')."""
        subjects = {
            niche: copy[0]
            for niche, copy in _NICHE_COPY.items()
            if niche != "general"
        }
        distinct = len(set(subjects.values()))
        assert distinct >= 6, (distinct, subjects)

    def test_niche_specific_cues(self):
        """Each niche surfaces a category-relevant cue."""
        cases = {
            "beauty": ("routine", "ingredient"),
            "fashion": ("fit",),
            "tech": ("spec", "warranty",
                     "quickstart", "guides"),
            "food": ("pantry", "recipe", "transit"),
            "pets": ("pet",),
            "jewelry": ("insurance", "appraisal",
                        "tarnish"),
            "baby": ("stage", "grow"),
        }
        for niche, snippets in cases.items():
            spec = generate_order_confirmation_content(
                store_name="Acme", niche=niche,
            )
            blob = " ".join((
                spec["templates"]["order_confirmation"][
                    "pre_receipt_text"
                ],
                spec["templates"]["order_confirmation"][
                    "post_receipt_text"
                ],
                spec["templates"]["shipping_confirmation"][
                    "pre_receipt_text"
                ],
                spec["templates"]["shipping_confirmation"][
                    "post_receipt_text"
                ],
            )).lower()
            assert any(s in blob for s in snippets), (
                niche, snippets, blob[:200],
            )


class TestTriggers:

    def test_order_confirmation_trigger(self):
        spec = generate_order_confirmation_content(
            store_name="Acme",
        )
        assert (
            "immediately on checkout"
            in spec["templates"]["order_confirmation"][
                "trigger"
            ]
        )

    def test_shipping_confirmation_trigger(self):
        spec = generate_order_confirmation_content(
            store_name="Acme",
        )
        assert (
            "ships"
            in spec["templates"]["shipping_confirmation"][
                "trigger"
            ]
        )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_order_emails_html({}) == ""
        assert render_order_emails_html(None) == ""  # type: ignore[arg-type]
        assert (
            render_order_emails_html({
                "store_name": "Acme",
            }) == ""
        )

    def test_renders_both_sections(self):
        spec = generate_order_confirmation_content(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_order_emails_html(spec)
        assert "Acme Beauty" in html_out
        assert "Order Confirmation" in html_out
        assert "Shipping Confirmation" in html_out
        # Pre + post receipt blocks for both templates
        assert html_out.count("Pre-receipt") == 4
        assert html_out.count("Post-receipt") == 4

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "templates": {
                "order_confirmation": {
                    "subject": "<b>S</b>",
                    "preheader": "x & y",
                    "pre_receipt_text": "",
                    "pre_receipt_html": "",
                    "post_receipt_text": "",
                    "post_receipt_html": "",
                    "trigger": "now",
                },
            },
        }
        html_out = render_order_emails_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>S</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_order_confirmation_content({})
        assert out["applied"] is False
        assert out["error"] == "no_order_email_spec"

    def test_non_dict(self):
        out = apply_order_confirmation_content(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_templates(self):
        out = apply_order_confirmation_content(
            {"store_name": "Acme"},
        )
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_order_confirmation_content(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.order_confirmation_content."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.order_confirmation_content."
            "record_writeback",
        ) as record_mock:
            out = apply_order_confirmation_content(spec)
        assert out["applied"] is True
        assert out["handle"] == "order-confirmation-email"
        params = router.execute.call_args.args[1]
        assert (
            params["title"]
            == "Order Confirmation Email"
        )
        assert (
            params["handle"]
            == "order-confirmation-email"
        )
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["template_count"] == 2
        assert kwargs["metrics"]["niche"] == "beauty"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_order_confirmation_content(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.order_confirmation_content."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.order_confirmation_content."
            "record_writeback",
        ) as record_mock:
            out = apply_order_confirmation_content(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"]
            is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_order_confirmation_content(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.order_confirmation_content."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.order_confirmation_content."
            "record_writeback",
        ):
            out = apply_order_confirmation_content(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_order_confirmation_content(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.order_confirmation_content."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.order_confirmation_content."
            "record_writeback",
        ):
            out = apply_order_confirmation_content(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_order_confirmation_content(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.order_confirmation_content."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.order_confirmation_content."
            "record_writeback",
        ) as record_mock:
            apply_order_confirmation_content(
                spec, store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
