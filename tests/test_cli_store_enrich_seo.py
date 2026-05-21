"""Tests for ``shopai store enrich-seo``.

Operator CLI for the SEO meta enricher. Default behavior is
read-only preview; ``--apply`` opts in to writes via
SHOPIFY_UPDATE_PRODUCT.

Coverage:
  - Preview without --apply -> no writes, exit 0
  - --apply happy path -> exit 0 + applied count
  - --apply with partial failures -> exit 1 + failure breakdown
  - Product fetch unavailable -> friendly message, exit 0
  - enrich_seo raises -> friendly message, exit 0
  - apply_seo raises -> exit 1
  - --json output (preview + apply)
  - Args propagate to enrich_seo (niche, overwrite, store_name)
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
        store_name="",
        overwrite=False,
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


def _failing_router(error="ACCESS_DENIED"):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=False, data=None, error=error,
    )
    return router


_SAMPLE_PRODUCTS = [
    {"id": "gid://shopify/Product/1", "title": "Lantern",
     "product_type": "Lighting", "vendor": "Acme"},
    {"id": "gid://shopify/Product/2", "title": "Tent",
     "product_type": "Shelter", "vendor": "Acme"},
]


class TestPreview:

    def test_preview_no_writes(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE_PRODUCTS),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
        ) as apply_mock:
            out, code = _capture(
                cli._cmd_store_enrich_seo, _ns(),
            )
        # Default (no --apply) -> apply_seo NEVER called
        apply_mock.assert_not_called()
        assert code == 0
        assert "PREVIEW" in out
        assert "would get SEO updates" in out
        assert "Re-run with --apply" in out

    def test_preview_json(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE_PRODUCTS),
        ):
            out, code = _capture(
                cli._cmd_store_enrich_seo, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["applied"] is False
        assert data["generated_count"] == 2
        assert len(data["generated"]) == 2
        # Each generated entry has the SEO fields
        first = data["generated"][0]
        assert "seo_title" in first
        assert "seo_description" in first


class TestApply:

    def test_apply_success_exits_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE_PRODUCTS),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
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
                cli._cmd_store_enrich_seo, _ns(apply=True),
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
            return_value=_ok_router(_SAMPLE_PRODUCTS),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
            return_value={
                "applied_count": 1,
                "results": [
                    {"product_id": (
                        "gid://shopify/Product/1"
                    ), "ok": True, "error": None},
                    {"product_id": (
                        "gid://shopify/Product/2"
                    ), "ok": False,
                     "error": "rate_limited"},
                ],
            },
        ):
            out, code = _capture(
                cli._cmd_store_enrich_seo, _ns(apply=True),
            )
        assert code == 1
        assert "PARTIAL" in out
        assert "rate_limited" in out

    def test_apply_json_round_trips_results(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE_PRODUCTS),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
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
        ):
            out, code = _capture(
                cli._cmd_store_enrich_seo,
                _ns(apply=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["applied"] is True
        assert data["applied_count"] == 2
        assert data["failure_count"] == 0


class TestResilience:

    def test_fetch_unavailable_friendly(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            side_effect=RuntimeError("network"),
        ):
            out, code = _capture(
                cli._cmd_store_enrich_seo, _ns(),
            )
        # Probe failure isn't a write failure -- exit 0
        assert code == 0
        assert "unavailable" in out.lower()

    def test_fetch_returns_not_ok(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_failing_router("ACCESS_DENIED"),
        ):
            out, code = _capture(
                cli._cmd_store_enrich_seo, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is None
        assert data["error"] == "products_fetch_failed"

    def test_apply_raise_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE_PRODUCTS),
        ), patch(
            "engines.store_setup.seo_meta_enricher.apply_seo",
            side_effect=RuntimeError("apply broke"),
        ):
            out, code = _capture(
                cli._cmd_store_enrich_seo, _ns(apply=True),
            )
        assert code == 1
        assert "unavailable" in out.lower()


class TestKwargsPropagation:

    def test_niche_and_overwrite_thread_through(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=_ok_router(_SAMPLE_PRODUCTS),
        ), patch(
            "engines.store_setup.seo_meta_enricher.enrich_seo",
            return_value={"generated": [], "skipped": []},
        ) as enrich_mock:
            _capture(
                cli._cmd_store_enrich_seo,
                _ns(
                    niche="beauty",
                    overwrite=True,
                    store_name="Acme Beauty",
                ),
            )
        enrich_mock.assert_called_once()
        kwargs = enrich_mock.call_args.kwargs
        assert kwargs["niche"] == "beauty"
        assert kwargs["overwrite_existing"] is True
        assert kwargs["store_name"] == "Acme Beauty"

    def test_limit_propagates_to_router(self, cli):
        router = _ok_router(_SAMPLE_PRODUCTS)
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "core.adapters.get_router",
            return_value=router,
        ):
            _capture(
                cli._cmd_store_enrich_seo, _ns(limit=50),
            )
        # First positional arg is Capability, second is params
        call_args = router.execute.call_args
        params = call_args.args[1]
        assert params["limit"] == 50
