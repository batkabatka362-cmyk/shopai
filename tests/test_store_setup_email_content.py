"""Tests for ``engines.store_setup.email_content``.

Generator produces welcome + abandoned-cart email templates;
applier persists them as a Shopify page (handle
``email-templates``) via ``SHOPIFY_CREATE_PAGE``. Records via
Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: both templates always present.
  3. Generator: subject + preheader + body_text + body_html
     for every template.
  4. Generator: niche-specific opening in welcome body.
  5. Generator: welcome discount code threaded when supplied.
  6. Generator: welcome WITHOUT discount has neutral CTA.
  7. Generator: every niche key resolves (no key error on
     extended niches).
  8. Generator: Liquid placeholders preserved in output.
  9. Renderer: empty spec.
 10. Renderer: produces both template sections.
 11. Renderer: HTML-escapes Liquid placeholders for safe
     paste-in viewing.
 12. Applier: empty short-circuit.
 13. Applier: success + Pattern Z metrics carry template
     count + niche.
 14. Applier: router_unavailable.
 15. Applier: adapter raise / rejection.
 16. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.email_content import (
    _CART_RECOVERY_LINES,
    _WELCOME_OPENINGS,
    apply_emails,
    generate_emails,
    render_emails_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_emails(store_name="") == {}
        assert generate_emails(store_name="   ") == {}
        assert generate_emails(store_name=None) == {}


class TestGeneratorShape:

    def test_both_templates_present(self):
        spec = generate_emails(
            store_name="Acme", niche="beauty",
        )
        assert "welcome" in spec["templates"]
        assert "abandoned_cart" in spec["templates"]

    def test_every_template_has_full_shape(self):
        spec = generate_emails(store_name="Acme")
        for key in ("welcome", "abandoned_cart"):
            tmpl = spec["templates"][key]
            assert tmpl["subject"], key
            assert tmpl["preheader"], key
            assert tmpl["body_text"], key
            assert tmpl["body_html"], key

    def test_store_name_in_subject(self):
        spec = generate_emails(
            store_name="Acme Beauty", niche="beauty",
        )
        assert "Acme Beauty" in (
            spec["templates"]["welcome"]["subject"]
        )

    def test_liquid_placeholders_preserved(self):
        """Klaviyo and Shopify-native templates use Liquid
        ``{{first_name}}``-style placeholders. Output must
        carry them verbatim so paste-in works."""
        spec = generate_emails(store_name="Acme")
        welcome = spec["templates"]["welcome"]
        assert "{{first_name}}" in welcome["body_text"]
        assert "{{first_name}}" in welcome["body_html"]

        cart = spec["templates"]["abandoned_cart"]
        assert "{{cart.recovery_url}}" in cart["body_text"]
        assert "{{cart.recovery_url}}" in cart["body_html"]


class TestNicheTone:

    def test_each_niche_has_distinct_opening(self):
        """Welcome opening must vary per niche, not the
        generic fallback."""
        for niche in _WELCOME_OPENINGS:
            spec = generate_emails(
                store_name="Acme", niche=niche,
            )
            opening = _WELCOME_OPENINGS[niche]
            # First 20 chars of the opening should appear in
            # the body (substring match -- escapes don't
            # matter since this is text body)
            head = opening[:20]
            assert head in (
                spec["templates"]["welcome"]["body_text"]
            ), niche

    def test_every_niche_resolves(self):
        """No KeyError on any extended niche."""
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_emails(
                store_name="Acme", niche=niche,
            )
            assert spec["templates"]["welcome"]["body_text"]

    def test_each_niche_distinct_cart_recovery(self):
        for niche in _CART_RECOVERY_LINES:
            spec = generate_emails(
                store_name="Acme", niche=niche,
            )
            recovery_line = _CART_RECOVERY_LINES[niche]
            head = recovery_line[:20]
            assert head in (
                spec["templates"][
                    "abandoned_cart"
                ]["body_text"]
            ), niche

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_emails(
            store_name="Acme", niche="ufo_parts",
        )
        general_opening = _WELCOME_OPENINGS["general"]
        # First 20 chars of the general opening should
        # appear -- confirms fallback
        head = general_opening[:20]
        assert head in (
            spec["templates"]["welcome"]["body_text"]
        )


class TestWelcomeDiscountIntegration:

    def test_discount_code_threaded_into_welcome(self):
        spec = generate_emails(
            store_name="Acme",
            niche="beauty",
            welcome_discount_code="WELCOME15",
            welcome_discount_pct=15,
        )
        welcome = spec["templates"]["welcome"]
        assert "WELCOME15" in welcome["body_text"]
        assert "WELCOME15" in welcome["body_html"]
        assert "15%" in welcome["body_text"]
        assert "15%" in welcome["preheader"]

    def test_no_discount_has_neutral_cta(self):
        spec = generate_emails(
            store_name="Acme", niche="beauty",
        )
        welcome = spec["templates"]["welcome"]
        # No discount = no "% off" copy
        assert "% off" not in welcome["body_text"]
        # CTA still present, just generic
        assert "Shop" in welcome["body_html"]

    def test_zero_discount_pct_ignored(self):
        """Zero pct = no real discount; CTA stays neutral."""
        spec = generate_emails(
            store_name="Acme",
            welcome_discount_code="WELCOME0",
            welcome_discount_pct=0,
        )
        welcome = spec["templates"]["welcome"]
        assert "0%" not in welcome["body_text"]

    def test_code_uppercased(self):
        spec = generate_emails(
            store_name="Acme",
            welcome_discount_code="welcome15",
            welcome_discount_pct=15,
        )
        assert (
            "WELCOME15"
            in spec["templates"]["welcome"]["body_text"]
        )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_emails_html({}) == ""
        assert render_emails_html(None) == ""  # type: ignore[arg-type]
        assert (
            render_emails_html({"store_name": "Acme"}) == ""
        )

    def test_renders_both_sections(self):
        spec = generate_emails(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_emails_html(spec)
        assert "<section class=\"email-templates\">" in html_out
        assert "Acme Beauty" in html_out
        # Both template sections
        assert "Welcome" in html_out
        assert "Abandoned Cart" in html_out
        # Subject / preheader labels
        assert "Subject" in html_out
        assert "Preheader" in html_out

    def test_escapes_liquid_placeholders(self):
        """Liquid placeholders must be HTML-escaped in the
        preview body so they show literally in the rendered
        page; the operator copies the unescaped versions out
        of the spec dict itself when pasting into Klaviyo."""
        spec = generate_emails(store_name="Acme")
        html_out = render_emails_html(spec)
        # Plain text body is HTML-escaped: { -> {
        # but {{ stays in the source. The wrapper <pre>
        # tag means {{ shows literally on the page.
        assert "{{first_name}}" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "templates": {
                "welcome": {
                    "subject": "<b>Subject</b>",
                    "preheader": "x & y",
                    "body_text": "",
                    "body_html": "",
                },
            },
        }
        html_out = render_emails_html(spec)
        assert "<script>x</script>" not in html_out
        assert "&lt;script&gt;" in html_out
        # Subject's <b> also escaped (no real tags from the
        # spec leak into the page).
        assert "<b>Subject</b>" not in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_emails({})
        assert out["applied"] is False
        assert out["error"] == "no_email_spec"

    def test_non_dict(self):
        out = apply_emails(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_templates(self):
        out = apply_emails({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_emails(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.email_content._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.email_content."
            "record_writeback",
        ) as record_mock:
            out = apply_emails(spec)
        assert out["applied"] is True
        assert out["handle"] == "email-templates"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Email Templates"
        assert params["handle"] == "email-templates"
        assert "email-templates" in params["body_html"]
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["template_count"] == 2
        assert kwargs["metrics"]["niche"] == "beauty"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_emails(store_name="Acme")
        with patch(
            "engines.store_setup.email_content._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.email_content."
            "record_writeback",
        ) as record_mock:
            out = apply_emails(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        record_mock.assert_called_once()
        assert (
            record_mock.call_args.kwargs["success"] is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_emails(store_name="Acme")
        with patch(
            "engines.store_setup.email_content._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.email_content."
            "record_writeback",
        ):
            out = apply_emails(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_emails(store_name="Acme")
        with patch(
            "engines.store_setup.email_content._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.email_content."
            "record_writeback",
        ):
            out = apply_emails(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_emails(store_name="Acme")
        with patch(
            "engines.store_setup.email_content._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.email_content."
            "record_writeback",
        ) as record_mock:
            apply_emails(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
