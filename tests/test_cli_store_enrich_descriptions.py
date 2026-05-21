"""Tests for ``shopai store enrich-descriptions``.

Operator CLI for the product description enricher. Mirrors
``store enrich-seo`` (preview by default, ``--apply`` opts in).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(
        store_id=None,
        niche="general",
        min_length=80,
        limit=100,
        apply=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm():
    sm = MagicMock()
    sm.active_store_id = None
    return sm


def _ok_router(products):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True,
        data={"products": products},
        error=None,
    )
    return router


_SAMPLE = [
    {"id": "gid://shopify/Product/1", "title": "Lantern",
     "product_type": "Lighting",
     "vendor": "Acme", "body_html": ""},
    {"id": "gid://shopify/Product/2", "title": "Tent",
     "product_type": "Shelter",
     "vendor": "Acme", "body_html": ""},
]


class TestPreview:

    def test_preview_no_writes(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
        ) as apply_mock:
            out, code = _capture(
                cli._cmd_store_enrich_descriptions, _ns(),
            )
        apply_mock.assert_not_called()
        assert code == 0
        assert "PREVIEW" in out
        assert "would get descriptions" in out

    def test_preview_json(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ):
            out, code = _capture(
                cli._cmd_store_enrich_descriptions,
                _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["applied"] is False
        assert data["generated_count"] == 2
        assert len(data["generated"]) == 2
        first = data["generated"][0]
        assert "body_html" in first
        assert isinstance(first["body_html"], str)
        assert len(first["body_html"]) > 0


class TestApply:

    def test_apply_success_exits_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
            return_value={
                "applied_count": 2,
                "results": [
                    {"product_id": (
                        "gid://shopify/Product/1"
                    ), "ok": True, "error": None},
                    {"product_id": (
                        "gid://shopify/Product/2"
                    ), "ok": True, "error": None},
                ],
            },
        ) as apply_mock:
            out, code = _capture(
                cli._cmd_store_enrich_descriptions,
                _ns(apply=True),
            )
        apply_mock.assert_called_once()
        assert code == 0
        assert "APPLIED" in out
        assert "2 product" in out

    def test_apply_partial_failure_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
            return_value={
                "applied_count": 1,
                "results": [
                    {"product_id": (
                        "gid://shopify/Product/1"
                    ), "ok": True, "error": None},
                    {"product_id": (
                        "gid://shopify/Product/2"
                    ), "ok": False,
                     "error": "validation_failed"},
                ],
            },
        ):
            out, code = _capture(
                cli._cmd_store_enrich_descriptions,
                _ns(apply=True),
            )
        assert code == 1
        assert "PARTIAL" in out
        assert "validation_failed" in out


class TestResilience:

    def test_fetch_unavailable_friendly(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            side_effect=RuntimeError("network"),
        ):
            out, code = _capture(
                cli._cmd_store_enrich_descriptions, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()

    def test_apply_raise_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.product_description_enricher."
            "apply_descriptions",
            side_effect=RuntimeError("apply broke"),
        ):
            out, code = _capture(
                cli._cmd_store_enrich_descriptions,
                _ns(apply=True),
            )
        assert code == 1
        assert "unavailable" in out.lower()


class TestKwargsPropagation:

    def test_min_length_threads_through(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE),
        ), patch(
            "engines.store_setup.product_description_enricher."
            "enrich_products",
            return_value={"generated": [], "skipped": []},
        ) as enrich_mock:
            _capture(
                cli._cmd_store_enrich_descriptions,
                _ns(niche="beauty", min_length=150),
            )
        enrich_mock.assert_called_once()
        kwargs = enrich_mock.call_args.kwargs
        assert kwargs["niche"] == "beauty"
        assert kwargs["min_existing_length"] == 150

    def test_existing_long_description_preserved(self, cli):
        """A product with a long existing body_html is recorded
        as skipped (not regenerated) -- preserves operator-
        authored copy."""
        sample = [
            {"id": "gid://shopify/Product/1", "title": "T1",
             "body_html": "X" * 200},
            {"id": "gid://shopify/Product/2", "title": "T2",
             "body_html": ""},
        ]
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(sample),
        ):
            out, code = _capture(
                cli._cmd_store_enrich_descriptions,
                _ns(json=True),
            )
        data = json.loads(out)
        # Product 1 had long copy -> skipped, Product 2 -> generated
        skipped_ids = {s["product_id"] for s in data["skipped"]}
        generated_ids = {
            g["product_id"] for g in data["generated"]
        }
        assert "gid://shopify/Product/1" in skipped_ids
        assert "gid://shopify/Product/2" in generated_ids
