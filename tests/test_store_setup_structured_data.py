"""Tests for ``engines.store_setup.structured_data``.

Generator produces 4 Schema.org JSON-LD blocks; applier
persists them as a Shopify page (handle
``structured-data``) via ``SHOPIFY_CREATE_PAGE``. Records
via Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: all 4 blocks always present.
  3. Generator: Organization shape (name, url, optional
     logo + contactPoint).
  4. Generator: WebSite has SearchAction with proper
     urlTemplate.
  5. Generator: FAQPage has 5+ Q&A entries in Schema.org
     shape.
  6. Generator: BreadcrumbList has at least Home item.
  7. Generator: site_url resolution (supplied vs fallback
     to myshopify.com slug).
  8. Generator: placeholder support_email rejected.
  9. Generator: real support_email surfaces in
     contactPoint.
 10. Renderer: empty / non-dict input.
 11. Renderer: produces <script type="application/ld+json">
     blocks for each generated section.
 12. Renderer: HTML-escapes user content.
 13. Renderer: round-trip JSON validity (each block's body
     parses as valid JSON).
 14. Applier: empty / no blocks short-circuit.
 15. Applier: success + Pattern Z records block_keys +
     block_count.
 16. Applier: router_unavailable.
 17. Applier: adapter rejection / raise.
 18. store_id propagation.
"""
from __future__ import annotations

