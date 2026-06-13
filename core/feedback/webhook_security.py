"""Webhook payload signature verification.

Wave 57: ``shopai webhook receive`` accepted any payload --
anyone reaching the operator's webhook endpoint could spoof
events ("orders/create with $1M attributed!"). Shopify (and
most webhook senders) ship with an HMAC signature header
the receiver must verify.

This module provides:

  - verify_hmac(raw_body, header_value, secret) -> bool
  - Standard Shopify SHA256 HMAC base64-encoded signature

## Standard Shopify behaviour

Shopify computes:
    HMAC-SHA256(secret, raw_body) -> base64-encoded digest

The receiver gets the digest in ``X-Shopify-Hmac-Sha256``
header. To verify, recompute and constant-time compare.

CRITICAL: must use the RAW body (bytes before any JSON
parsing). Re-serializing the parsed payload won't match
Shopify's HMAC because of key ordering, whitespace, etc.

## API

  verify_hmac(raw_body, header_value, secret) -> bool
    Returns True when the header matches the recomputed HMAC.
    Returns False on mismatch OR malformed inputs (never
    raises).
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac


def verify_hmac(
    raw_body: bytes | str,
    header_value: str | None,
    secret: str | None,
) -> bool:
    """Verify a Shopify-style SHA256 HMAC base64 signature.

    Args:
        raw_body: The raw bytes (or string) of the request
            body, BEFORE any JSON parsing.
        header_value: The X-Shopify-Hmac-Sha256 header value
            from the request.
        secret: The webhook secret configured on the Shopify
            admin (or equivalent).

    Returns:
        True when valid; False otherwise. Never raises.
    """
    if not header_value or not secret:
        return False
    if isinstance(raw_body, str):
        body_bytes = raw_body.encode("utf-8")
    else:
        body_bytes = raw_body
    if not isinstance(body_bytes, (bytes, bytearray)):
        return False
    try:
        secret_bytes = secret.encode("utf-8")
        digest = _hmac.new(
            secret_bytes,
            body_bytes,
            hashlib.sha256,
        ).digest()
        expected = base64.b64encode(digest).decode("utf-8")
    except Exception:  # noqa: BLE001
        return False
    # Constant-time compare to defeat timing attacks
    return _hmac.compare_digest(
        expected.strip(),
        header_value.strip(),
    )


def compute_hmac(
    raw_body: bytes | str,
    secret: str,
) -> str:
    """Compute the HMAC-SHA256 base64 signature for a body +
    secret. Useful for tests + outbound webhook senders."""
    if isinstance(raw_body, str):
        body_bytes = raw_body.encode("utf-8")
    else:
        body_bytes = raw_body
    digest = _hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")
