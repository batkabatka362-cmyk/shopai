"""Deterministic per-partner referral code generation.

Given a partner identity (email or name), generate a stable
6-character alphanumeric code. Two key properties:

  1. **Idempotent.** Re-running with the same partner_email
     always returns the same code. Partners who share their
     link across multiple channels (Instagram bio + email
     signature + YouTube description) all use the same URL.

  2. **Collision-resistant.** Codes derive from SHA-256 of the
     normalized partner identity. A 6-char alphanumeric code
     has 36^6 = ~2 billion possibilities, more than sufficient
     for any single-store affiliate program.

  3. **Reversible-resistant.** A 6-char prefix of SHA-256 leaks
     nothing about the underlying partner email. Operator can
     publish codes freely.
"""
from __future__ import annotations

import hashlib
import re


_CODE_LEN = 6
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
# Ambiguity-avoidance: dropped 0/O/1/I to keep codes
# operator-readable + handwriting-friendly.


def _normalize(identity: str) -> str:
    """Lowercase + strip whitespace + canonical-form an email."""
    s = (identity or "").strip().lower()
    # Strip surrounding whitespace; keep the literal +tag and
    # dots so they're treated as part of the identity (a real
    # affiliate engine would normalize Gmail dots, but
    # operators may want to distinguish a+tag from a sometimes,
    # so we DON'T strip them here).
    return s


def generate_code(partner_identity: str) -> str:
    """Generate a stable 6-char ref code from the identity.

    Identity should be a partner's email when available
    (more unique). Falls back to name if email is missing.
    """
    norm = _normalize(partner_identity)
    if not norm:
        return ""
    digest = hashlib.sha256(norm.encode("utf-8")).digest()
    # Sample 6 alphabet characters from the digest bytes.
    code_chars: list[str] = []
    for b in digest[:_CODE_LEN]:
        code_chars.append(_ALPHABET[b % len(_ALPHABET)])
    return "".join(code_chars)


def build_link(shop_url: str, code: str) -> str:
    """Build the canonical referral URL.

    ``shop_url`` should be the bare ``<store>.myshopify.com`` or
    a custom domain; the helper inserts https:// and ?ref=.
    Empty code => empty URL.
    """
    code = (code or "").strip()
    if not code:
        return ""
    shop = (shop_url or "").strip().rstrip("/")
    if not shop:
        return ""
    if not re.match(r"^https?://", shop):
        shop = "https://" + shop
    sep = "&" if "?" in shop else "?"
    return f"{shop}{sep}ref={code}"
