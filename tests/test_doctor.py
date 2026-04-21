"""Tests for ``shopai doctor`` connectivity probes + MCP tool."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.readiness import doctor as dr
from mcp_server.tools import ToolCall, build_default_registry


class _EnvSandbox:
    KEYS = (
        "SHOPAI_SHOPIFY_URL",
        "SHOPAI_SHOPIFY_KEY",
        "SHOPAI_SHOPIFY_CLIENT_ID",
        "SHOPAI_SHOPIFY_CLIENT_SECRET",
        "META_ADS_ACCESS_TOKEN",
        "meta_ads_access_token",
        "FAL_KEY",
        "TRIPLE_WHALE_API_KEY",
        "OBSIDIAN_VAULT_PATH",
        "TIKTOK_SHOP_APP_KEY",
        "TIKTOK_SHOP_APP_SECRET",
        "TIKTOK_SHOP_ACCESS_TOKEN",
        "TIKTOK_SHOP_SHOP_ID",
    )

    def __enter__(self):
        self._orig = {
            k: os.environ.get(k) for k in self.KEYS
        }
        for k in self.KEYS:
            os.environ.pop(k, None)
        return self

    def __exit__(self, *a):
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _http(responses: dict[str, tuple[int, bytes]]):
    """Build a dict-driven fake HTTP client matching on url substr."""
    calls: list[dict] = []

    def _fake(method, url, headers, timeout):
        calls.append({
            "method": method, "url": url,
            "headers": headers, "timeout": timeout,
        })
        for substr, pair in responses.items():
            if substr in url:
                return pair
        raise AssertionError(
            f"unmocked url: {method} {url}",
        )

    return _fake, calls


# ── Per-probe shape tests ────────────────────────────────────


class TestShopifyProbe(unittest.TestCase):
    def test_no_url_skipped(self):
        with _EnvSandbox():
            r = dr._probe_shopify(
                _http({})[0], timeout=1,
            )
        self.assertFalse(r.ok)
        self.assertTrue(r.skipped)
        self.assertIn("SHOPAI_SHOPIFY_URL", r.fix)

    def test_no_token_resolved(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_SHOPIFY_URL"
            ] = "a.myshopify.com"
            # No SHOPAI_SHOPIFY_KEY — resolver returns ""
            r = dr._probe_shopify(
                _http({})[0], timeout=1,
            )
        self.assertFalse(r.ok)
        self.assertIn("credentials", r.detail.lower())

    def test_200_ok_extracts_store_name(self):
        with _EnvSandbox():
            os.environ.update({
                "SHOPAI_SHOPIFY_URL": "a.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "shpat_test",
            })
            http, calls = _http({
                "/shop.json": (
                    200,
                    json.dumps({
                        "shop": {"name": "Acme Pets"},
                    }).encode(),
                ),
            })
            r = dr._probe_shopify(http, timeout=1)
        self.assertTrue(r.ok)
        self.assertIn("Acme Pets", r.detail)
        self.assertEqual(
            calls[0]["headers"]["X-Shopify-Access-Token"],
            "shpat_test",
        )

    def test_401_surfaces_fix_hint(self):
        with _EnvSandbox():
            os.environ.update({
                "SHOPAI_SHOPIFY_URL": "a.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "bad",
            })
            http, _ = _http({
                "/shop.json": (401, b"{}"),
            })
            r = dr._probe_shopify(http, timeout=1)
        self.assertFalse(r.ok)
        self.assertIn("unauthorized", r.detail.lower())
        self.assertIn("Token", r.fix)


class TestMetaProbe(unittest.TestCase):
    def test_no_token_skipped(self):
        with _EnvSandbox():
            r = dr._probe_meta_ads(
                _http({})[0], timeout=1,
            )
        self.assertTrue(r.skipped)

    def test_200_with_user_id(self):
        with _EnvSandbox():
            os.environ[
                "META_ADS_ACCESS_TOKEN"
            ] = "meta_tok"
            http, _ = _http({
                "/me": (
                    200,
                    b'{"id":"12345","name":"Owner"}',
                ),
            })
            r = dr._probe_meta_ads(http, timeout=1)
        self.assertTrue(r.ok)
        self.assertIn("12345", r.detail)

    def test_401_rejects(self):
        with _EnvSandbox():
            os.environ[
                "META_ADS_ACCESS_TOKEN"
            ] = "bad"
            http, _ = _http({
                "/me": (401, b"{}"),
            })
            r = dr._probe_meta_ads(http, timeout=1)
        self.assertFalse(r.ok)
        self.assertIn("token", r.fix.lower())


class TestFalProbe(unittest.TestCase):
    def test_no_key_skipped(self):
        with _EnvSandbox():
            r = dr._probe_fal(_http({})[0], timeout=1)
        self.assertTrue(r.skipped)

    def test_404_means_reachable(self):
        with _EnvSandbox():
            os.environ["FAL_KEY"] = "fal_tok"
            http, calls = _http({
                "fal.run/": (404, b""),
            })
            r = dr._probe_fal(http, timeout=1)
        self.assertTrue(r.ok)
        self.assertEqual(
            calls[0]["headers"]["Authorization"],
            "Key fal_tok",
        )

    def test_401_rejects(self):
        with _EnvSandbox():
            os.environ["FAL_KEY"] = "bad"
            http, _ = _http({
                "fal.run/": (401, b""),
            })
            r = dr._probe_fal(http, timeout=1)
        self.assertFalse(r.ok)


class TestVaultProbe(unittest.TestCase):
    def test_no_path_skipped(self):
        with _EnvSandbox():
            r = dr._probe_vault()
        self.assertTrue(r.skipped)

    def test_existing_dir_ok(self):
        with _EnvSandbox(), tempfile.TemporaryDirectory() as td:
            os.environ["OBSIDIAN_VAULT_PATH"] = td
            r = dr._probe_vault()
        self.assertTrue(r.ok)

    def test_missing_dir_fails(self):
        with _EnvSandbox():
            os.environ[
                "OBSIDIAN_VAULT_PATH"
            ] = "/nonexistent/vault_xxx"
            r = dr._probe_vault()
        self.assertFalse(r.ok)
        self.assertIn("mkdir", r.fix)

    def test_not_a_dir_fails(self):
        with _EnvSandbox(), tempfile.NamedTemporaryFile() as tf:
            os.environ[
                "OBSIDIAN_VAULT_PATH"
            ] = tf.name
            r = dr._probe_vault()
        self.assertFalse(r.ok)


class TestTikTokShopProbe(unittest.TestCase):
    def test_no_config_skipped(self):
        with _EnvSandbox():
            r = dr._probe_tiktok_shop()
        self.assertTrue(r.skipped)
        self.assertIn("Z6", r.detail)

    def test_partial_config_fails(self):
        with _EnvSandbox():
            os.environ["TIKTOK_SHOP_APP_KEY"] = "k"
            os.environ["TIKTOK_SHOP_APP_SECRET"] = "s"
            # token + shop_id missing
            r = dr._probe_tiktok_shop()
        self.assertFalse(r.ok)
        self.assertFalse(r.skipped)
        self.assertIn("partial", r.detail)

    def test_full_config_ok(self):
        with _EnvSandbox():
            os.environ.update({
                "TIKTOK_SHOP_APP_KEY": "k",
                "TIKTOK_SHOP_APP_SECRET": "s",
                "TIKTOK_SHOP_ACCESS_TOKEN": "tok",
                "TIKTOK_SHOP_SHOP_ID": "1",
            })
            r = dr._probe_tiktok_shop()
        self.assertTrue(r.ok)


class TestMobyProbe(unittest.TestCase):
    def test_no_key_skipped(self):
        with _EnvSandbox():
            r = dr._probe_moby(
                _http({})[0], timeout=1,
            )
        self.assertTrue(r.skipped)

    def test_200_ok(self):
        with _EnvSandbox():
            os.environ[
                "TRIPLE_WHALE_API_KEY"
            ] = "tw_tok"
            http, _ = _http({
                "moby": (200, b"{}"),
            })
            r = dr._probe_moby(http, timeout=1)
        self.assertTrue(r.ok)


# ── Aggregate run() ──────────────────────────────────────────


class TestRun(unittest.TestCase):
    def test_all_skipped_is_not_critical(self):
        with _EnvSandbox():
            report = dr.run(_http({})[0], timeout=1)
        # Critical = shopify + meta_ads. Both skipped → they
        # weren't asked to produce revenue; treated as warnings.
        self.assertEqual(report.critical_failures, 0)
        self.assertGreater(report.warnings, 0)
        self.assertTrue(report.ok)

    def test_shopify_failure_is_critical(self):
        with _EnvSandbox():
            os.environ.update({
                "SHOPAI_SHOPIFY_URL": "s.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "bad",
            })
            http, _ = _http({
                "/shop.json": (401, b"{}"),
            })
            report = dr.run(http, timeout=1)
        self.assertFalse(report.ok)
        self.assertEqual(report.critical_failures, 1)

    def test_all_green_critical(self):
        with _EnvSandbox(), tempfile.TemporaryDirectory() as td:
            os.environ.update({
                "SHOPAI_SHOPIFY_URL": "s.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "shpat",
                "META_ADS_ACCESS_TOKEN": "meta",
                "FAL_KEY": "fal",
                "OBSIDIAN_VAULT_PATH": td,
                "TRIPLE_WHALE_API_KEY": "tw",
                "TIKTOK_SHOP_APP_KEY": "k",
                "TIKTOK_SHOP_APP_SECRET": "s",
                "TIKTOK_SHOP_ACCESS_TOKEN": "tok",
                "TIKTOK_SHOP_SHOP_ID": "1",
            })
            http, _ = _http({
                "/shop.json": (
                    200,
                    json.dumps({
                        "shop": {"name": "S"},
                    }).encode(),
                ),
                "/me": (
                    200,
                    b'{"id":"1"}',
                ),
                "fal.run/": (404, b""),
                "moby": (200, b"{}"),
            })
            report = dr.run(http, timeout=1)
        self.assertTrue(report.ok)
        self.assertEqual(report.critical_failures, 0)
        self.assertEqual(report.warnings, 0)

    def test_probe_exception_becomes_failure(self):
        with _EnvSandbox():
            os.environ.update({
                "SHOPAI_SHOPIFY_URL": "s.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "shpat",
            })

            def _raise(method, url, headers, timeout):
                raise RuntimeError("boom")

            report = dr.run(_raise, timeout=1)
        shopify = next(
            p for p in report.probes
            if p.name == "shopify"
        )
        self.assertFalse(shopify.ok)


class TestMcpDoctorTool(unittest.TestCase):
    def test_registered(self):
        reg = build_default_registry()
        names = {s.name for s in reg.list_tools()}
        self.assertIn("doctor", names)

    def test_returns_structured_report(self):
        with _EnvSandbox():
            # All skipped → ok=True, warnings>0
            reg = build_default_registry()
            with patch(
                "core.readiness.doctor._urlopen",
            ) as up:
                up.side_effect = RuntimeError(
                    "should not be called when all skipped",
                )
                res = reg.call(ToolCall(tool="doctor"))
        self.assertTrue(res.ok)
        self.assertIn("probes", res.content)
        self.assertIn("ok", res.content)
        self.assertIn("critical_failures", res.content)


if __name__ == "__main__":
    unittest.main()
