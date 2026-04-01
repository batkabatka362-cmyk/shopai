"""Lead time rules and constraints.

Hard limits and business rules that govern lead time decisions.
These come from operational experience — violating them leads to
stockouts, angry customers, and margin erosion.
"""
from __future__ import annotations

from typing import Any


# --- Maximum acceptable lead time by product type (days) ---
# Beyond these, customer expectations break down and cancel rates spike.
MAX_LEAD_TIME_BY_PRODUCT = {
    "fashion_apparel":     45,   # Trend-sensitive, short shelf life
    "electronics":         30,   # Customers expect fast delivery
    "home_decor":          60,   # More patience, but not infinite
    "beauty_cosmetics":    35,   # Expiry concerns, trend cycles
    "pet_supplies":        40,   # Recurring purchases need reliability
    "fitness_equipment":   50,   # Heavier items, customers plan ahead
    "toys_games":          35,   # Seasonal demand spikes
    "kitchen_gadgets":     40,   # Impulse buys cool off fast
    "phone_accessories":   25,   # Commodity — if slow, they buy elsewhere
    "jewelry":             30,   # Gift purchases, time-sensitive
    "outdoor_gear":        50,   # Seasonal but planned
    "default":             45,   # Fallback for unknown categories
}

# --- Buffer requirements ---
MIN_BUFFER_PCT = 0.20   # Minimum 20% buffer over quoted lead time
MAX_BUFFER_PCT = 0.60   # Cap buffer at 60% to avoid excess inventory
CRITICAL_ITEM_BUFFER_PCT = 0.35  # Higher buffer for best-selling items

# --- Peak season multiplier ---
# October-December and Chinese holidays inflate lead times significantly.
PEAK_SEASON_MULTIPLIER = 1.50   # +50% on all lead time components
CNY_MULTIPLIER = 1.80           # Chinese New Year — factories shut down

# --- Customs documentation requirements by destination ---
CUSTOMS_DOC_REQUIREMENTS = {
    "US": {
        "required": ["commercial_invoice", "packing_list", "bill_of_lading"],
        "conditional": ["FDA_prior_notice", "FCC_declaration", "CPSC_certificate"],
        "threshold_usd": 800,   # De minimis — under $800 duty-free (Section 321)
        "notes": "Section 321 exemption for shipments under $800. "
                 "Certain products (food, electronics, children's items) need agency clearance.",
    },
    "EU": {
        "required": ["commercial_invoice", "packing_list", "EUR1_certificate", "CE_marking_declaration"],
        "conditional": ["REACH_compliance", "WEEE_registration"],
        "threshold_eur": 150,   # VAT due from first euro, duty-free under 150 EUR
        "notes": "IOSS required for consignments under 150 EUR. "
                 "CE marking mandatory for most consumer products.",
    },
    "UK": {
        "required": ["commercial_invoice", "packing_list", "UKCA_declaration"],
        "conditional": ["REACH_UK_compliance"],
        "threshold_gbp": 135,   # VAT at point of sale under 135 GBP
        "notes": "Post-Brexit: UKCA mark replacing CE. Separate customs from EU.",
    },
    "CA": {
        "required": ["commercial_invoice", "packing_list", "Canada_customs_invoice"],
        "conditional": ["SCC_certificate"],
        "threshold_cad": 20,    # Very low de minimis
        "notes": "Low de minimis threshold. Most shipments incur duty + GST/HST.",
    },
    "AU": {
        "required": ["commercial_invoice", "packing_list", "import_declaration"],
        "conditional": ["biosecurity_permit"],
        "threshold_aud": 1000,  # GST from first dollar, duty-free under 1000 AUD
        "notes": "Strict biosecurity. Wood packaging needs ISPM-15 treatment.",
    },
}


def validate_lead_time(
    total_days: int,
    product_type: str = "default",
) -> dict[str, Any]:
    """Check if total lead time is acceptable for the product type."""
    max_days = MAX_LEAD_TIME_BY_PRODUCT.get(product_type, MAX_LEAD_TIME_BY_PRODUCT["default"])
    within_limit = total_days <= max_days
    return {
        "acceptable": within_limit,
        "total_days": total_days,
        "max_allowed": max_days,
        "product_type": product_type,
        "overage_days": max(0, total_days - max_days),
        "action": None if within_limit else (
            f"Lead time {total_days}d exceeds {max_days}d limit for {product_type}. "
            "Consider air freight or a closer supplier."
        ),
    }


def validate_buffer(
    quoted_days: int,
    buffer_days: int,
    is_critical_item: bool = False,
) -> dict[str, Any]:
    """Ensure buffer meets minimum requirements."""
    min_pct = CRITICAL_ITEM_BUFFER_PCT if is_critical_item else MIN_BUFFER_PCT
    actual_pct = buffer_days / max(quoted_days, 1)
    meets_minimum = actual_pct >= min_pct
    recommended_buffer = max(buffer_days, round(quoted_days * min_pct))
    return {
        "meets_minimum": meets_minimum,
        "buffer_days": buffer_days,
        "buffer_pct": round(actual_pct, 2),
        "required_pct": min_pct,
        "recommended_buffer_days": recommended_buffer,
    }


def apply_peak_adjustment(
    optimistic: int,
    likely: int,
    pessimistic: int,
    multiplier: float | None = None,
) -> tuple[int, int, int]:
    """Apply peak season inflation to lead time estimates."""
    m = multiplier or PEAK_SEASON_MULTIPLIER
    return (
        round(optimistic * m),
        round(likely * m),
        round(pessimistic * m),
    )


def get_docs_for_destination(destination: str) -> dict[str, Any]:
    """Return customs documentation requirements for a destination."""
    docs = CUSTOMS_DOC_REQUIREMENTS.get(destination)
    if docs is None:
        return {
            "destination": destination,
            "known": False,
            "note": "Documentation requirements unknown. Consult a customs broker.",
        }
    return {"destination": destination, "known": True, **docs}
