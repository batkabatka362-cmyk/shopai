"""Tests for ``engines.store_setup.product_alt_text``.

Niche-aware product image alt-text suggestion generator.
Output is operator-facing reference content (no media-alt
write adapter exists yet).

Coverage:
  1. Empty store_name -> empty dict.
  2. Empty product list -> empty suggestions + skipped.
  3. Per-product alt text generated; contains brand +
     title.
  4. Niche descriptor included.
  5. Missing product_id / title -> skipped.
  6. Alt text capped at 125 chars (screen-reader cap).
  7. Every niche resolves.
  8. Rationale references detail hints.
  9. Non-dict entries skipped silently.
 10. Renderer: empty / non-dict.
 11. Renderer: produces rows per suggestion + skipped
     block.
 12. Renderer: HTML escape.
 13. Applier: empty short-circuit.
 14. Applier: success + Pattern Z.
 15. Applier: router_unavailable / rejection / raise.
 16. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.product_alt_text import (
    _MAX_ALT_CHARS,
    _NICHE_DESCRIPTORS,
    apply_alt_text_suggestions,
    generate_product_alt_text,
    render_alt_text_html,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


def _product(
    *,
    pid: str = "gid://shopify/Product/1",
    title: str = "Vitamin C Serum",
    product_type: str = "Skincare",
    vendor: str = "Acme Labs",
):
    return {
        "id": pid,
        "title": title,
        "product_type": product_type,
        "vendor": vendor,
    }


# ── Generator ─────────────────────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_product_alt_text(
            [_product()], store_name="",
        ) == {}
        assert generate_product_alt_text(
            [_product()], store_name="   ",
        ) == {}
        assert generate_product_alt_text(
            [_product()], store_name=None,
        ) == {}

    def test_empty_product_list(self):
        out = generate_product_alt_text(
            [], store_name="Acme",
        )
        assert out["suggestions"] == []
        assert out["skipped"] == []

    def test_none_product_list(self):
        out = generate_product_alt_text(
            None, store_name="Acme",  # type: ignore[arg-type]
        )
        assert out["suggestions"] == []


class TestGeneratorContent:

    def test_brand_and_title_in_alt(self):
        out = generate_product_alt_text(
            [_product()], store_name="Acme",
        )
        alt = out["suggestions"][0]["alt_text"]
        assert "Acme" in alt
        assert "Vitamin C Serum" in alt

    def test_niche_descriptor_included(self):
        out = generate_product_alt_text(
            [_product()],
            store_name="Acme", niche="beauty",
        )
        alt = out["suggestions"][0]["alt_text"]
        descriptor = _NICHE_DESCRIPTORS["beauty"]
        # Either the full descriptor OR the product_type
        # is in the alt (composer drops descriptor if
        # length forces it).
        assert (
            descriptor in alt
            or "Skincare" in alt
        )

    def test_vendor_included_when_distinct(self):
        out = generate_product_alt_text(
            [_product(vendor="Other Lab")],
            store_name="Acme",
        )
        alt = out["suggestions"][0]["alt_text"]
        assert "Other Lab" in alt

    def test_vendor_skipped_when_same_as_brand(self):
        out = generate_product_alt_text(
            [_product(vendor="Acme")],
            store_name="Acme",
        )
        alt = out["suggestions"][0]["alt_text"]
        # Vendor "Acme" matches store name "Acme" --
        # shouldn't repeat
        assert alt.count("Acme") == 1


class TestGeneratorSkipped:

    def test_missing_id_skipped(self):
        out = generate_product_alt_text(
            [_product(pid="")], store_name="Acme",
        )
        assert len(out["suggestions"]) == 0
        assert out["skipped"][0]["reason"] == (
            "missing_product_id"
        )

    def test_missing_title_skipped(self):
        out = generate_product_alt_text(
            [_product(title="")], store_name="Acme",
        )
        assert out["skipped"][0]["reason"] == (
            "missing_title"
        )

    def test_non_dict_silently_skipped(self):
        out = generate_product_alt_text(
            [
                "not a dict",
                42,
                _product(),
            ],
            store_name="Acme",
        )
        # 1 generated; 2 garbage entries silently dropped
        assert len(out["suggestions"]) == 1


class TestAltTextLength:

    def test_alt_under_125_chars(self):
        """Screen-reader best-practice cap."""
        # Build a long title to stress the cap
        long_product = _product(
            title=(
                "Vitamin C + Hyaluronic Acid + Niacinamide "
                "Brightening Serum for Dehydrated Skin "
                "30ml Glass Dropper Bottle"
            ),
        )
        out = generate_product_alt_text(
            [long_product], store_name="Acme",
        )
        alt = out["suggestions"][0]["alt_text"]
        assert len(alt) <= _MAX_ALT_CHARS, (
            len(alt), alt,
        )

    def test_short_alt_unchanged(self):
        out = generate_product_alt_text(
            [_product(title="Cream")],
            store_name="A", niche="beauty",
        )
        alt = out["suggestions"][0]["alt_text"]
        # Short brand + short title; descriptor + type
        # fit
        assert len(alt) < _MAX_ALT_CHARS


class TestNicheCoverage:

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general", "ufo_parts",
        ):
            out = generate_product_alt_text(
                [_product()],
                store_name="Acme", niche=niche,
            )
            assert out["suggestions"]
            assert out["suggestions"][0]["alt_text"]


class TestRationale:

    def test_rationale_present(self):
        out = generate_product_alt_text(
            [_product()],
            store_name="Acme", niche="beauty",
        )
        rationale = out["suggestions"][0]["rationale"]
        assert rationale
        assert "consider" in rationale.lower()

    def test_rationale_carries_niche_hints(self):
        out = generate_product_alt_text(
            [_product()],
            store_name="Acme", niche="jewelry",
        )
        rationale = (
            out["suggestions"][0]["rationale"].lower()
        )
        # Jewelry-specific hints: metal / stone / carat
        assert any(
            hint in rationale
            for hint in ("metal", "stone", "carat")
        )


# ── Renderer ──────────────────────────────────────────────────


class TestRenderer:

    def test_empty_spec(self):
        assert render_alt_text_html({}) == ""
        assert render_alt_text_html(None) == ""  # type: ignore[arg-type]

    def test_produces_suggestion_rows(self):
        spec = generate_product_alt_text(
            [_product(), _product(
                pid="gid://shopify/Product/2",
                title="Hyaluronic Acid Serum",
            )],
            store_name="Acme Beauty", niche="beauty",
        )
        html_out = render_alt_text_html(spec)
        assert "Acme Beauty" in html_out
        # 2 suggestion rows in the body
        assert html_out.count("<tr>") >= 3  # 1 header + 2 data
        assert "Vitamin C Serum" in html_out
        assert "Hyaluronic Acid Serum" in html_out

    def test_renders_skipped_block_when_present(self):
        spec = generate_product_alt_text(
            [
                _product(),
                _product(
                    pid="gid://shopify/Product/2",
                    title="",
                ),
            ],
            store_name="Acme",
        )
        html_out = render_alt_text_html(spec)
        assert "Skipped Products" in html_out
        assert "missing_title" in html_out

    def test_escapes_user_content(self):
        spec = {
            "store_name": "<script>x</script>",
            "niche": "beauty",
            "suggestions": [
                {
                    "product_id": "gid://1",
                    "title": "<b>X</b>",
                    "alt_text": "<i>alt</i>",
                    "rationale": "x & y",
                },
            ],
            "skipped": [],
        }
        html_out = render_alt_text_html(spec)
        assert "<script>x</script>" not in html_out
        assert "<b>X</b>" not in html_out
        assert "&lt;" in html_out


# ── Applier ──────────────────────────────────────────────────


class TestApplierEmpty:

    def test_no_spec(self):
        out = apply_alt_text_suggestions({})
        assert out["applied"] is False
        assert out["error"] == "no_alt_text_spec"

    def test_non_dict(self):
        out = apply_alt_text_suggestions(None)  # type: ignore[arg-type]
        assert out["applied"] is False

    def test_spec_without_suggestions(self):
        out = apply_alt_text_suggestions(
            {"store_name": "Acme"},
        )
        assert out["applied"] is False


class TestApplierSuccess:

    def test_pushes_via_create_page(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_product_alt_text(
            [_product()],
            store_name="Acme", niche="beauty",
        )
        with patch(
            "engines.store_setup.product_alt_text."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_alt_text."
            "record_writeback",
        ) as record_mock:
            out = apply_alt_text_suggestions(spec)
        assert out["applied"] is True
        assert out["handle"] == "product-alt-text"
        params = router.execute.call_args.args[1]
        assert params["title"] == "Product Alt Text"
        assert params["handle"] == "product-alt-text"
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["metrics"]["suggestion_count"] == 1
        assert kwargs["metrics"]["niche"] == "beauty"


class TestApplierFailureModes:

    def test_router_unavailable(self):
        spec = generate_product_alt_text(
            [_product()], store_name="Acme",
        )
        with patch(
            "engines.store_setup.product_alt_text."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.product_alt_text."
            "record_writeback",
        ) as record_mock:
            out = apply_alt_text_suggestions(spec)
        assert out["applied"] is False
        assert out["error"] == "router_unavailable"
        assert (
            record_mock.call_args.kwargs["success"]
            is False
        )

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = _fail("handle taken")
        spec = generate_product_alt_text(
            [_product()], store_name="Acme",
        )
        with patch(
            "engines.store_setup.product_alt_text."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_alt_text."
            "record_writeback",
        ):
            out = apply_alt_text_suggestions(spec)
        assert out["applied"] is False
        assert "handle taken" in out["error"]

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        spec = generate_product_alt_text(
            [_product()], store_name="Acme",
        )
        with patch(
            "engines.store_setup.product_alt_text."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_alt_text."
            "record_writeback",
        ):
            out = apply_alt_text_suggestions(spec)
        assert out["applied"] is False
        assert "network" in out["error"]


class TestStoreIdPropagation:

    def test_store_id_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        spec = generate_product_alt_text(
            [_product()], store_name="Acme",
        )
        with patch(
            "engines.store_setup.product_alt_text."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.product_alt_text."
            "record_writeback",
        ) as record_mock:
            apply_alt_text_suggestions(
                spec, store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
