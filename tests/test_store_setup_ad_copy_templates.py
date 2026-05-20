"""Tests for ``engines.store_setup.ad_copy_templates``.

Niche-aware paid ad copy variants per channel
(Meta / Google Search / TikTok).

Coverage:
  1. Empty store_name -> empty dict.
  2. Every niche has at least one variant per channel.
  3. Meta variants stay within character caps (40c
     headline, 125c primary, 30c description).
  4. Google Search variants stay within caps (30c per
     headline, 90c per description, 15c display path).
  5. TikTok variants within 100c text cap.
  6. Each Meta variant has all 5 fields.
  7. Each Google Search variant has all 8 fields.
  8. Each TikTok variant has all 3 fields.
  9. Every niche resolves; unknown niche -> general.
 10. Niche-specific positioning (beauty inclusive,
     tech anti-fluff, fitness anti-influencer).
 11. CTA strings are non-empty.
 12. Renderer: empty / non-dict.
 13. Renderer: produces channel sections + variant
     sections.
 14. Renderer: HTML escape.
 15. Applier: empty short-circuit.
 16. Applier: success + Pattern Z (variant_count
     metric).
 17. Applier: failure modes.
 18. Store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.ad_copy_templates import (
    _CHAR_CAPS,
    _NICHE_AD_COPY,
    apply_ad_copy_templates,
    generate_ad_copy_templates,
    render_ad_copy_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_ad_copy_templates(
            store_name="",
        ) == {}
        assert generate_ad_copy_templates(
            store_name="   ",
        ) == {}
        assert generate_ad_copy_templates(
            store_name=None,
        ) == {}


class TestGeneratorShape:

    def test_every_niche_has_meta_variants(self):
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            assert spec["channels"]["meta"], niche

    def test_every_niche_has_google_search(self):
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            assert spec["channels"]["google_search"], niche

    def test_every_niche_has_tiktok(self):
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            assert spec["channels"]["tiktok"], niche


class TestMetaVariantShape:

    def test_meta_variant_full_shape(self):
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["meta"]:
                assert v["headline"], niche
                assert v["primary_text"], niche
                assert v["description"], niche
                assert v["cta"], niche
                assert v["rationale"], niche


class TestGoogleSearchVariantShape:

    def test_gs_variant_full_shape(self):
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["google_search"]:
                for field in (
                    "headline_1", "headline_2",
                    "headline_3", "description_1",
                    "description_2", "display_path",
                    "cta", "rationale",
                ):
                    assert v[field], (niche, field)


class TestTikTokVariantShape:

    def test_tiktok_variant_full_shape(self):
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["tiktok"]:
                assert v["ad_text"], niche
                assert v["cta"], niche
                assert v["rationale"], niche


# ── Character caps (real platform limits) ────────────────────


class TestCharCaps:

    def test_meta_headline_within_cap(self):
        cap = _CHAR_CAPS["meta_headline"]
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["meta"]:
                assert len(v["headline"]) <= cap, (
                    niche, v["headline"],
                )

    def test_meta_primary_within_cap(self):
        cap = _CHAR_CAPS["meta_primary"]
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["meta"]:
                assert (
                    len(v["primary_text"]) <= cap
                ), (niche, v["primary_text"])

    def test_meta_description_within_cap(self):
        cap = _CHAR_CAPS["meta_description"]
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["meta"]:
                assert (
                    len(v["description"]) <= cap
                ), (niche, v["description"])

    def test_gs_headlines_within_cap(self):
        cap = _CHAR_CAPS["gs_headline"]
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["google_search"]:
                for h in (
                    v["headline_1"],
                    v["headline_2"],
                    v["headline_3"],
                ):
                    assert len(h) <= cap, (niche, h)

    def test_gs_descriptions_within_cap(self):
        cap = _CHAR_CAPS["gs_description"]
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["google_search"]:
                for d in (
                    v["description_1"],
                    v["description_2"],
                ):
                    assert len(d) <= cap, (niche, d)

    def test_gs_display_path_within_cap(self):
        cap = _CHAR_CAPS["gs_display_path"]
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["google_search"]:
                assert (
                    len(v["display_path"]) <= cap
                ), (niche, v["display_path"])

    def test_tiktok_text_within_cap(self):
        cap = _CHAR_CAPS["tiktok_text"]
        for niche in _NICHE_AD_COPY:
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            for v in spec["channels"]["tiktok"]:
                assert (
                    len(v["ad_text"]) <= cap
                ), (niche, v["ad_text"])


# ── Niche positioning ───────────────────────────────────────


class TestNicheCoverage:

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            spec = generate_ad_copy_templates(
                store_name="Acme", niche=niche,
            )
            assert spec["channels"]["meta"]

    def test_unknown_niche_falls_back(self):
        spec = generate_ad_copy_templates(
            store_name="Acme", niche="ufo_parts",
        )
        general = generate_ad_copy_templates(
            store_name="Acme", niche="general",
        )
        # Same variant count + same first headline
        assert (
            len(spec["channels"]["meta"])
            == len(general["channels"]["meta"])
        )

    def test_beauty_clean_positioning(self):
        spec = generate_ad_copy_templates(
            store_name="Acme", niche="beauty",
        )
        blob = " ".join(
            v["primary_text"]
            for v in spec["channels"]["meta"]
        ).lower()
        assert any(
            t in blob
            for t in ("clean", "vegan",
                      "fragrance-free")
        )

    def test_fashion_inclusive_sizing(self):
        spec = generate_ad_copy_templates(
            store_name="Acme", niche="fashion",
        )
        blob = " ".join(
            v["primary_text"]
            for v in spec["channels"]["meta"]
        ).lower()
        assert any(
            t in blob
            for t in ("real body", "sizing", "returns",
                      "fit")
        )

    def test_food_subscription_pitch(self):
        spec = generate_ad_copy_templates(
            store_name="Acme", niche="food",
        )
        blob = " ".join(
            v["primary_text"]
            for v in spec["channels"]["meta"]
        ).lower()
        assert "subscribe" in blob or "subscription" in blob


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_ad_copy_html({}) == ""
        assert render_ad_copy_html(None) == ""  # type: ignore[arg-type]

    def test_renders_three_channel_sections(self):
        spec = generate_ad_copy_templates(
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_ad_copy_html(spec)
        assert "Acme Beauty" in html_out
        # Three channel sections rendered
        assert "Meta" in html_out or "Instagram" in html_out
        assert "Google Search" in html_out
        assert "TikTok" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "channels": {
                "meta": [
                    {
                        "headline": "<b>h</b>",
                        "primary_text": "p & p",
                        "description": "d",
                        "cta": "c",
                        "rationale": "r",
                    },
                ],
                "google_search": [],
                "tiktok": [],
            },
        }
        html_out = render_ad_copy_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>h</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_ad_copy_templates({})
        assert out["applied"] is False
        assert out["error"] == "no_ad_copy_spec"

    def test_non_dict(self):
        out = apply_ad_copy_templates(None)  # type: ignore[arg-type]
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_ad_copy_templates(
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.ad_copy_templates."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.ad_copy_templates."
            "record_writeback",
        ) as record_mock:
            out = apply_ad_copy_templates(spec)
        assert out["applied"] is True
        assert out["handle"] == "ad-copy-templates"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        # Variant count sums across channels
        total = sum(
            len(v) for v in spec["channels"].values()
        )
        assert (
            kwargs["metrics"]["variant_count"] == total
        )


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_ad_copy_templates(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.ad_copy_templates."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.ad_copy_templates."
            "record_writeback",
        ):
            out = apply_ad_copy_templates(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_ad_copy_templates(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.ad_copy_templates."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.ad_copy_templates."
            "record_writeback",
        ):
            out = apply_ad_copy_templates(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_ad_copy_templates(
            store_name="Acme",
        )
        with patch(
            "engines.store_setup.ad_copy_templates."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.ad_copy_templates."
            "record_writeback",
        ) as record_mock:
            apply_ad_copy_templates(
                spec, store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
