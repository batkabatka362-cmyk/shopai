"""Webhook Handler Engine — signature verifier.

Verifies the HMAC-SHA256 signature on incoming Shopify webhooks.
Uses constant-time comparison to prevent timing attacks.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any


def verify_signature(
    raw_payload: bytes | str,
    hmac_header: str,
    shared_secret: str,
) -> dict[str, Any]:
    """Verify the HMAC-SHA256 signature of a Shopify webhook payload.

    Args:
        raw_payload: The raw webhook body (bytes or UTF-8 string).
        hmac_header: The HMAC value from the X-Shopify-Hmac-Sha256 header.
        shared_secret: The Shopify app shared secret.

    Returns:
        Structured dict with verification result.
    """
    try:
        if not hmac_header:
            return {
                "status": "success",
                "signature_valid": False,
                "hmac_computed": "",
                "note": "No HMAC header provided",
            }

        if not shared_secret:
            return {
                "status": "error",
                "signature_valid": False,
                "hmac_computed": "",
                "error": "Shared secret is required for HMAC verification",
            }

        # Normalize payload to bytes
        if isinstance(raw_payload, str):
            payload_bytes = raw_payload.encode("utf-8")
        elif isinstance(raw_payload, dict):
            # If someone passes a dict, serialize it consistently
            import json
            payload_bytes = json.dumps(raw_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        else:
            payload_bytes = raw_payload

        secret_bytes = shared_secret.encode("utf-8")

        # Compute HMAC-SHA256
        computed_hmac = hmac.new(
            secret_bytes,
            payload_bytes,
            hashlib.sha256,
        ).digest()

        # Base64 encode for comparison with Shopify header
        computed_b64 = base64.b64encode(computed_hmac).decode("utf-8")

        # Decode the header value for constant-time comparison
        try:
            header_bytes = base64.b64decode(hmac_header)
        except Exception:
            # Header might not be valid base64 — try direct comparison
            header_bytes = hmac_header.encode("utf-8")
            computed_hmac = computed_b64.encode("utf-8")

        # Constant-time comparison to prevent timing attacks
        signature_valid = hmac.compare_digest(computed_hmac, header_bytes)

        return {
            "status": "success",
            "signature_valid": signature_valid,
            "hmac_computed": computed_b64,
        }
    except Exception as exc:
        return {
            "status": "error",
            "signature_valid": False,
            "hmac_computed": "",
            "error": f"Signature verification failed: {exc}",
        }
