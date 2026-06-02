"""W962-39 regression guards for core.system.webhook_handler.

Three security bugs the prior implementation shipped:

  1. HMAC verification was SKIPPED when the request had no
     `hmac_header`, even when a secret was configured.
     An attacker omitting the header bypassed the check.
  2. HMAC was computed over ``json.dumps(payload)``, the
     re-serialized parsed body. Shopify signs the RAW
     request body; the re-serialized bytes differ
     (key order, whitespace) so every real Shopify
     webhook was rejected.
  3. The local hex-digest verifier didn't match Shopify's
     base64-encoded HMAC format.

The fix introduces a ``raw_body`` kwarg that the HTTP
server passes through, delegates to the production
verify_hmac base64 implementation, and fails-closed when
the secret is set but the header is missing.
"""
from __future__ import annotations

import json


def _make_handler(secret: str = ""):
    from core.system.webhook_handler import WebhookHandler
    return WebhookHandler(secret=secret)


def _good_hmac(secret: str, raw: bytes) -> str:
    from core.feedback.webhook_security import compute_hmac
    return compute_hmac(raw, secret)


class TestSecretRequiresHeader:

    def test_secret_set_header_missing_rejected(self):
        """W962-39 (1): secret configured, no header -> reject.
        Pre-fix this silently passed."""
        wh = _make_handler(secret="shh")
        result = wh.process(
            "orders/create",
            {"id": 1},
            hmac_header="",
            raw_body=b'{"id": 1}',
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "missing_hmac_header"

    def test_no_secret_no_header_passes(self):
        """Dev / test path: handler with no secret skips
        verification (kept for back-compat)."""
        wh = _make_handler(secret="")
        result = wh.process(
            "orders/create",
            {"id": 1},
            hmac_header="",
            raw_body=b'{"id": 1}',
        )
        assert result["status"] != "rejected"


class TestRawBodyVerification:

    def test_valid_hmac_over_raw_body_accepted(self):
        """W962-39 (2): HMAC is computed over the raw bytes
        the receiver got, NOT the re-serialized payload."""
        secret = "test-secret"
        # Pre-fix: process re-serialized the parsed dict with
        # json.dumps, which produces different bytes than the
        # original. We pass a body with non-default spacing
        # that round-trip would mangle.
        raw = b'{"id":1, "amount":  100}'
        good = _good_hmac(secret, raw)
        wh = _make_handler(secret=secret)
        # payload is the parsed dict (what dashboard_api passes)
        result = wh.process(
            "orders/create",
            json.loads(raw),
            hmac_header=good,
            raw_body=raw,
        )
        assert result["status"] != "rejected"

    def test_invalid_hmac_rejected(self):
        secret = "test-secret"
        raw = b'{"id": 1}'
        wh = _make_handler(secret=secret)
        result = wh.process(
            "orders/create",
            json.loads(raw),
            hmac_header="not-a-valid-hmac",
            raw_body=raw,
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "invalid_hmac"

    def test_tampered_body_rejected(self):
        """Attacker modifies the body but keeps the original
        HMAC -> reject."""
        secret = "test-secret"
        original = b'{"id": 1, "amount": 100}'
        good = _good_hmac(secret, original)
        tampered = b'{"id": 1, "amount": 999999}'
        wh = _make_handler(secret=secret)
        result = wh.process(
            "orders/create",
            json.loads(tampered),
            hmac_header=good,
            raw_body=tampered,
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "invalid_hmac"


class TestBase64Format:

    def test_hex_format_no_longer_accepted_as_shopify_sig(self):
        """W962-39 (3): hex-digest format doesn't decode as a
        valid Shopify HMAC. Even if an attacker submits the
        correct HEX HMAC of the body, the receiver's BASE64
        check rejects it."""
        import hashlib
        import hmac as _hmac
        secret = "test-secret"
        raw = b'{"id": 1}'
        hex_sig = _hmac.new(
            secret.encode(), raw, hashlib.sha256,
        ).hexdigest()
        wh = _make_handler(secret=secret)
        result = wh.process(
            "orders/create",
            json.loads(raw),
            hmac_header=hex_sig,
            raw_body=raw,
        )
        assert result["status"] == "rejected"
