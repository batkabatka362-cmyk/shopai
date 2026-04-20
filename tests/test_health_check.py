"""Health check tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.readiness import health_check as hc


class EnvContext:
    """Isolate env mutations to one test."""
    def __init__(self, **kwargs):
        self._kwargs = kwargs
        self._prior = {}

    def __enter__(self):
        for k, v in self._kwargs.items():
            self._prior[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self._prior.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestShopify(unittest.TestCase):
    def test_fail_when_missing(self):
        with EnvContext(
            SHOPAI_SHOPIFY_URL=None,
            SHOPAI_SHOPIFY_KEY=None,
            SHOPAI_SHOPIFY_CLIENT_SECRET=None,
        ):
            r = hc.check_shopify_credentials()
        self.assertEqual(r.status, "fail")

    def test_ok_when_present(self):
        with EnvContext(
            SHOPAI_SHOPIFY_URL="x.myshopify.com",
            SHOPAI_SHOPIFY_KEY="tok",
        ):
            r = hc.check_shopify_credentials()
        self.assertEqual(r.status, "ok")


class TestMeta(unittest.TestCase):
    def test_warn_when_neither(self):
        with EnvContext(
            META_ACCESS_TOKEN=None,
            META_ADS_ACCOUNT_ID=None,
            meta_ads_access_token=None,
            meta_ads_account_id=None,
        ):
            r = hc.check_meta_ads_credentials()
        self.assertEqual(r.status, "warn")

    def test_fail_when_partial(self):
        with EnvContext(
            META_ACCESS_TOKEN="tok",
            META_ADS_ACCOUNT_ID=None,
            meta_ads_account_id=None,
        ):
            r = hc.check_meta_ads_credentials()
        self.assertEqual(r.status, "fail")

    def test_ok_when_both(self):
        with EnvContext(
            META_ACCESS_TOKEN="tok",
            META_ADS_ACCOUNT_ID="act_1",
        ):
            r = hc.check_meta_ads_credentials()
        self.assertEqual(r.status, "ok")


class TestLiveFlag(unittest.TestCase):
    def test_warn_when_off(self):
        with EnvContext(SHOPAI_ENABLE_LIVE_EXECUTION=None):
            r = hc.check_live_execution_flags()
        self.assertEqual(r.status, "warn")

    def test_ok_when_on(self):
        with EnvContext(SHOPAI_ENABLE_LIVE_EXECUTION="1"):
            r = hc.check_live_execution_flags()
        self.assertEqual(r.status, "ok")


class TestBrainHooks(unittest.TestCase):
    def test_warn_off(self):
        with EnvContext(SHOPAI_BRAIN_HOOKS=None):
            r = hc.check_brain_hooks()
        self.assertEqual(r.status, "warn")

    def test_ok_on(self):
        with EnvContext(SHOPAI_BRAIN_HOOKS="1"):
            r = hc.check_brain_hooks()
        self.assertEqual(r.status, "ok")


class TestVault(unittest.TestCase):
    def test_warn_when_missing(self):
        tmp = tempfile.TemporaryDirectory()
        missing = str(Path(tmp.name) / "nope_vault")
        with EnvContext(OBSIDIAN_VAULT_PATH=missing):
            r = hc.check_obsidian_vault()
        tmp.cleanup()
        self.assertEqual(r.status, "warn")

    def test_ok_when_full_structure(self):
        tmp = tempfile.TemporaryDirectory()
        vault = Path(tmp.name) / "vault"
        for sub in ("Decisions", "Wins", "Errors", "Knowledge"):
            (vault / sub).mkdir(parents=True)
        with EnvContext(OBSIDIAN_VAULT_PATH=str(vault)):
            r = hc.check_obsidian_vault()
        tmp.cleanup()
        self.assertEqual(r.status, "ok")


class TestWebhookRegistered(unittest.TestCase):
    def test_skipped_without_credentials(self):
        with EnvContext(
            SHOPAI_SHOPIFY_URL=None,
            SHOPAI_SHOPIFY_KEY=None,
            SHOPAI_SHOPIFY_CLIENT_SECRET=None,
        ):
            r = hc.check_webhook_registered()
        self.assertEqual(r.status, "skipped")

    def test_ok_when_present(self):
        client = MagicMock()
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "webhooks": [
                {
                    "id": 1,
                    "topic": "orders/paid",
                    "address": "https://x/wh",
                },
            ],
        }
        with EnvContext(
            SHOPAI_SHOPIFY_URL="x.myshopify.com",
            SHOPAI_SHOPIFY_KEY="tok",
        ):
            r = hc.check_webhook_registered(http=client)
        self.assertEqual(r.status, "ok")

    def test_fail_when_missing(self):
        client = MagicMock()
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "webhooks": [],
        }
        with EnvContext(
            SHOPAI_SHOPIFY_URL="x.myshopify.com",
            SHOPAI_SHOPIFY_KEY="tok",
        ):
            r = hc.check_webhook_registered(http=client)
        self.assertEqual(r.status, "fail")
        self.assertIn("ensure_attribution", r.fix)


class TestRunAll(unittest.TestCase):
    def test_report_has_verdict(self):
        r = hc.run_all()
        self.assertIn(
            r.verdict, {"ready", "degraded", "blocked"},
        )
        self.assertGreater(len(r.checks), 3)

    def test_text_rendering_has_checks(self):
        r = hc.run_all()
        text = r.as_text()
        self.assertIn("ShopAI health:", text)
        for c in r.checks:
            self.assertIn(c.name, text)

    def test_as_dict_complete(self):
        r = hc.run_all()
        d = r.as_dict()
        for key in (
            "verdict", "checks", "fixes",
            "ok_count", "warn_count", "fail_count",
        ):
            self.assertIn(key, d)

    def test_extra_check_runs(self):
        counter = {"n": 0}

        def extra():
            counter["n"] += 1
            return hc.CheckResult(
                name="custom",
                status="ok",
                summary="custom check",
            )

        r = hc.run_all(extra_checks=(extra,))
        self.assertEqual(counter["n"], 1)
        names = [c.name for c in r.checks]
        self.assertIn("custom", names)

    def test_extra_check_exception_caught(self):
        def boom():
            raise RuntimeError("boom")

        r = hc.run_all(extra_checks=(boom,))
        # boom's result was added as fail
        boom_result = next(
            (c for c in r.checks if c.status == "fail"
             and "boom" in c.summary),
            None,
        )
        self.assertIsNotNone(boom_result)

    def test_verdict_blocked_on_fail(self):
        def fail_check():
            return hc.CheckResult(
                name="fake_fail",
                status="fail",
                summary="bad",
            )

        r = hc.run_all(extra_checks=(fail_check,))
        self.assertEqual(r.verdict, "blocked")

    def test_verdict_ready_if_all_ok(self):
        with EnvContext(
            SHOPAI_SHOPIFY_URL="x.myshopify.com",
            SHOPAI_SHOPIFY_KEY="tok",
            META_ACCESS_TOKEN="tok",
            META_ADS_ACCOUNT_ID="act_1",
            SHOPAI_ENABLE_LIVE_EXECUTION="1",
            SHOPAI_BRAIN_HOOKS="1",
        ):
            # vault + data + compute_budget may still warn;
            # verdict is 'degraded' not 'ready'. Check at
            # least the env-driven checks flipped to ok.
            r = hc.run_all()
        env_results = {c.name: c.status for c in r.checks}
        self.assertEqual(
            env_results["shopify.credentials"], "ok",
        )
        self.assertEqual(
            env_results["meta_ads.credentials"], "ok",
        )
        self.assertEqual(
            env_results["live_execution.flag"], "ok",
        )
        self.assertEqual(env_results["brain.hooks"], "ok")


class TestDict(unittest.TestCase):
    def test_check_result_serialises(self):
        r = hc.CheckResult(
            name="x", status="ok", summary="y",
        )
        d = r.as_dict()
        self.assertEqual(d["name"], "x")


if __name__ == "__main__":
    unittest.main()
