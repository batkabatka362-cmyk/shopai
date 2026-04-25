"""Security audit tests for ShopifyWebhookHandler HMAC flow:
  * Secret resolution from env (SHOPAI_SHOPIFY_WEBHOOK_SECRET +
    SHOPIFY_WEBHOOK_SECRET fallback)
  * Fail-closed gate SHOPAI_WEBHOOK_VERIFY_REQUIRED=1
  * Explicit kwarg beats env
Pre-audit: handler was constructed with no args in api/server.py,
so self._secret stayed empty and HMAC verification was silently
skipped for every production webhook.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import os
import unittest

from core.webhooks import ShopifyWebhookHandler


class _EnvSandbox:
    KEYS = (
        "SHOPAI_SHOPIFY_WEBHOOK_SECRET",
        "SHOPIFY_WEBHOOK_SECRET",
        "SHOPAI_WEBHOOK_VERIFY_REQUIRED",
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


def _sign(secret: str, body: bytes) -> str:
    return base64.b64encode(
        _hmac.new(
            secret.encode(), body, hashlib.sha256,
        ).digest(),
    ).decode()


class TestSecretResolution(unittest.TestCase):
    def test_explicit_kwarg_beats_env(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_SHOPIFY_WEBHOOK_SECRET"
            ] = "env-secret"
            h = ShopifyWebhookHandler(
                webhook_secret="kwarg-secret",
            )
        self.assertEqual(h._secret, "kwarg-secret")

    def test_shopai_env_picked_up(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_SHOPIFY_WEBHOOK_SECRET"
            ] = "shopai-env"
            h = ShopifyWebhookHandler()
        self.assertEqual(h._secret, "shopai-env")

    def test_standard_shopify_env_fallback(self):
        with _EnvSandbox():
            os.environ[
                "SHOPIFY_WEBHOOK_SECRET"
            ] = "standard-env"
            h = ShopifyWebhookHandler()
        self.assertEqual(h._secret, "standard-env")

    def test_shopai_env_beats_standard(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_SHOPIFY_WEBHOOK_SECRET"
            ] = "a"
            os.environ["SHOPIFY_WEBHOOK_SECRET"] = "b"
            h = ShopifyWebhookHandler()
        self.assertEqual(h._secret, "a")

    def test_no_env_empty_secret(self):
        with _EnvSandbox():
            h = ShopifyWebhookHandler()
        self.assertEqual(h._secret, "")


class TestVerifyRequiredGate(unittest.TestCase):
    def _raw(self) -> bytes:
        return json.dumps({
            "id": 42, "total_price": "29.99",
        }).encode()

    def test_no_secret_no_flag_accepts(self):
        """Pre-audit behaviour: empty secret = accept all."""
        with _EnvSandbox():
            h = ShopifyWebhookHandler()
        result = h.handle(
            topic="orders/paid",
            payload={"id": 42},
            hmac_header="whatever",
            shop="s.myshopify.com",
            raw_body=self._raw(),
        )
        self.assertNotEqual(result["status"], "rejected")

    def test_no_secret_with_flag_rejects(self):
        """Production safety: flag forces rejection when the
        operator forgot to set the secret."""
        with _EnvSandbox():
            os.environ[
                "SHOPAI_WEBHOOK_VERIFY_REQUIRED"
            ] = "1"
            h = ShopifyWebhookHandler()
        result = h.handle(
            topic="orders/paid",
            payload={"id": 42},
            hmac_header="whatever",
            shop="s.myshopify.com",
            raw_body=self._raw(),
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(
            result["reason"],
            "webhook_secret_not_configured",
        )

    def test_valid_secret_with_flag_accepts_signed(self):
        raw = self._raw()
        with _EnvSandbox():
            os.environ[
                "SHOPAI_SHOPIFY_WEBHOOK_SECRET"
            ] = "sekret"
            os.environ[
                "SHOPAI_WEBHOOK_VERIFY_REQUIRED"
            ] = "1"
            h = ShopifyWebhookHandler()
        sig = _sign("sekret", raw)
        result = h.handle(
            topic="orders/paid",
            payload=json.loads(raw.decode()),
            hmac_header=sig,
            shop="s.myshopify.com",
            raw_body=raw,
        )
        self.assertNotEqual(result["status"], "rejected")

    def test_valid_secret_bad_signature_rejects(self):
        raw = self._raw()
        with _EnvSandbox():
            os.environ[
                "SHOPAI_SHOPIFY_WEBHOOK_SECRET"
            ] = "sekret"
            h = ShopifyWebhookHandler()
        result = h.handle(
            topic="orders/paid",
            payload={"id": 42},
            hmac_header="not-a-real-sig",
            shop="s.myshopify.com",
            raw_body=raw,
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "invalid_hmac")

    def test_valid_secret_missing_raw_body_rejects(self):
        """Audit pass 42 invariant — without raw bytes we
        can't verify, so fail closed."""
        with _EnvSandbox():
            os.environ[
                "SHOPAI_SHOPIFY_WEBHOOK_SECRET"
            ] = "sekret"
            h = ShopifyWebhookHandler()
        result = h.handle(
            topic="orders/paid",
            payload={"id": 42},
            hmac_header="whatever",
            shop="s.myshopify.com",
            raw_body=None,
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(
            result["reason"],
            "raw_body_required_for_hmac",
        )

    def test_valid_secret_missing_hmac_header_rejects(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_SHOPIFY_WEBHOOK_SECRET"
            ] = "sekret"
            h = ShopifyWebhookHandler()
        result = h.handle(
            topic="orders/paid",
            payload={"id": 42},
            hmac_header="",
            shop="s.myshopify.com",
            raw_body=self._raw(),
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(
            result["reason"], "missing_hmac_header",
        )


if __name__ == "__main__":
    unittest.main()
