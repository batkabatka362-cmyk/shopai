"""Tests for ``engines.store_setup.seo_meta_enricher``.

Generator + applier for product SEO title + meta description.
Pushes through ``SHOPIFY_UPDATE_PRODUCT`` (which already
accepts ``seo_title`` / ``seo_description`` kwargs) and
records via Pattern Z.

Coverage:
  1. Generator: empty input / per-product generation.
  2. Title length cap (58 chars target).
  3. Brand suffix appended when room.
  4. Meta length cap (158 chars max).
  5. Existing SEO preserved unless overwrite=True.
  6. Partial existing fields: missing one gets generated.
  7. Niche tone in meta description.
  8. Missing product_id / title skipped with reason.
  9. Applier: empty / success path / router_unavailable /
     partial failure / adapter raise / store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.seo_meta_enricher import (
    _build_meta,
    _build_title,
    _truncate_at_word,
    apply_seo,
    enrich_seo,
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
    seo_title: str = "",
    seo_description: str = "",
):
    return {
        "id": pid,
        "title": title,
        "product_type": product_type,
        "vendor": vendor,
        "seo_title": seo_title,
        "seo_description": seo_description,
    }


# --- Title builder --------------------------------------------


class TestBuildTitle:

    def test_short_title_unchanged(self):
        assert _build_title("Serum", "") == "Serum"

    def test_brand_suffix_appended_when_room(self):
        assert (
            _build_title("Serum", "Acme") == "Serum | Acme"
        )

    def test_brand_suffix_skipped_when_no_room(self):
        # Long product title leaves no room for suffix
        title = "Hyaluronic Acid + Vitamin C Brightening Serum"
        assert len(title) > 30
        out = _build_title(title, "Acme Beauty Co")
        # Suffix was NOT appended (combined would exceed cap)
        assert out == title or "|" not in out

    def test_overlong_title_truncated_at_word(self):
        title = (
            "Super Long Title That Goes On And On And Will Not "
            "Fit In Sixty Characters Limit"
        )
        out = _build_title(title, "")
        assert len(out) <= 58
        # No truncation mid-word
        assert not out.endswith(" ")
        assert " " in out  # multi-word


# --- Meta builder ---------------------------------------------


class TestBuildMeta:

    def test_includes_title_type_vendor(self):
        out = _build_meta(
            title="Serum",
            product_type="Skincare",
            vendor="Acme",
            tagline="Clean beauty.",
        )
        assert "Serum" in out
        assert "skincare" in out
        assert "Acme" in out
        assert "Clean beauty" in out

    def test_length_capped(self):
        long_tagline = (
            "We make small-batch, locally-sourced, "
            "thoughtfully-crafted, lovingly-packaged ... " * 4
        )
        out = _build_meta(
            title="X", product_type="Y",
            vendor="Z", tagline=long_tagline,
        )
        assert len(out) <= 158

    def test_falls_back_when_no_type(self):
        out = _build_meta(
            title="X", product_type="",
            vendor="", tagline="Tagline.",
        )
        assert "product" in out


# --- truncate helper ------------------------------------------


class TestTruncate:

    def test_short_unchanged(self):
        assert _truncate_at_word("abc", 10) == "abc"

    def test_at_word_boundary(self):
        assert (
            _truncate_at_word(
                "hello world foo bar", 13,
            ) == "hello world"
        )

    def test_trailing_punctuation_stripped(self):
        assert (
            _truncate_at_word("hello, world.", 7) == "hello"
        )


# --- enrich_seo ----------------------------------------------


class TestEnrichEmpty:

    def test_empty_list(self):
        out = enrich_seo([])
        assert out == {"generated": [], "skipped": []}


class TestEnrichGeneration:

    def test_generates_for_empty_seo(self):
        out = enrich_seo(
            [_product()], niche="beauty",
            store_name="Acme",
        )
        assert len(out["generated"]) == 1
        g = out["generated"][0]
        assert g["seo_title"]
        assert g["seo_description"]
        assert "Vitamin C Serum" in g["seo_title"]
        # niche tone present
        assert "Clean beauty" in g["seo_description"]

    def test_preserves_existing_seo_default(self):
        out = enrich_seo(
            [_product(
                seo_title="Existing Title",
                seo_description="Existing meta description.",
            )],
        )
        assert len(out["generated"]) == 0
        assert (
            out["skipped"][0]["reason"]
            == "existing_seo_ok"
        )

    def test_overwrite_replaces_existing(self):
        out = enrich_seo(
            [_product(
                seo_title="Existing Title",
                seo_description="Existing meta description.",
            )],
            niche="beauty",
            store_name="Acme",
            overwrite_existing=True,
        )
        assert len(out["generated"]) == 1
        g = out["generated"][0]
        assert g["seo_title"] != "Existing Title"

    def test_partial_existing_only_fills_missing(self):
        out = enrich_seo(
            [_product(
                seo_title="Operator's Title",
                seo_description="",
            )],
            niche="beauty",
        )
        # ONE got generated; the operator's title is preserved.
        assert len(out["generated"]) == 1
        g = out["generated"][0]
        assert g["seo_title"] == "Operator's Title"
        # Meta filled in
        assert g["seo_description"]

    def test_missing_id_skipped(self):
        out = enrich_seo([_product(pid="")])
        assert (
            out["skipped"][0]["reason"]
            == "missing_product_id"
        )

    def test_missing_title_skipped(self):
        out = enrich_seo([_product(title="")])
        assert (
            out["skipped"][0]["reason"] == "missing_title"
        )

    def test_unknown_niche_falls_back(self):
        out = enrich_seo(
            [_product()], niche="ufo_parts",
        )
        g = out["generated"][0]
        # general tagline
        assert "Quality you can trust" in g["seo_description"]


# --- apply_seo -----------------------------------------------


class TestApplyEmpty:

    def test_empty_list(self):
        out = apply_seo([])
        assert out == {"applied_count": 0, "results": []}


class TestApplySuccess:

    def test_routes_seo_kwargs_to_adapter(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        with patch(
            "engines.store_setup.seo_meta_enricher."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.seo_meta_enricher."
            "record_writeback",
        ) as record_mock:
            out = apply_seo([{
                "product_id": "gid://1",
                "seo_title": "Title",
                "seo_description": "Meta description.",
            }])
        assert out["applied_count"] == 1
        # Adapter call carries seo_title + seo_description
        call_params = router.execute.call_args.args[1]
        assert call_params["seo_title"] == "Title"
        assert (
            call_params["seo_description"]
            == "Meta description."
        )
        assert record_mock.call_args.kwargs["success"] is True

    def test_missing_id_records_failure(self):
        with patch(
            "engines.store_setup.seo_meta_enricher."
            "record_writeback",
        ):
            router = MagicMock()
            router.execute.return_value = _ok()
            with patch(
                "engines.store_setup.seo_meta_enricher."
                "_get_router",
                return_value=router,
            ):
                out = apply_seo([{
                    "product_id": "",
                    "seo_title": "x",
                    "seo_description": "y",
                }])
        assert out["applied_count"] == 0
        assert (
            "missing_product_id_or_seo"
            in out["results"][0]["error"]
        )


class TestApplyFailureModes:

    def test_router_unavailable(self):
        with patch(
            "engines.store_setup.seo_meta_enricher."
            "_get_router",
            return_value=None,
        ), patch(
            "engines.store_setup.seo_meta_enricher."
            "record_writeback",
        ) as record_mock:
            out = apply_seo([
                {"product_id": "gid://1",
                 "seo_title": "x",
                 "seo_description": "y"},
                {"product_id": "gid://2",
                 "seo_title": "x",
                 "seo_description": "y"},
            ])
        assert out["applied_count"] == 0
        assert all(
            r["error"] == "router_unavailable"
            for r in out["results"]
        )
        assert record_mock.call_count == 2

    def test_partial_failure(self):
        def _by_id(cap, params):
            if params["id"] == "gid://2":
                return _fail("not_found")
            return _ok()
        router = MagicMock()
        router.execute.side_effect = _by_id
        with patch(
            "engines.store_setup.seo_meta_enricher."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.seo_meta_enricher."
            "record_writeback",
        ):
            out = apply_seo([
                {"product_id": "gid://1",
                 "seo_title": "x", "seo_description": "y"},
                {"product_id": "gid://2",
                 "seo_title": "x", "seo_description": "y"},
            ])
        assert out["applied_count"] == 1
        by_id = {r["product_id"]: r for r in out["results"]}
        assert by_id["gid://1"]["ok"] is True
        assert by_id["gid://2"]["ok"] is False

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        with patch(
            "engines.store_setup.seo_meta_enricher."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.seo_meta_enricher."
            "record_writeback",
        ):
            out = apply_seo([
                {"product_id": "gid://1",
                 "seo_title": "x",
                 "seo_description": "y"},
            ])
        assert out["applied_count"] == 0
        assert (
            "adapter_raise" in out["results"][0]["error"]
        )


class TestStoreIdPropagation:

    def test_store_id_in_recorded_params(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        with patch(
            "engines.store_setup.seo_meta_enricher."
            "_get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.seo_meta_enricher."
            "record_writeback",
        ) as record_mock:
            apply_seo(
                [{"product_id": "gid://1",
                  "seo_title": "x",
                  "seo_description": "y"}],
                store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
