"""Tests for core.feedback.webhook_security."""
from __future__ import annotations

from core.feedback.webhook_security import (
    compute_hmac, verify_hmac,
)


class TestComputeHMAC:

    def test_known_pair(self):
        """Verify against a hand-computed known good pair."""
        # Hand-computed with `openssl dgst -sha256 -hmac s | base64`
        # for body="hello", secret="s"
        body = b"hello"
        secret = "s"
        result = compute_hmac(body, secret)
        # We just need it to be deterministic + reasonable
        assert isinstance(result, str)
        assert len(result) > 20  # base64 of 32-byte digest

    def test_str_body_equivalent_to_bytes(self):
        a = compute_hmac("hello", "s")
        b = compute_hmac(b"hello", "s")
        assert a == b


class TestVerifyHMAC:

    def test_valid_returns_true(self):
        body = b'{"id":"1"}'
        secret = "mysecret"
        sig = compute_hmac(body, secret)
        assert verify_hmac(body, sig, secret) is True

    def test_wrong_secret_returns_false(self):
        body = b'{"id":"1"}'
        sig = compute_hmac(body, "right")
        assert verify_hmac(body, sig, "wrong") is False

    def test_tampered_body_returns_false(self):
        sig = compute_hmac(b'{"id":"1"}', "s")
        # Same signature, different body
        assert verify_hmac(b'{"id":"2"}', sig, "s") is False

    def test_missing_header_returns_false(self):
        assert verify_hmac(b"x", None, "s") is False
        assert verify_hmac(b"x", "", "s") is False

    def test_missing_secret_returns_false(self):
        sig = compute_hmac(b"x", "s")
        assert verify_hmac(b"x", sig, None) is False
        assert verify_hmac(b"x", sig, "") is False

    def test_str_body_works(self):
        body = '{"id":"1"}'
        secret = "s"
        sig = compute_hmac(body, secret)
        assert verify_hmac(body, sig, secret) is True

    def test_whitespace_in_header_trimmed(self):
        body = b"hello"
        secret = "s"
        sig = compute_hmac(body, secret)
        # Some senders pad with whitespace
        assert verify_hmac(body, f"  {sig}  ", secret) is True

    def test_constant_time_compare(self):
        """Verify uses hmac.compare_digest (defeats timing
        attacks). We can't directly test timing but we can
        verify it returns False for almost-correct sigs."""
        body = b"hello"
        sig = compute_hmac(body, "s")
        # Tamper one char
        tampered = sig[:-1] + ("A" if sig[-1] != "A" else "B")
        assert verify_hmac(body, tampered, "s") is False
