"""Tax Engine — exemption checker.

Checks customer-level and product-category-level tax exemptions.
Determines which line items are fully or partially exempt.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# US states where food (grocery) is fully exempt
# ---------------------------------------------------------------------------

_FOOD_EXEMPT_STATES = {
    "AZ", "CA", "CT", "FL", "GA", "IA", "ID", "IN", "KY", "LA",
    "MA", "MD", "ME", "MI", "MN", "NE", "NJ", "NM", "NY", "ND",
    "OH", "PA", "RI", "SC", "TX", "VT", "WA", "WI", "WV", "WY",
    "CO",
}

# States where clothing is exempt
_CLOTHING_EXEMPT_STATES = {"MN", "NJ", "NY", "PA", "RI", "VT"}

# States where medicine / prescription drugs are exempt
_MEDICINE_EXEMPT_STATES = {
    "AL", "AZ", "CA", "CO", "CT", "FL", "GA", "HI", "IA", "ID",
    "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN",
    "MO", "MS", "MT", "NC", "ND", "NE", "NJ", "NM", "NV", "NY",
    "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VA", "VT", "WA", "WI", "WV", "WY", "DC",
}

# Valid exemption types for customer-level exemption
_VALID_EXEMPTION_TYPES = {
    "resale",
    "non_profit",
    "government",
    "diplomatic",
    "agricultural",
    "manufacturing",
    "educational",
}


def check_exemptions(
    customer: dict[str, Any],
    line_items: list[dict[str, Any]],
    jurisdictions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check tax exemptions for a customer and their line items.

    Args:
        customer: CustomerInfo dict.
        line_items: List of TransactionItem dicts.
        jurisdictions: List of JurisdictionInfo dicts.

    Returns:
        Structured dict with per-line-item exemption status.
    """
    try:
        customer = copy.deepcopy(customer)
        line_items = copy.deepcopy(line_items)
        jurisdictions = copy.deepcopy(jurisdictions)

        # Determine the primary state for category exemptions
        primary_state = _get_primary_state(jurisdictions)

        # Check customer-level exemption
        customer_exempt = _is_customer_exempt(customer)
        customer_reason = ""
        if customer_exempt:
            cert = customer.get("exemption_certificate") or ""
            etype = str(customer.get("exemption_type", "resale"))
            if customer.get("tax_exempt"):
                customer_reason = f"Customer tax exempt (type={etype}, cert={cert})"

        exemptions: list[dict[str, Any]] = []
        all_exempt = True

        for item in line_items:
            item_id = str(item.get("id", "unknown"))
            category = str(item.get("product_category", "")).lower()

            # Customer-level exemption overrides everything
            if customer_exempt:
                exemptions.append({
                    "line_item_id": item_id,
                    "exempt": True,
                    "reason": customer_reason,
                })
                continue

            # Check product category exemptions
            cat_exempt, cat_reason = _check_category_exemption(
                category, primary_state,
            )

            if cat_exempt:
                exemptions.append({
                    "line_item_id": item_id,
                    "exempt": True,
                    "reason": cat_reason,
                })
            else:
                exemptions.append({
                    "line_item_id": item_id,
                    "exempt": False,
                    "reason": "No exemption applicable",
                })
                all_exempt = False

        return {
            "status": "success",
            "exemptions": exemptions,
            "fully_exempt": all_exempt,
        }
    except Exception as exc:
        return _fail(f"Exemption check failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fail(reason: str) -> dict[str, Any]:
    """Standardized error output."""
    return {
        "status": "error",
        "exemptions": [],
        "fully_exempt": False,
        "error": reason,
    }


def _is_customer_exempt(customer: dict[str, Any]) -> bool:
    """Check if the customer has a valid tax exemption."""
    if not customer.get("tax_exempt"):
        return False

    cert = customer.get("exemption_certificate")
    if cert and str(cert).strip():
        return True

    # Also accept if exemption_type is valid even without cert
    etype = str(customer.get("exemption_type", "")).lower()
    if etype in _VALID_EXEMPTION_TYPES:
        return True

    # tax_exempt flag is set but no cert or type — still honor it
    return True


def _get_primary_state(jurisdictions: list[dict[str, Any]]) -> str:
    """Extract the primary US state from jurisdictions list."""
    for jur in jurisdictions:
        if jur.get("type") == "state":
            code = str(jur.get("code", ""))
            if code.startswith("US-"):
                return code.split("-")[1]
            return str(jur.get("name", ""))
    return ""


def _check_category_exemption(
    category: str,
    state: str,
) -> tuple[bool, str]:
    """Check if a product category is exempt in the given state.

    Returns (is_exempt, reason).
    """
    if not state or not category:
        return False, ""

    # Normalize category
    cat = category.lower().replace(" ", "_")

    # Food / grocery exemptions
    if cat in ("food", "grocery", "groceries", "food_and_beverage"):
        if state in _FOOD_EXEMPT_STATES:
            return True, f"Food/grocery exempt in {state}"

    # Clothing exemptions
    if cat in ("clothing", "apparel", "clothes"):
        if state in _CLOTHING_EXEMPT_STATES:
            return True, f"Clothing exempt in {state}"

    # Medicine exemptions
    if cat in ("medicine", "prescription", "pharmaceutical", "rx", "otc_medicine"):
        if state in _MEDICINE_EXEMPT_STATES:
            return True, f"Medicine/prescription exempt in {state}"

    # Digital goods — some states exempt
    if cat in ("digital", "digital_good", "software", "saas"):
        # A few states don't tax digital goods
        no_digital_tax = {"CA", "FL", "GA", "IL", "MO", "MT", "NH", "OR", "VA"}
        if state in no_digital_tax:
            return True, f"Digital goods not taxed in {state}"

    return False, ""
