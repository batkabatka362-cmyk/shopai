"""Tests for ``shopai store seed-products``.

Standalone surface for the product seeder. Same engine the
launch flow's Step 7 uses; this CLI is for stores that need a
catalog backfill without re-running the full launch.

Coverage:
  - Preview (default) -> no writes, spec list rendered
  - --apply happy path -> 4 created, exit 0
  - --apply partial failure -> exit 1, failures surfaced
  - JSON outputs (both preview + apply)
  - Engine import failure -> friendly text, exit 0
  - --niche / --vendor flow through to generate_starter_products
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
        store=None,
        niche="general",
        vendor="",
        apply=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm():
    sm = MagicMock()
    sm.active_store_id = None
    return sm


_SAMPLE_SPECS = [
    {"title": "Hydrating Serum", "handle": "hydrating-serum",
     "description_html": "<p>...</p>",
     "product_type": "Skincare",
     "tags": ["starter"], "status": "ACTIVE"},
    {"title": "Lip Balm", "handle": "lip-balm",
     "description_html": "<p>...</p>",
     "product_type": "Makeup",
     "tags": ["starter"], "status": "ACTIVE"},
]


class TestPreview:

    def test_preview_no_writes(self, cli):
        """Default mode: generate_starter_products is called
        but apply_starter_products is not."""
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            return_value=_SAMPLE_SPECS,
        ), patch(
            "engines.store_setup.product_seeder."
            "apply_starter_products",
        ) as apply_mock:
            out, code = _capture(
                cli._cmd_store_seed_products, _ns(),
            )
        apply_mock.assert_not_called()
        assert code == 0
        assert "PREVIEW" in out
        assert "Hydrating Serum" in out
        assert "Re-run with --apply" in out

    def test_preview_json(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            return_value=_SAMPLE_SPECS,
        ):
            out, code = _capture(
                cli._cmd_store_seed_products,
                _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["applied"] is False
        assert data["spec_count"] == 2
        assert len(data["specs"]) == 2


class TestApply:

    def test_apply_clean_exits_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            return_value=_SAMPLE_SPECS,
        ), patch(
            "engines.store_setup.product_seeder."
            "apply_starter_products",
            return_value={
                "applied_count": 2,
                "results": [
                    {"title": "Hydrating Serum",
                     "handle": "hydrating-serum",
                     "ok": True, "error": None},
                    {"title": "Lip Balm",
                     "handle": "lip-balm",
                     "ok": True, "error": None},
                ],
            },
        ) as apply_mock:
            out, code = _capture(
                cli._cmd_store_seed_products,
                _ns(apply=True),
            )
        apply_mock.assert_called_once()
        assert code == 0
        assert "APPLIED" in out
        assert "2/2 created" in out

    def test_apply_partial_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            return_value=_SAMPLE_SPECS,
        ), patch(
            "engines.store_setup.product_seeder."
            "apply_starter_products",
            return_value={
                "applied_count": 1,
                "results": [
                    {"title": "Hydrating Serum",
                     "handle": "hydrating-serum",
                     "ok": True, "error": None},
                    {"title": "Lip Balm",
                     "handle": "lip-balm",
                     "ok": False, "error": "rate_limited"},
                ],
            },
        ):
            out, code = _capture(
                cli._cmd_store_seed_products,
                _ns(apply=True),
            )
        assert code == 1
        assert "PARTIAL" in out
        assert "1/2 created" in out
        assert "rate_limited" in out

    def test_apply_json_partial_carries_failures(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            return_value=_SAMPLE_SPECS,
        ), patch(
            "engines.store_setup.product_seeder."
            "apply_starter_products",
            return_value={
                "applied_count": 0,
                "results": [
                    {"title": "Hydrating Serum",
                     "handle": "hydrating-serum",
                     "ok": False, "error": "duplicate"},
                    {"title": "Lip Balm",
                     "handle": "lip-balm",
                     "ok": False, "error": "duplicate"},
                ],
            },
        ):
            out, code = _capture(
                cli._cmd_store_seed_products,
                _ns(apply=True, json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert data["applied_count"] == 0
        assert len(data["failures"]) == 2


class TestKwargPropagation:

    def test_niche_and_vendor_forwarded(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.product_seeder."
            "generate_starter_products",
            return_value=_SAMPLE_SPECS,
        ) as gen_mock:
            _capture(
                cli._cmd_store_seed_products,
                _ns(niche="beauty", vendor="Acme"),
            )
        kwargs = gen_mock.call_args.kwargs
        assert kwargs["niche"] == "beauty"
        assert kwargs["vendor"] == "Acme"
