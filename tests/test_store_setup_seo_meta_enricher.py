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


# --- LLM-driven enrichment ------------------------------------


import json as _json


def _ok_llm(data):
    return SimpleNamespace(ok=True, data=data, error=None)


class TestLLMPath:
    """LLM path is only invoked when PYTEST_CURRENT_TEST is
    falsey OR the router is explicitly patched. The default
    test environment short-circuits to the template path
    (Pattern J)."""

    def test_pytest_env_blocks_live_llm(self, monkeypatch):
        """Default pytest run uses template path -- LLM never
        called even when products lack SEO fields."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        out = enrich_seo(
            [_product()], niche="beauty", store_name="Acme",
        )
        gen = out["generated"][0]
        # Template-built title has the brand suffix pattern
        assert "Acme" in gen["seo_title"] or "Vitamin" in gen["seo_title"]
        # Niche tagline ("Clean beauty, ...") is template signal
        assert "beauty" in gen["seo_description"].lower() \
            or "honest" in gen["seo_description"].lower()

    def test_llm_pair_used_when_returned(self):
        llm = _json.dumps({
            "seo_title": "Pro-grade Vitamin C Serum -- 4 weeks",
            "seo_description": (
                "Clinical-strength brightening serum -- visible "
                "results in 4 weeks. FDA-tested ingredients, "
                "vegan, cruelty-free."
            ),
        })
        router = SimpleNamespace(
            execute=lambda c, p: _ok_llm({"text": llm, "model": "x"}),
        )
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch(
                "core.adapters.get_router",
                return_value=router,
             ):
            out = enrich_seo(
                [_product()], niche="beauty", store_name="Acme",
            )
        gen = out["generated"][0]
        assert gen["seo_title"] == (
            "Pro-grade Vitamin C Serum -- 4 weeks"
        )
        assert gen["seo_description"].startswith(
            "Clinical-strength brightening serum"
        )

    def test_overlong_title_truncated_post_llm(self):
        """If the model overshoots, we still cap at _TITLE_MAX
        (58 chars)."""
        llm = _json.dumps({
            "seo_title": "A" * 80,
            "seo_description": "B" * 120,
        })
        router = SimpleNamespace(
            execute=lambda c, p: _ok_llm({"text": llm, "model": "x"}),
        )
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch(
                "core.adapters.get_router",
                return_value=router,
             ):
            out = enrich_seo(
                [_product()], niche="beauty", store_name="Acme",
            )
        gen = out["generated"][0]
        assert len(gen["seo_title"]) <= 58

    def test_too_short_description_falls_back(self):
        """A description shorter than 40 chars is treated as
        a degenerate LLM result -- falls back to template."""
        llm = _json.dumps({
            "seo_title": "OK",
            "seo_description": "tiny",  # < 40 chars
        })
        router = SimpleNamespace(
            execute=lambda c, p: _ok_llm({"text": llm, "model": "x"}),
        )
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch(
                "core.adapters.get_router",
                return_value=router,
             ):
            out = enrich_seo(
                [_product()], niche="beauty", store_name="Acme",
            )
        gen = out["generated"][0]
        # Template path used -- description has the niche tagline
        assert "honest" in gen["seo_description"].lower() \
            or "beauty" in gen["seo_description"].lower()

    def test_router_raises_falls_back_to_template(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch(
                "core.adapters.get_router",
                return_value=router,
             ):
            out = enrich_seo(
                [_product()], niche="beauty", store_name="Acme",
            )
        # Template path output still produced
        assert out["generated"][0]["seo_title"]
        assert out["generated"][0]["seo_description"]

    def test_garbage_response_falls_back(self):
        router = SimpleNamespace(
            execute=lambda c, p: _ok_llm({"text": "no json", "model": "x"}),
        )
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch(
                "core.adapters.get_router",
                return_value=router,
             ):
            out = enrich_seo(
                [_product()], niche="beauty", store_name="Acme",
            )
        assert out["generated"][0]["seo_description"]
