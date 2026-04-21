"""Tests for the llms.txt CLI build command + API serve routes."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── CLI: shopai build-llms-txt ────────────────────────────────


class TestBuildLlmsTxtCli(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get("SHOPAI_SHOPIFY_URL")
        os.environ["SHOPAI_SHOPIFY_URL"] = (
            "example.myshopify.com"
        )

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("SHOPAI_SHOPIFY_URL", None)
        else:
            os.environ["SHOPAI_SHOPIFY_URL"] = self._orig

    def _products_json_file(self, products, td):
        path = Path(td) / "products.json"
        path.write_text(json.dumps(products))
        return str(path)

    def test_writes_all_artifacts(self):
        from cli import _cmd_build_llms_txt
        products = [
            {
                "handle": "pet-bowl",
                "title": "Pet Slow Feeder Bowl",
                "description": "Prevents bloat.",
                "price": 29.99,
            },
            {
                "handle": "cat-tree",
                "title": "Cat Climbing Tree",
                "description": "Multi-level perch.",
                "price": 89.99,
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            products_path = self._products_json_file(
                products, td,
            )
            out_dir = Path(td) / "llms"
            buf = io.StringIO()
            with redirect_stdout(buf):
                _cmd_build_llms_txt(
                    store_name="Pets Co",
                    store_url="example.myshopify.com",
                    products_json=products_path,
                    out_dir=str(out_dir),
                    as_json=True,
                )
            payload = json.loads(buf.getvalue())
            self.assertEqual(
                payload["products_written"], 2,
            )
            self.assertTrue(
                (out_dir / "llms.txt").exists(),
            )
            self.assertTrue(
                (out_dir / "llms-full.txt").exists(),
            )
            self.assertTrue(
                (out_dir / "products" / "pet-bowl.md"
                 ).exists(),
            )
            self.assertTrue(
                (out_dir / "products" / "cat-tree.md"
                 ).exists(),
            )

    def test_table_output_path(self):
        from cli import _cmd_build_llms_txt
        products = [{
            "handle": "a",
            "title": "A",
            "description": "d",
            "price": 1,
        }]
        with tempfile.TemporaryDirectory() as td:
            products_path = self._products_json_file(
                products, td,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                _cmd_build_llms_txt(
                    store_name="S",
                    store_url="s.myshopify.com",
                    products_json=products_path,
                    out_dir=str(Path(td) / "llms"),
                    as_json=False,
                )
            out = buf.getvalue()
            self.assertIn("llms.txt artifacts written", out)
            self.assertIn("products:", out)

    def test_stale_mirrors_cleared(self):
        from cli import _cmd_build_llms_txt
        with tempfile.TemporaryDirectory() as td:
            # Pre-seed a stale mirror
            out = Path(td) / "llms"
            (out / "products").mkdir(parents=True)
            (out / "products" / "old.md").write_text(
                "stale",
            )
            products_path = self._products_json_file(
                [{
                    "handle": "new",
                    "title": "New",
                    "description": "d",
                    "price": 1,
                }],
                td,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                _cmd_build_llms_txt(
                    store_name="S",
                    store_url="s.myshopify.com",
                    products_json=products_path,
                    out_dir=str(out),
                    as_json=True,
                )
            # Old mirror removed, new one present
            self.assertFalse(
                (out / "products" / "old.md").exists(),
            )
            self.assertTrue(
                (out / "products" / "new.md").exists(),
            )

    def test_empty_products_exits_non_zero(self):
        from cli import _cmd_build_llms_txt
        with tempfile.TemporaryDirectory() as td:
            products_path = self._products_json_file(
                [], td,
            )
            buf = io.StringIO()
            with redirect_stdout(buf), self.assertRaises(
                SystemExit,
            ) as ctx:
                _cmd_build_llms_txt(
                    store_name="S",
                    store_url="s.myshopify.com",
                    products_json=products_path,
                    out_dir=str(Path(td) / "llms"),
                    as_json=False,
                )
            self.assertEqual(ctx.exception.code, 2)


# ── API routes ───────────────────────────────────────────────


class _FakeHandler:
    """Stand-in for BaseHTTPRequestHandler methods."""

    def __init__(self):
        self._wfile = io.BytesIO()
        self._status = None
        self._headers: dict[str, str] = {}

    def send_response(self, status):
        self._status = status

    def send_header(self, key, value):
        self._headers[key] = value

    def end_headers(self):
        pass

    @property
    def wfile(self):
        return self._wfile

    @property
    def body(self) -> str:
        return self._wfile.getvalue().decode(
            "utf-8", errors="replace",
        )


def _bind_handler_methods(handler):
    """Patch in _text_response + _serve_llms_file + _llms_*
    from ShopAIHandler without instantiating it."""
    from api.server import ShopAIHandler

    handler._text_response = (
        ShopAIHandler._text_response.__get__(handler)
    )
    handler._llms_txt = (
        ShopAIHandler._llms_txt.__get__(handler)
    )
    handler._llms_full_txt = (
        ShopAIHandler._llms_full_txt.__get__(handler)
    )
    handler._llms_mirror = (
        ShopAIHandler._llms_mirror.__get__(handler)
    )
    handler._serve_llms_file = (
        ShopAIHandler._serve_llms_file.__get__(handler)
    )


class TestApiServe(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        root = Path("data/llms")
        (root / "products").mkdir(parents=True)
        (root / "llms.txt").write_text("SHORT")
        (root / "llms-full.txt").write_text("FULL")
        (root / "products" / "pet-bowl.md").write_text(
            "# Pet Bowl",
        )

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_llms_txt_200(self):
        h = _FakeHandler()
        _bind_handler_methods(h)
        h._llms_txt()
        self.assertEqual(h._status, 200)
        self.assertEqual(h.body, "SHORT")
        self.assertEqual(
            h._headers["Content-Type"],
            "text/plain; charset=utf-8",
        )

    def test_llms_full_txt_200(self):
        h = _FakeHandler()
        _bind_handler_methods(h)
        h._llms_full_txt()
        self.assertEqual(h._status, 200)
        self.assertEqual(h.body, "FULL")

    def test_llms_mirror_valid_slug(self):
        h = _FakeHandler()
        _bind_handler_methods(h)
        h._llms_mirror("pet-bowl")
        self.assertEqual(h._status, 200)
        self.assertEqual(h.body, "# Pet Bowl")
        self.assertEqual(
            h._headers["Content-Type"],
            "text/markdown; charset=utf-8",
        )

    def test_llms_mirror_invalid_slug_rejected(self):
        h = _FakeHandler()
        _bind_handler_methods(h)
        h._llms_mirror("../etc/passwd")
        self.assertEqual(h._status, 400)
        self.assertIn("invalid", h.body.lower())

    def test_missing_file_404(self):
        os.remove("data/llms/llms.txt")
        h = _FakeHandler()
        _bind_handler_methods(h)
        h._llms_txt()
        self.assertEqual(h._status, 404)
        self.assertIn(
            "build-llms-txt", h.body.lower(),
        )

    def test_missing_mirror_404(self):
        h = _FakeHandler()
        _bind_handler_methods(h)
        h._llms_mirror("does-not-exist")
        self.assertEqual(h._status, 404)


class TestApiRouting(unittest.TestCase):
    """Confirm the do_GET router dispatches to the llms handlers."""

    def test_root_route_table_includes_llms(self):
        from api.server import ShopAIHandler
        src = ShopAIHandler.do_GET.__code__.co_consts
        # Flatten nested constants to a string for a simple
        # grep-based check of route registration
        all_str = repr(src)
        self.assertIn("/llms.txt", all_str)
        self.assertIn("/llms-full.txt", all_str)


if __name__ == "__main__":
    unittest.main()
