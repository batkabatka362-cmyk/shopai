"""Fraud Detection Engine — address verifier.

Compares billing and shipping addresses and flags anomalies:
  - Billing/shipping mismatch (fuzzy)
  - PO Box detection (regex)
  - Freight forwarder detection (known addresses)
  - Country risk scoring
"""
from __future__ import annotations

import copy
import re
from typing import Any

# PO Box regex — matches "PO Box", "P.O. Box", "P O Box", "Post Office Box", etc.
_PO_BOX_RE = re.compile(
    r"\b(p\.?\s*o\.?\s*box|post\s+office\s+box)\b",
    re.IGNORECASE,
)

# Known freight forwarder / reshipping service address fragments
_FREIGHT_FORWARDER_FRAGMENTS: list[str] = [
    "shipito",
    "myus.com",
    "stackry",
    "planet express",
    "borderlinx",
    "viabox",
    "usgobuy",
    "fishisfast",
    "forward2me",
    "parcl",
    "1405 sw 6th ave",  # known reshipping hub
]

# Country risk tiers
_HIGH_RISK_COUNTRIES: set[str] = {
    "NG", "GH", "CI", "CM", "PK", "BD", "VN", "ID", "RO", "UA",
}
_MEDIUM_RISK_COUNTRIES: set[str] = {
    "BR", "MX", "CO", "PH", "IN", "EG", "KE", "TZ",
}


def verify_address(
    shipping: dict[str, Any],
    billing: dict[str, Any],
) -> dict[str, Any]:
    """Verify addresses and compute address-based risk score.

    Args:
        shipping: Shipping address dict.
        billing: Billing address dict.

    Returns:
        Structured dict with score, match status, and flags.
    """
    try:
        shipping = copy.deepcopy(shipping)
        billing = copy.deepcopy(billing)

        sub_scores: list[tuple[float, float]] = []  # (score, weight)

        # ---- Billing/Shipping match ----
        billing_shipping_match = _fuzzy_address_match(billing, shipping)
        if billing_shipping_match:
            sub_scores.append((0.0, 0.35))
        else:
            sub_scores.append((0.6, 0.35))

        # ---- PO Box detection ----
        shipping_text = _flatten_address(shipping)
        billing_text = _flatten_address(billing)
        is_po_box = bool(
            _PO_BOX_RE.search(shipping_text) or _PO_BOX_RE.search(billing_text)
        )
        if is_po_box:
            sub_scores.append((0.5, 0.15))
        else:
            sub_scores.append((0.0, 0.15))

        # ---- Freight forwarder detection ----
        combined_text = (shipping_text + " " + billing_text).lower()
        is_freight_forwarder = any(
            frag in combined_text for frag in _FREIGHT_FORWARDER_FRAGMENTS
        )
        if is_freight_forwarder:
            sub_scores.append((0.8, 0.25))
        else:
            sub_scores.append((0.0, 0.25))

        # ---- Country risk ----
        shipping_country = str(shipping.get("country", "")).upper().strip()
        billing_country = str(billing.get("country", "")).upper().strip()

        country_risk = _country_risk_level(shipping_country, billing_country)
        if country_risk == "high":
            sub_scores.append((0.7, 0.15))
        elif country_risk == "medium":
            sub_scores.append((0.4, 0.15))
        else:
            sub_scores.append((0.05, 0.15))

        # ---- Country mismatch between billing and shipping ----
        if (
            billing_country
            and shipping_country
            and billing_country != shipping_country
        ):
            sub_scores.append((0.6, 0.10))
        else:
            sub_scores.append((0.0, 0.10))

        # ---- Weighted composite ----
        total_weight = sum(w for _, w in sub_scores)
        score = sum(s * w for s, w in sub_scores) / total_weight if total_weight else 0.0
        score = round(max(0.0, min(1.0, score)), 4)

        return {
            "status": "success",
            "score": score,
            "billing_shipping_match": billing_shipping_match,
            "is_po_box": is_po_box,
            "is_freight_forwarder": is_freight_forwarder,
            "country_risk": country_risk,
        }
    except Exception as exc:
        return _fail(f"Address verification failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for comparison."""
    text = text.lower().strip()
    text = re.sub(r"[.,#\-/]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    # Common abbreviations
    replacements = {
        " street": " st",
        " avenue": " ave",
        " boulevard": " blvd",
        " drive": " dr",
        " road": " rd",
        " lane": " ln",
        " court": " ct",
        " apartment": " apt",
        " suite": " ste",
    }
    for long, short in replacements.items():
        text = text.replace(long, short)
    return text


def _fuzzy_address_match(
    addr_a: dict[str, Any],
    addr_b: dict[str, Any],
) -> bool:
    """Compare two addresses with fuzzy matching.

    Considers a match if the normalized core fields are similar enough.
    """
    norm_a = _normalize(_flatten_address(addr_a))
    norm_b = _normalize(_flatten_address(addr_b))

    if norm_a == norm_b:
        return True

    # Jaccard similarity on character trigrams
    trigrams_a = _trigrams(norm_a)
    trigrams_b = _trigrams(norm_b)
    if not trigrams_a or not trigrams_b:
        return False

    intersection = len(trigrams_a & trigrams_b)
    union = len(trigrams_a | trigrams_b)
    similarity = intersection / union if union else 0.0
    return similarity >= 0.70


def _trigrams(text: str) -> set[str]:
    """Compute character trigrams from a string."""
    if len(text) < 3:
        return {text}
    return {text[i : i + 3] for i in range(len(text) - 2)}


def _flatten_address(addr: dict[str, Any]) -> str:
    """Concatenate address fields into a single string."""
    parts = [
        str(addr.get("line1", "")),
        str(addr.get("line2", "")),
        str(addr.get("city", "")),
        str(addr.get("state", "")),
        str(addr.get("zip", "")),
        str(addr.get("country", "")),
    ]
    return " ".join(p for p in parts if p).strip()


def _country_risk_level(shipping_country: str, billing_country: str) -> str:
    """Return the higher risk tier of two countries."""
    for country in (shipping_country, billing_country):
        if country in _HIGH_RISK_COUNTRIES:
            return "high"
    for country in (shipping_country, billing_country):
        if country in _MEDIUM_RISK_COUNTRIES:
            return "medium"
    return "low"


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "score": 0.0,
        "billing_shipping_match": False,
        "is_po_box": False,
        "is_freight_forwarder": False,
        "country_risk": "unknown",
        "error": reason,
    }
