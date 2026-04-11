"""Fraud Detection Engine — address verifier.

Checks billing/shipping address match (fuzzy), detects PO boxes,
identifies known freight forwarder addresses, and assigns country risk.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import re
from typing import Any


# ---------------------------------------------------------------------------
# PO Box regex patterns
# ---------------------------------------------------------------------------

_PO_BOX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bP\.?\s*O\.?\s*Box\b", re.IGNORECASE),
    re.compile(r"\bPost\s+Office\s+Box\b", re.IGNORECASE),
    re.compile(r"\bPOB\s+\d", re.IGNORECASE),
    re.compile(r"\bPMB\s+\d", re.IGNORECASE),
    re.compile(r"^\s*Box\s+\d", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Known freight forwarder address fragments
# ---------------------------------------------------------------------------

_FREIGHT_FORWARDER_MARKERS: list[str] = [
    "shipito",
    "myus.com",
    "stackry",
    "planet express",
    "viabox",
    "usgobuy",
    "fishisfast",
    "forward2me",
    "borderlinx",
    "parcl",
]

# ---------------------------------------------------------------------------
# Country risk tiers
# ---------------------------------------------------------------------------

_HIGH_RISK_COUNTRIES: set[str] = {
    "NG", "GH", "RO", "UA", "BY", "VN", "ID", "PK", "BD", "EG",
    "KE", "TZ", "CI", "CM", "SN", "ML",
}

_MEDIUM_RISK_COUNTRIES: set[str] = {
    "BR", "MX", "CO", "AR", "TR", "TH", "PH", "IN", "ZA", "MY",
    "RU", "RS", "BG", "HR", "BA",
}


def verify_address(
    shipping: dict[str, Any],
    billing: dict[str, Any],
) -> dict[str, Any]:
    """Verify address attributes for fraud signals.

    Args:
        shipping: Shipping address dict.
        billing: Billing address dict.

    Returns:
        Structured dict with address verification results.
    """
    try:
        shipping = copy.deepcopy(shipping)
        billing = copy.deepcopy(billing)

        risk_points = 0.0
        max_points = 0.0

        # ---- 1. Billing/shipping match (weight: 3) ----
        max_points += 3.0
        billing_shipping_match = _addresses_match(billing, shipping)
        if not billing_shipping_match:
            risk_points += 3.0

        # ---- 2. PO box detection (weight: 1.5) ----
        max_points += 1.5
        ship_line1 = str(shipping.get("line1", ""))
        ship_line2 = str(shipping.get("line2", ""))
        bill_line1 = str(billing.get("line1", ""))
        bill_line2 = str(billing.get("line2", ""))

        is_po_box = (
            _is_po_box(ship_line1) or _is_po_box(ship_line2)
            or _is_po_box(bill_line1) or _is_po_box(bill_line2)
        )
        if is_po_box:
            risk_points += 1.5

        # ---- 3. Freight forwarder detection (weight: 3) ----
        max_points += 3.0
        combined_shipping = f"{ship_line1} {ship_line2}".lower()
        is_freight_forwarder = any(
            marker in combined_shipping for marker in _FREIGHT_FORWARDER_MARKERS
        )
        if is_freight_forwarder:
            risk_points += 3.0

        # ---- 4. Country risk (weight: 2.5) ----
        max_points += 2.5
        ship_country = str(shipping.get("country", "")).upper().strip()
        bill_country = str(billing.get("country", "")).upper().strip()

        country_risk = "low"
        if ship_country in _HIGH_RISK_COUNTRIES or bill_country in _HIGH_RISK_COUNTRIES:
            country_risk = "high"
            risk_points += 2.5
        elif ship_country in _MEDIUM_RISK_COUNTRIES or bill_country in _MEDIUM_RISK_COUNTRIES:
            country_risk = "medium"
            risk_points += 1.0

        # ---- 5. Cross-country mismatch (weight: 1.5) ----
        max_points += 1.5
        if ship_country and bill_country and ship_country != bill_country:
            risk_points += 1.5

        # ---- Compute final score ----
        score = round(risk_points / max_points, 4) if max_points > 0 else 0.0
        score = max(0.0, min(1.0, score))

        return {
            "status": "success",
            "score": score,
            "billing_shipping_match": billing_shipping_match,
            "is_po_box": is_po_box,
            "is_freight_forwarder": is_freight_forwarder,
            "country_risk": country_risk,
        }
    except Exception as exc:
        return {
            "status": "error",
            "score": 0.0,
            "billing_shipping_match": False,
            "is_po_box": False,
            "is_freight_forwarder": False,
            "country_risk": "unknown",
            "error": f"Address verification failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Normalize an address string for comparison."""
    text = text.lower().strip()
    text = re.sub(r"[.,#\-/\\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    replacements = {
        " street": " st",
        " avenue": " ave",
        " boulevard": " blvd",
        " drive": " dr",
        " road": " rd",
        " lane": " ln",
        " court": " ct",
        " place": " pl",
        " apartment": " apt",
        " suite": " ste",
    }
    for full, abbr in replacements.items():
        text = text.replace(full, abbr)
    return text


def _addresses_match(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Check if two addresses match using fuzzy normalization."""
    fields = ["line1", "city", "state", "zip", "country"]
    for field in fields:
        val_a = _normalize(str(a.get(field, "")))
        val_b = _normalize(str(b.get(field, "")))
        if not val_a and not val_b:
            continue
        if val_a != val_b:
            return False
    return True


def _is_po_box(text: str) -> bool:
    """Check if the text indicates a PO box."""
    return any(pattern.search(text) for pattern in _PO_BOX_PATTERNS)
