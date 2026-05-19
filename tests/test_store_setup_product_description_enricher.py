"""Tests for ``engines.store_setup.product_description_enricher``.

Generates niche-aware product descriptions for products that
have empty / short body_html, then pushes them via
``SHOPIFY_UPDATE_PRODUCT``. Records each push via Pattern Z.

Coverage:
  1. Empty / non-list input short-circuits.
  2. Products with existing long body are skipped.
  3. Products missing id or title are skipped with reason.
  4. Generated body contains title + niche tone + tags.
  5. Niche fallback for unknown niche.
  6. Applier success path + recording.
  7. Applier router_unavailable -> each update recorded as fail.
  8. Applier partial failure / adapter raise.
  9. store_id propagation to Pattern Z params.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.store_setup.product_description_enricher import (
    apply_descriptions,
    enrich_products,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(err: str):
    return SimpleNamespace(ok=False, data=None, error=err)


def _product(
    *,
    pid: str = "gid://shopify/Product/1",
    title: str = "Vitamin C Serum",
    body: str = "",
    product_type: str = "Skincare",
    vendor: str = "Acme Labs",
    tags=("clean", "vegan", "cruelty-free"),
):
    return {
        "id": pid,
        "title": title,
        "body_html": body,
        "product_type": product_type,
        "vendor": vendor,
        "tags": list(tags),
    }


# --- enrich_products -----------------------------------------


class TestEnrichEmptyInput:

    def test_empty_list(self):
        out = enrich_products([])
        assert out == {"generated": [], "skipped": []}

    def test_none(self):
        out = enrich_products(None)  # type: ignore[arg-type]
        assert out == {"generated": [], "skipped": []}


class TestEnrichGeneration:

    def test_missing_body_gets_generated(self):
        out = enrich_products(
            [_product(body="")],
            niche="beauty",
        )
        assert len(out["generated"]) == 1
        assert len(out["skipped"]) == 0
        g = out["generated"][0]
        assert g["product_id"] == "gid://shopify/Product/1"
        # Body has the title
        assert "Vitamin C Serum" in g["body_html"]
        # Niche tone
        assert "Clean" in g["body_html"]  # beauty's promise tone

    def test_short_body_gets_replaced(self):
        out = enrich_products(
            [_product(body="<p>x</p>")],
            niche="beauty",
            min_existing_length=80,
        )
        assert len(out["generated"]) == 1
        assert len(out["skipped"]) == 0

    def test_long_body_is_preserved(self):
        long_body = "<p>" + ("Real copy. " * 30) + "</p>"
        out = enrich_products(
            [_product(body=long_body)],
            niche="beauty",
        )
        assert len(out["generated"]) == 0
        assert len(out["skipped"]) == 1
        assert (
            "existing_description_ok"
            in out["skipped"][0]["reason"]
        )

    def test_missing_id_skipped(self):
        out = enrich_products(
            [_product(pid="", title="X", body="")],
        )
        assert len(out["generated"]) == 0
        assert out["skipped"][0]["reason"] == "missing_product_id"

    def test_missing_title_skipped(self):
        out = enrich_products(
            [_product(title="", body="")],
        )
        assert len(out["generated"]) == 0
        assert out["skipped"][0]["reason"] == "missing_title"

    def test_tags_rendered_in_highlights(self):
        out = enrich_products(
            [_product(tags=["organic", "vegan"], body="")],
        )
        body = out["generated"][0]["body_html"]
        assert "Highlights" in body
        assert "organic" in body
        assert "vegan" in body

    def test_tags_as_string_parsed(self):
        out = enrich_products(
            [{
                "id": "gid://1",
                "title": "X",
                "body_html": "",
                "tags": "tag1, tag2, tag3",
            }],
        )
        body = out["generated"][0]["body_html"]
        assert "tag1" in body
        assert "tag2" in body

    def test_unknown_niche_falls_back(self):
        out = enrich_products(
            [_product(body="")],
            niche="ufo_parts",
        )
        body = out["generated"][0]["body_html"]
        # general fallback tone
        assert "Hand-picked" in body

    def test_skips_non_dict_entries(self):
        out = enrich_products(
            ["not a dict", 42, _product(body="")],
        )
        # 2 garbage entries skipped silently; 1 generated
        assert len(out["generated"]) == 1


# --- apply_descriptions --------------------------------------


class TestApplyEmpty:

    def test_empty_list(self):
        out = apply_descriptions([])
        assert out == {"applied_count": 0, "results": []}

    def test_non_list(self):
        out = apply_descriptions(None)  # type: ignore[arg-type]
        assert out == {"applied_count": 0, "results": []}


class TestApplySuccess:

    def test_all_applied_recorded(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        with patch(
            "engines.store_setup."
            "product_description_enricher._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup."
            "product_description_enricher.record_writeback",
        ) as record_mock:
            out = apply_descriptions([
                {"product_id": "gid://1",
                 "body_html": "<p>x</p>"},
                {"product_id": "gid://2",
                 "body_html": "<p>y</p>"},
            ])
        assert out["applied_count"] == 2
        assert all(r["ok"] for r in out["results"])
        assert record_mock.call_count == 2
        for call in record_mock.call_args_list:
            assert call.kwargs["success"] is True

    def test_missing_body_recorded_as_failure(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        with patch(
            "engines.store_setup."
            "product_description_enricher._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup."
            "product_description_enricher.record_writeback",
        ):
            out = apply_descriptions([
                {"product_id": "gid://1", "body_html": ""},
            ])
        assert out["applied_count"] == 0
        assert (
            out["results"][0]["error"]
            == "missing_product_id_or_body"
        )


class TestApplyFailureModes:

    def test_router_unavailable(self):
        with patch(
            "engines.store_setup."
            "product_description_enricher._get_router",
            return_value=None,
        ), patch(
            "engines.store_setup."
            "product_description_enricher.record_writeback",
        ) as record_mock:
            out = apply_descriptions([
                {"product_id": "gid://1",
                 "body_html": "<p>x</p>"},
                {"product_id": "gid://2",
                 "body_html": "<p>y</p>"},
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
            "engines.store_setup."
            "product_description_enricher._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup."
            "product_description_enricher.record_writeback",
        ):
            out = apply_descriptions([
                {"product_id": "gid://1",
                 "body_html": "<p>x</p>"},
                {"product_id": "gid://2",
                 "body_html": "<p>y</p>"},
                {"product_id": "gid://3",
                 "body_html": "<p>z</p>"},
            ])
        assert out["applied_count"] == 2
        by_id = {
            r["product_id"]: r for r in out["results"]
        }
        assert by_id["gid://1"]["ok"] is True
        assert by_id["gid://2"]["ok"] is False
        assert "not_found" in by_id["gid://2"]["error"]
        assert by_id["gid://3"]["ok"] is True

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        with patch(
            "engines.store_setup."
            "product_description_enricher._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup."
            "product_description_enricher.record_writeback",
        ):
            out = apply_descriptions([
                {"product_id": "gid://1",
                 "body_html": "<p>x</p>"},
            ])
        assert out["applied_count"] == 0
        assert (
            "adapter_raise"
            in out["results"][0]["error"]
        )


class TestStoreIdPropagation:

    def test_store_id_in_recorded_params(self):
        router = MagicMock()
        router.execute.return_value = _ok()
        with patch(
            "engines.store_setup."
            "product_description_enricher._get_router",
            return_value=router,
        ), patch(
            "engines.store_setup."
            "product_description_enricher.record_writeback",
        ) as record_mock:
            apply_descriptions(
                [{"product_id": "gid://1",
                  "body_html": "<p>x</p>"}],
                store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"
        assert params["product_id"] == "gid://1"
