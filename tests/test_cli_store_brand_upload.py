"""Tests for ``shopai store brand-upload``.

Stand-alone operator surface for ``brand_uploader`` (#369).
Mirrors the launch orchestrator's brand step but invokable
independently for logo refreshes / favicon A/B without
re-running the whole launch.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

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
        store_name="Acme",
        logo_url=None,
        favicon_url=None,
        hero_url=None,
        og_image_url=None,
        store_id=None,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestValidation:

    def test_no_urls_exits_1(self, cli):
        out, code = _capture(cli._cmd_store_brand_upload, _ns())
        assert code == 1
        assert "at least one" in out.lower()

    def test_no_urls_json(self, cli):
        out, code = _capture(
            cli._cmd_store_brand_upload, _ns(json=True),
        )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert data["error"] == "no_urls_provided"


class TestHappyPath:

    def test_logo_and_favicon_exits_0(self, cli):
        with patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value={
                "uploaded_count": 2,
                "files": [
                    {"asset": "logo"},
                    {"asset": "favicon"},
                ],
                "missing_assets": ["hero", "og_image"],
                "ok": True,
                "error": None,
            },
        ) as upload_mock:
            out, code = _capture(
                cli._cmd_store_brand_upload,
                _ns(
                    logo_url="https://x/logo.png",
                    favicon_url="https://x/fav.png",
                ),
            )
        assert code == 0
        assert "uploaded" in out.lower()
        assert "2 file" in out
        # Optional-assets-not-provided line surfaces
        assert "Optional" in out
        kwargs = upload_mock.call_args.kwargs
        assert kwargs["logo_url"] == "https://x/logo.png"
        assert kwargs["favicon_url"] == "https://x/fav.png"

    def test_json_round_trips(self, cli):
        with patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value={
                "uploaded_count": 4,
                "files": [
                    {"asset": "logo"},
                    {"asset": "favicon"},
                    {"asset": "hero"},
                    {"asset": "og_image"},
                ],
                "missing_assets": [],
                "ok": True,
                "error": None,
            },
        ):
            out, code = _capture(
                cli._cmd_store_brand_upload,
                _ns(
                    logo_url="https://x/l.png",
                    favicon_url="https://x/f.png",
                    hero_url="https://x/h.png",
                    og_image_url="https://x/og.png",
                    json=True,
                ),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["uploaded_count"] == 4
        assert data["missing_assets"] == []


class TestFailingUpload:

    def test_missing_minimum_exits_1(self, cli):
        with patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value={
                "uploaded_count": 1,
                "files": [{"asset": "logo"}],
                "missing_assets": ["favicon"],
                "ok": False,
                "error": "favicon_upload_rejected",
            },
        ):
            out, code = _capture(
                cli._cmd_store_brand_upload,
                _ns(logo_url="https://x/l.png"),
            )
        assert code == 1
        assert "FAILED" in out
        assert "favicon_upload_rejected" in out
        assert "favicon" in out

    def test_failure_json_exits_1(self, cli):
        with patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value={
                "uploaded_count": 0,
                "files": [],
                "missing_assets": ["logo", "favicon"],
                "ok": False,
                "error": "router_unavailable",
            },
        ):
            out, code = _capture(
                cli._cmd_store_brand_upload,
                _ns(
                    logo_url="https://x/l.png", json=True,
                ),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert data["error"] == "router_unavailable"
        assert data["missing_assets"] == ["logo", "favicon"]


class TestResilience:

    def test_uploader_raise_friendly(self, cli):
        with patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            side_effect=RuntimeError("uploader broken"),
        ):
            out, code = _capture(
                cli._cmd_store_brand_upload,
                _ns(logo_url="https://x/l.png"),
            )
        # Probe failure isn't a launch failure - exit 0
        assert code == 0
        assert "unavailable" in out.lower()


class TestKwargsPropagation:

    def test_all_urls_thread_through(self, cli):
        with patch(
            "engines.store_setup.brand_uploader."
            "upload_brand_assets",
            return_value={
                "uploaded_count": 4,
                "files": [],
                "missing_assets": [],
                "ok": True,
                "error": None,
            },
        ) as upload_mock:
            _capture(
                cli._cmd_store_brand_upload,
                _ns(
                    store_name="Acme Beauty",
                    logo_url="https://x/l.png",
                    favicon_url="https://x/f.png",
                    hero_url="https://x/h.png",
                    og_image_url="https://x/og.png",
                    store_id="store-a",
                ),
            )
        kwargs = upload_mock.call_args.kwargs
        assert kwargs["store_name"] == "Acme Beauty"
        assert kwargs["logo_url"] == "https://x/l.png"
        assert kwargs["favicon_url"] == "https://x/f.png"
        assert kwargs["hero_url"] == "https://x/h.png"
        assert kwargs["og_image_url"] == "https://x/og.png"
        assert kwargs["store_id"] == "store-a"
