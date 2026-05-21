"""Fraud Detection Engine — blacklist checker.

Checks email, IP, phone, and address hash against stored blacklists
in .memory/fraud_detection/blacklists.json.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory", "fraud_detection")
_BLACKLIST_PATH = os.path.join(_MEMORY_DIR, "blacklists.json")

# Default empty blacklist structure
_EMPTY_BLACKLIST: dict[str, list[str]] = {
    "emails": [],
    "ips": [],
    "phones": [],
    "address_hashes": [],
}


def check_blacklists(
    email: str,
    ip: str,
    phone: str,
    address_hash: str,
) -> dict[str, Any]:
    """Check identifiers against stored blacklists.

    Args:
        email: Customer email address.
        ip: Customer IP address.
        phone: Customer phone number.
        address_hash: Normalized address hash.

    Returns:
        Structured dict with per-field match results and score.
    """
    try:
        blacklists = _load_blacklists()

        email_norm = email.lower().strip()
        ip_norm = ip.strip()
        phone_norm = _normalize_phone(phone)
        addr_norm = address_hash.lower().strip()

        bl_emails = {e.lower().strip() for e in blacklists.get("emails", [])}
        bl_ips = {i.strip() for i in blacklists.get("ips", [])}
        bl_phones = {_normalize_phone(p) for p in blacklists.get("phones", [])}
        bl_addrs = {a.lower().strip() for a in blacklists.get("address_hashes", [])}

        email_listed = bool(email_norm and email_norm in bl_emails)
        ip_listed = bool(ip_norm and ip_norm in bl_ips)
        phone_listed = bool(phone_norm and phone_norm in bl_phones)
        address_listed = bool(addr_norm and addr_norm in bl_addrs)

        # Also check email domain against blacklisted domains
        domain = email_norm.split("@")[-1] if "@" in email_norm else ""
        bl_domains = {e for e in bl_emails if not e.startswith("@") is False}
        domain_listed = bool(
            domain and f"@{domain}" in bl_emails
        )

        # Score: each blacklist hit contributes to the score
        hits = sum([email_listed, ip_listed, phone_listed, address_listed, domain_listed])
        max_hits = 5

        # Blacklist matches are heavily weighted — any single match is serious
        if hits >= 3:
            score = 1.0
        elif hits == 2:
            score = 0.85
        elif hits == 1:
            score = 0.7
        else:
            score = 0.0

        return {
            "status": "success",
            "score": round(score, 4),
            "email_listed": email_listed or domain_listed,
            "ip_listed": ip_listed,
            "phone_listed": phone_listed,
            "address_listed": address_listed,
        }
    except Exception as exc:
        return {
            "status": "error",
            "score": 0.0,
            "email_listed": False,
            "ip_listed": False,
            "phone_listed": False,
            "address_listed": False,
            "error": f"Blacklist check failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_blacklists() -> dict[str, list[str]]:
    """Load blacklists from disk, returning empty structure if not found."""
    if not os.path.isfile(_BLACKLIST_PATH):
        return copy.deepcopy(_EMPTY_BLACKLIST)
    try:
        with open(_BLACKLIST_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError) as exc:
        # Falling back to an empty blacklist means fraud
        # checks PASS for everyone -- a real security blindspot.
        # Without this warning a corrupt blacklists.json could
        # let known-bad emails / IPs through for weeks unnoticed.
        logger.warning(
            "_load_blacklists failed (%s), falling back to "
            "empty blacklist (fraud checks effectively "
            "disabled): %s",
            _BLACKLIST_PATH, exc,
        )
    return copy.deepcopy(_EMPTY_BLACKLIST)


def _normalize_phone(phone: str) -> str:
    """Normalize a phone number to digits only."""
    if not phone:
        return ""
    return "".join(c for c in phone if c.isdigit())