import html as _html
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.structured_data import (
    _resolve_site_url,
    apply_structured_data,
    generate_structured_data,
    render_structured_data_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_structured_data(store_name="") == {}
        assert (
            generate_structured_data(store_name="   ") == {}
        )
        assert (
            generate_structured_data(store_name=None) == {}
        )


class TestGeneratorBlocks:

    def test_four_blocks_present(self):
        spec = generate_structured_data(
            store_name="Acme", niche="beauty",
        )
        for key in (
            "organization", "website", "faqpage",
            "breadcrumblist",
        ):
            assert key in spec["blocks"], key

    def test_organization_shape(self):
        spec = generate_structured_data(
            store_name="Acme",
            site_url="https://acme.com",
            logo_url="https://cdn/logo.png",
            support_email="hello@acmestore.com",
        )
        org = spec["blocks"]["organization"]
        assert org["@context"] == "https://schema.org"
        assert org["@type"] == "Organization"
        assert org["name"] == "Acme"
        assert org["url"] == "https://acme.com"
        assert org["logo"] == "https://cdn/logo.png"
        assert org["contactPoint"]["email"] == (
            "hello@acmestore.com"
        )

    def test_organization_no_logo_no_email(self):
        """Omitted logo + email -> those fields absent from
        the block, not present-but-empty."""
        spec = generate_structured_data(store_name="Acme")
        org = spec["blocks"]["organization"]
        assert "logo" not in org
        assert "contactPoint" not in org

    def test_placeholder_email_rejected(self):
        for bad in (
            "support@example.com",
            "test@test.com",
            "x@localhost",
        ):
            spec = generate_structured_data(
                store_name="Acme", support_email=bad,
            )
            assert (
                "contactPoint"
                not in spec["blocks"]["organization"]
            ), bad

    def test_website_search_action(self):
        spec = generate_structured_data(
            store_name="Acme",
            site_url="https://acme.com",
        )
        site = spec["blocks"]["website"]
        assert site["@type"] == "WebSite"
        action = site["potentialAction"]
        assert action["@type"] == "SearchAction"
        # urlTemplate contains the search query placeholder
        assert (
            "{search_term_string}"
            in action["target"]["urlTemplate"]
        )
        assert (
            action["target"]["urlTemplate"].startswith(
                "https://acme.com",
            )
        )

    def test_faqpage_has_5_questions(self):
        spec = generate_structured_data(store_name="Acme")
        faq = spec["blocks"]["faqpage"]
        assert faq["@type"] == "FAQPage"
        assert len(faq["mainEntity"]) >= 5
        for entry in faq["mainEntity"]:
            assert entry["@type"] == "Question"
            assert entry["name"]
            assert entry["acceptedAnswer"]["@type"] == "Answer"
            assert entry["acceptedAnswer"]["text"]

    def test_breadcrumblist_has_home(self):
        spec = generate_structured_data(
            store_name="Acme",
            site_url="https://acme.com",
        )
        bc = spec["blocks"]["breadcrumblist"]
        assert bc["@type"] == "BreadcrumbList"
        assert len(bc["itemListElement"]) >= 1
        first = bc["itemListElement"][0]
        assert first["name"] == "Home"
        assert first["position"] == 1
        assert first["item"] == "https://acme.com"


# ── site_url resolution ────────────────────────────────────


class TestSiteUrlResolution:

    def test_supplied_url_used(self):
        spec = generate_structured_data(
            store_name="Acme",
            site_url="https://acme.com",
        )
        assert spec["site_url"] == "https://acme.com"

    def test_supplied_url_trailing_slash_stripped(self):
        spec = generate_structured_data(
            store_name="Acme",
            site_url="https://acme.com/",
        )
        assert spec["site_url"] == "https://acme.com"

    def test_missing_url_falls_back_to_myshopify_slug(self):
        spec = generate_structured_data(
            store_name="Acme Beauty",
        )
        assert (
            spec["site_url"]
            == "https://acme-beauty.myshopify.com"
        )

    def test_punctuation_in_name_handled(self):
        spec = generate_structured_data(
            store_name="Acme & Co.",
        )
        # Punctuation -> hyphens; runs collapsed
        assert spec["site_url"] == (
            "https://acme-co.myshopify.com"
        )

    def test_invalid_url_scheme_falls_back(self):
        """A URL without http(s) scheme is treated as
        missing -- falls back to the myshopify slug."""
        spec = generate_structured_data(
            store_name="Acme", site_url="acme.com",
        )
        assert (
            spec["site_url"]
            == "https://acme.myshopify.com"
        )

    def test_resolve_helper_directly(self):
        # Stand-alone helper test for tricky inputs
        assert (
            _resolve_site_url("Acme", "https://x.com/")
            == "https://x.com"
        )
        assert (
            _resolve_site_url("Acme", None)
            == "https://acme.myshopify.com"
        )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_structured_data_html({}) == ""
        assert render_structured_data_html(None) == ""  # type: ignore[arg-type]
        assert (
            render_structured_data_html({
                "store_name": "Acme",
            }) == ""
        )

    def test_renders_script_blocks(self):
        spec = generate_structured_data(
            store_name="Acme", site_url="https://acme.com",
        )
        html_out = render_structured_data_html(spec)
        assert "structured-data" in html_out
        # 4 blocks => 4 <script type="application/ld+json">
        # (HTML-escaped) appearances.
        assert html_out.count("application/ld+json") == 4

    def test_round_trip_json_per_block(self):
        """Each block's <pre> body must round-trip through
        JSON unescape + parse. Confirms the JSON-LD is
        copy-pasteable without manual cleanup."""
        spec = generate_structured_data(
            store_name="Acme", site_url="https://acme.com",
        )
        html_out = render_structured_data_html(spec)
        # Extract every <pre>...</pre> body
        chunks = []
        cursor = 0
        while True:
            start = html_out.find("<pre", cursor)
            if start < 0:
                break
            body_start = html_out.find(">", start) + 1
            end = html_out.find("</pre>", body_start)
            chunks.append(html_out[body_start:end])
            cursor = end
        assert len(chunks) == 4
        for chunk in chunks:
            unescaped = _html.unescape(chunk)
            # Strip the wrapper script tags + whitespace
            json_str = unescaped.split(
                "<script type=\"application/ld+json\">",
            )[1].split("</script>")[0].strip()
            # Must parse
            parsed = json.loads(json_str)
            assert parsed["@context"] == (
                "https://schema.org"
            )

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "site_url": "https://acme.com",
            "blocks": {
                "organization": {
                    "@context": "https://schema.org",
                    "@type": "Organization",
                    "name": "<b>tag</b>",
                },
            },
        }
        html_out = render_structured_data_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>tag</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_structured_data({})
        assert out["applied"] is False
        assert out["error"] == "no_structured_data_spec"

    def test_non_dict(self):
        out = apply_structured_data(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_blocks(self):
        out = apply_structured_data({"store_name": "Acme"})
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_structured_data(
            store_name="Acme",
            site_url="https://acme.com",
        )
        with patch(
            "engines.store_setup.structured_data."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.structured_data."
            "record_writeback",
        ) as record_mock:
            out = apply_structured_data(spec)
        assert out["applied"] is True
        assert out["handle"] == "structured-data"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Structured Data"
        assert params["handle"] == "structured-data"
        assert "application/ld+json" in params["body_html"]
        # Pattern Z carries block keys + counts
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["block_count"] == 4


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_structured_data(store_name="Acme")
        with patch(
            "engines.store_setup.structured_data."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.structured_data."
            "record_writeback",
        ) as record_mock:
            out = apply_structured_data(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"] is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_structured_data(store_name="Acme")
        with patch(
            "engines.store_setup.structured_data."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.structured_data."
            "record_writeback",
        ):
            out = apply_structured_data(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_structured_data(store_name="Acme")
        with patch(
            "engines.store_setup.structured_data."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.structured_data."
            "record_writeback",
        ):
            out = apply_structured_data(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_structured_data(store_name="Acme")
        with patch(
            "engines.store_setup.structured_data."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.structured_data."
            "record_writeback",
        ) as record_mock:
            apply_structured_data(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
