"""Tests for ``engines.store_setup.homepage_hero``.

Generator builds a structured hero spec; applier persists it
as a Shopify page (handle ``homepage-hero``) via the existing
``SHOPIFY_CREATE_PAGE`` adapter, recording via Pattern Z.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: niche-specific headline + subhead.
  3. Generator: store_name interpolated into subhead.
  4. Generator: unknown niche falls back to general.
  5. Generator: primary CTA URL defaults to niche-typical
     collection; override accepted.
  6. Generator: image_url passed through when provided.
  7. Renderer: produces semantic HTML with hero classes.
  8. Renderer: empty spec -> empty string.
  9. Renderer: HTML-escapes user content to prevent XSS.
 10. Applier: no spec -> short-circuit.
 11. Applier: success path + records via Pattern Z.
 12. Applier: router_unavailable -> records failure.
 13. Applier: adapter rejection / raise.
 14. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.homepage_hero import (
    apply_hero,
    generate_hero,
    render_hero_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_hero(store_name="") == {}
        assert generate_hero(store_name="   ") == {}
        assert generate_hero(store_name=None) == {}


class TestGeneratorNicheTone:

    def test_beauty_headline(self):
        out = generate_hero(
            store_name="Acme Beauty", niche="beauty",
        )
        assert "bathroom shelf" in out["headline"].lower()
        # store_name interpolated
        assert "Acme Beauty" in out["subhead"]

    def test_fashion_headline(self):
        out = generate_hero(
            store_name="Acme Fashion", niche="fashion",
        )
        assert "way you actually dress" in out["headline"]

    def test_extended_niches_each_have_distinct_tone(self):
        snippets = {
            "pets": "animals",
            "fitness": "training",
            "jewelry": "Heirloom",
            "outdoor": "trail",
            "baby": "Soft, safe",
        }
        for niche, snippet in snippets.items():
            out = generate_hero(
                store_name="Acme", niche=niche,
            )
            assert snippet in out["headline"], niche

    def test_unknown_niche_falls_back_to_general(self):
        out = generate_hero(
            store_name="Acme", niche="ufo_parts",
        )
        assert "Quality you can trust" in out["headline"]


class TestGeneratorShape:

    def test_full_shape(self):
        out = generate_hero(
            store_name="Acme", niche="beauty",
        )
        for key in (
            "headline", "subhead",
            "primary_cta_label", "primary_cta_url",
            "secondary_cta_label", "secondary_cta_url",
            "image_alt",
        ):
            assert key in out, key

    def test_default_primary_cta_url_per_niche(self):
        # Beauty -> skincare collection
        out = generate_hero(
            store_name="Acme", niche="beauty",
        )
        assert out["primary_cta_url"] == "/collections/skincare"
        # Fitness -> apparel
        out = generate_hero(
            store_name="Acme", niche="fitness",
        )
        assert out["primary_cta_url"] == "/collections/apparel"
        # Unknown -> /collections/all
        out = generate_hero(
            store_name="Acme", niche="ufo_parts",
        )
        assert out["primary_cta_url"] == "/collections/all"

    def test_primary_cta_url_override(self):
        out = generate_hero(
            store_name="Acme",
            niche="beauty",
            primary_cta_url="/collections/featured",
        )
        assert (
            out["primary_cta_url"] == "/collections/featured"
        )

    def test_default_secondary_cta(self):
        out = generate_hero(store_name="Acme")
        assert out["secondary_cta_url"] == "/pages/about"

    def test_image_url_passed_through(self):
        out = generate_hero(
            store_name="Acme",
            image_url="https://cdn/hero.jpg",
        )
        assert out["image_url"] == "https://cdn/hero.jpg"
        assert out["image_alt"] == "Acme hero"

    def test_no_image_url_no_image_field(self):
        out = generate_hero(store_name="Acme")
        # image_url omitted when not supplied
        assert "image_url" not in out
        # image_alt still present so the applier can pass it
        # to a future asset-uploader
        assert out["image_alt"] == "Acme hero"


# ── Renderer ─────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec_returns_empty_string(self):
        assert render_hero_html({}) == ""
        assert render_hero_html(None) == ""  # type: ignore[arg-type]

    def test_basic_render(self):
        spec = generate_hero(
            store_name="Acme", niche="beauty",
        )
        html_out = render_hero_html(spec)
        assert "<section class=\"hero\">" in html_out
        assert "<h1" in html_out
        assert spec["headline"] in html_out
        # No image when not in spec
        assert "<img" not in html_out

    def test_render_with_image(self):
        spec = generate_hero(
            store_name="Acme",
            image_url="https://cdn/hero.jpg",
        )
        html_out = render_hero_html(spec)
        assert "<img" in html_out
        assert "https://cdn/hero.jpg" in html_out
        assert "alt=\"Acme hero\"" in html_out

    def test_renders_both_ctas(self):
        spec = generate_hero(store_name="Acme")
        html_out = render_hero_html(spec)
        assert "hero__cta--primary" in html_out
        assert "hero__cta--secondary" in html_out

    def test_escapes_user_content(self):
        """Headline / subhead must be HTML-escaped to prevent
        injection if a future generator pulls store_name from
        user input."""
        spec = {
            "headline": "<script>alert(1)</script>",
            "subhead": "x & y < z",
            "primary_cta_label": "",
            "primary_cta_url": "",
            "secondary_cta_label": "",
            "secondary_cta_url": "",
            "image_alt": "",
        }
        html_out = render_hero_html(spec)
        assert "<script>" not in html_out
        assert "&lt;script&gt;" in html_out
        assert "&amp;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_empty_spec_short_circuits(self):
        out = apply_hero({})
        assert out["applied"] is False
        assert out["error"] == "no_hero_spec"

    def test_non_dict(self):
        out = apply_hero(None)  # type: ignore[arg-type]
        assert out["applied"] is False


class TestApplierSuccess:

    def test_success_records_via_pattern_z(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_hero(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.homepage_hero._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.homepage_hero."
            "record_writeback",
        ) as record_mock:
            out = apply_hero(spec)
        assert out["applied"] is True
        assert out["handle"] == "homepage-hero"
        # The adapter got the rendered HTML body
        call_params = router.execute.call_args.args[1]
        assert call_params["title"] == "Homepage Hero"
        assert call_params["handle"] == "homepage-hero"
        assert "<section" in call_params["body_html"]
        assert call_params["published"] is True
        record_mock.assert_called_once()
        assert (
            record_mock.call_args.kwargs["success"] is True
        )


class TestApplierFailureModes:

    def test_router_unavailable_records_failure(self):
        spec = generate_hero(store_name="Acme")
        with patch(
            "engines.store_setup.homepage_hero._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.homepage_hero."
            "record_writeback",
        ) as record_mock:
            out = apply_hero(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        record_mock.assert_called_once()
        assert (
            record_mock.call_args.kwargs["success"] is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_hero(store_name="Acme")
        with patch(
            "engines.store_setup.homepage_hero._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.homepage_hero."
            "record_writeback",
        ):
            out = apply_hero(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_hero(store_name="Acme")
        with patch(
            "engines.store_setup.homepage_hero._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.homepage_hero."
            "record_writeback",
        ) as record_mock:
            out = apply_hero(spec)
        assert out["applied"] is False
        assert "network" in out["error"]
        # Failure still recorded
        record_mock.assert_called_once()


class TestStoreIdPropagation:

    def test_store_id_in_recorded_params(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_hero(store_name="Acme")
        with patch(
            "engines.store_setup.homepage_hero._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.homepage_hero."
            "record_writeback",
        ) as record_mock:
            apply_hero(spec, store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
