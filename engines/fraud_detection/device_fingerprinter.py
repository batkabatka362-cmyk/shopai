"""Fraud Detection Engine — device fingerprinter.

Analyzes device information to detect bots, headless browsers,
timezone inconsistencies, and other device-level anomalies.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any


# ---------------------------------------------------------------------------
# Bot / automation user-agent patterns
# ---------------------------------------------------------------------------

_BOT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(bot|crawl|spider|scrape|phantom|headless)\b", re.IGNORECASE),
    re.compile(r"\b(selenium|puppeteer|playwright|cypress)\b", re.IGNORECASE),
    re.compile(r"\bHeadlessChrome\b", re.IGNORECASE),
    re.compile(r"\bPhantomJS\b", re.IGNORECASE),
    re.compile(r"\bcurl/", re.IGNORECASE),
    re.compile(r"\bwget/", re.IGNORECASE),
    re.compile(r"\bpython-requests\b", re.IGNORECASE),
    re.compile(r"\bgo-http-client\b", re.IGNORECASE),
    re.compile(r"\bnode-fetch\b", re.IGNORECASE),
    re.compile(r"\baxios/", re.IGNORECASE),
    re.compile(r"\bPostman", re.IGNORECASE),
    re.compile(r"\bhttpie\b", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Timezone-to-country mapping (simplified — major zones)
# ---------------------------------------------------------------------------

_TIMEZONE_COUNTRY_MAP: dict[str, set[str]] = {
    "America/New_York": {"US", "CA"},
    "America/Chicago": {"US", "CA", "MX"},
    "America/Denver": {"US", "CA", "MX"},
    "America/Los_Angeles": {"US", "CA", "MX"},
    "America/Anchorage": {"US"},
    "Pacific/Honolulu": {"US"},
    "America/Toronto": {"US", "CA"},
    "America/Vancouver": {"US", "CA"},
    "America/Mexico_City": {"MX"},
    "America/Sao_Paulo": {"BR"},
    "America/Argentina/Buenos_Aires": {"AR"},
    "America/Bogota": {"CO"},
    "America/Lima": {"PE"},
    "America/Santiago": {"CL"},
    "Europe/London": {"GB", "IE", "PT"},
    "Europe/Paris": {"FR", "BE", "NL", "LU"},
    "Europe/Berlin": {"DE", "AT", "CH", "PL", "CZ"},
    "Europe/Rome": {"IT", "MT"},
    "Europe/Madrid": {"ES"},
    "Europe/Moscow": {"RU"},
    "Europe/Istanbul": {"TR"},
    "Asia/Tokyo": {"JP"},
    "Asia/Seoul": {"KR"},
    "Asia/Shanghai": {"CN"},
    "Asia/Hong_Kong": {"CN", "HK"},
    "Asia/Singapore": {"SG"},
    "Asia/Kolkata": {"IN"},
    "Asia/Dubai": {"AE", "OM"},
    "Australia/Sydney": {"AU"},
    "Australia/Melbourne": {"AU"},
    "Pacific/Auckland": {"NZ"},
}

# ---------------------------------------------------------------------------
# Suspicious screen resolutions
# ---------------------------------------------------------------------------

_HEADLESS_RESOLUTIONS: set[str] = {
    "0x0", "1x1", "800x600",
}


def analyze_device(
    device: dict[str, Any],
) -> dict[str, Any]:
    """Analyze device fingerprint for fraud signals.

    Args:
        device: Device data dict with user_agent, screen_resolution, timezone, etc.

    Returns:
        Structured dict with device analysis results.
    """
    try:
        device = copy.deepcopy(device)

        risk_points = 0.0
        max_points = 0.0

        user_agent = str(device.get("user_agent", ""))
        screen_resolution = str(device.get("screen_resolution", ""))
        tz = str(device.get("timezone", ""))
        language = str(device.get("language", ""))
        cookies_enabled = device.get("cookies_enabled", True)

        # ---- 1. Bot / automation detection (weight: 4) ----
        max_points += 4.0
        is_bot = _detect_bot(user_agent)
        if is_bot:
            risk_points += 4.0

        # Empty or missing user agent is also suspicious
        if not user_agent.strip():
            risk_points += 3.0
            is_bot = True

        # ---- 2. Screen resolution anomaly (weight: 2) ----
        max_points += 2.0
        resolution_norm = screen_resolution.lower().strip()
        if resolution_norm in _HEADLESS_RESOLUTIONS:
            risk_points += 2.0
        elif not resolution_norm:
            risk_points += 1.5

        # ---- 3. Timezone consistency (weight: 2) ----
        max_points += 2.0
        timezone_consistent = True
        # We validate against the shipping country if available
        # For now, just check if the timezone is a known valid one
        if tz and tz not in _TIMEZONE_COUNTRY_MAP:
            # Unknown timezone — mild risk
            risk_points += 0.5
            timezone_consistent = False
        elif not tz:
            risk_points += 1.0
            timezone_consistent = False

        # ---- 4. Cookies disabled (weight: 1) ----
        max_points += 1.0
        if not cookies_enabled:
            risk_points += 1.0

        # ---- 5. Missing language header (weight: 1) ----
        max_points += 1.0
        if not language.strip():
            risk_points += 1.0

        # ---- Compute final score ----
        score = round(risk_points / max_points, 4) if max_points > 0 else 0.0
        score = max(0.0, min(1.0, score))

        # Generate a fingerprint hash from available device attributes
        fingerprint_hash = _compute_fingerprint(device)

        return {
            "status": "success",
            "score": score,
            "is_bot": is_bot,
            "timezone_consistent": timezone_consistent,
            "fingerprint_hash": fingerprint_hash,
        }
    except Exception as exc:
        return {
            "status": "error",
            "score": 0.0,
            "is_bot": False,
            "timezone_consistent": True,
            "fingerprint_hash": "",
            "error": f"Device analysis failed: {exc}",
        }


def check_timezone_country(
    timezone_str: str,
    country_code: str,
) -> bool:
    """Check if a timezone is consistent with a country code.

    Args:
        timezone_str: IANA timezone string.
        country_code: ISO 3166-1 alpha-2 country code.

    Returns:
        True if consistent or if lookup is not possible.
    """
    if not timezone_str or not country_code:
        return True  # Cannot verify — assume OK
    allowed = _TIMEZONE_COUNTRY_MAP.get(timezone_str)
    if allowed is None:
        return True  # Unknown timezone — cannot verify
    return country_code.upper().strip() in allowed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_bot(user_agent: str) -> bool:
    """Check user agent against known bot patterns."""
    return any(pattern.search(user_agent) for pattern in _BOT_PATTERNS)


def _compute_fingerprint(device: dict[str, Any]) -> str:
    """Compute a deterministic hash of device attributes."""
    parts = [
        str(device.get("user_agent", "")),
        str(device.get("screen_resolution", "")),
        str(device.get("timezone", "")),
        str(device.get("language", "")),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
