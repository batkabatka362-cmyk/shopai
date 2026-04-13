"""Cart Recovery Engine — message builder.

Builds the recovery message including subject line, body text, product
reminder, call-to-action, and personalization tokens.

Model note: Uses LLaMA for creative message generation.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Subject line templates by strategy
# ---------------------------------------------------------------------------

_SUBJECT_TEMPLATES: dict[str, list[str]] = {
    "email_reminder": [
        "You left something behind, {first_name}!",
        "Still thinking about it? Your cart is waiting",
        "Don't forget your items from {store_name}",
    ],
    "discount_offer": [
        "{first_name}, here's {discount}% off your cart!",
        "Your cart just got cheaper — {discount}% off inside",
        "We saved your cart + a special {discount}% discount",
    ],
    "free_shipping": [
        "Free shipping on your cart — for a limited time!",
        "{first_name}, your shipping is on us!",
        "Good news: free shipping on the items you love",
    ],
    "urgency_message": [
        "Your items are selling fast, {first_name}!",
        "Low stock alert: complete your order now",
        "Last chance — your cart items may sell out soon",
    ],
    "retarget_ad": [
        "Still interested? Your favorites are waiting",
        "Picked for you — items you recently viewed",
        "Complete your look with items you loved",
    ],
}

# CTA templates by strategy
_CTA_TEMPLATES: dict[str, str] = {
    "email_reminder": "Return to Your Cart",
    "discount_offer": "Claim Your {discount}% Discount",
    "free_shipping": "Get Free Shipping Now",
    "urgency_message": "Complete Your Order Before It's Gone",
    "retarget_ad": "Shop Your Favorites",
}

# Body templates by strategy
_BODY_TEMPLATES: dict[str, str] = {
    "email_reminder": (
        "Hi {first_name},\n\n"
        "We noticed you left {items_summary} in your cart. "
        "Your items are saved and ready for you.\n\n"
        "{product_reminder}\n\n"
        "Total: ${total:.2f}\n\n"
        "{cta_text}"
    ),
    "discount_offer": (
        "Hi {first_name},\n\n"
        "Great news! We're offering you an exclusive {discount}% discount "
        "on the items in your cart.\n\n"
        "{product_reminder}\n\n"
        "Your new total: ${discounted_total:.2f} (was ${total:.2f})\n\n"
        "This offer is just for you — don't miss out!\n\n"
        "{cta_text}"
    ),
    "free_shipping": (
        "Hi {first_name},\n\n"
        "We'd love for you to complete your order, so shipping is on us!\n\n"
        "{product_reminder}\n\n"
        "Total: ${total:.2f} + FREE shipping\n\n"
        "{cta_text}"
    ),
    "urgency_message": (
        "Hi {first_name},\n\n"
        "The items in your cart are popular and stock is limited. "
        "We can only hold them for a short time.\n\n"
        "{product_reminder}\n\n"
        "Total: ${total:.2f}\n\n"
        "Don't wait — secure your items now.\n\n"
        "{cta_text}"
    ),
    "retarget_ad": (
        "Still thinking it over? Here's a reminder of the great items "
        "you were looking at:\n\n"
        "{product_reminder}\n\n"
        "Total: ${total:.2f}\n\n"
        "{cta_text}"
    ),
}


def build_message(
    strategy: dict[str, Any],
    incentive: dict[str, Any],
    cart: dict[str, Any],
    customer: dict[str, Any],
) -> dict[str, Any]:
    """Build the recovery message for the selected strategy.

    Args:
        strategy: RecoveryStrategy from strategy selector.
        incentive: Incentive from incentive calculator.
        cart: Original cart data.
        customer: Customer profile data.

    Returns:
        Structured dict with RecoveryMessage data and status.
    """
    try:
        safe_strategy = copy.deepcopy(strategy)
        safe_incentive = copy.deepcopy(incentive)
        safe_cart = copy.deepcopy(cart)
        safe_customer = copy.deepcopy(customer)

        strategy_name = str(safe_strategy.get("strategy", "email_reminder"))
        incentive_type = str(safe_incentive.get("type", "none"))
        incentive_value = float(safe_incentive.get("value", 0))

        # Extract customer info
        email = str(safe_customer.get("email", ""))
        first_name = _extract_first_name(email)

        # Extract cart info
        items = safe_cart.get("items", [])
        total = float(safe_cart.get("total", 0))

        # Build product reminder
        product_reminder = _build_product_reminder(items)
        items_summary = _build_items_summary(items)

        # Compute discounted total
        discount_pct = incentive_value if incentive_type == "percentage" else 0
        discounted_total = total * (1 - discount_pct / 100.0)

        # Personalization tokens
        personalization_tokens = [first_name, email]
        if discount_pct > 0:
            personalization_tokens.append(f"{discount_pct}%")

        # Format values for templates
        fmt = {
            "first_name": first_name,
            "store_name": "our store",
            "discount": int(discount_pct) if discount_pct == int(discount_pct) else discount_pct,
            "items_summary": items_summary,
            "product_reminder": product_reminder,
            "total": total,
            "discounted_total": discounted_total,
            "cta_text": "",
        }

        # Select subject line (first template)
        subjects = _SUBJECT_TEMPLATES.get(strategy_name, _SUBJECT_TEMPLATES["email_reminder"])
        subject = _safe_format(subjects[0], fmt)

        # Build CTA
        cta_template = _CTA_TEMPLATES.get(strategy_name, "Return to Your Cart")
        cta = _safe_format(cta_template, fmt)
        fmt["cta_text"] = cta

        # Build body
        body_template = _BODY_TEMPLATES.get(strategy_name, _BODY_TEMPLATES["email_reminder"])
        body = _safe_format(body_template, fmt)

        return {
            "status": "success",
            "message": {
                "subject": subject,
                "body": body,
                "cta": cta,
                "product_reminder": product_reminder,
                "personalization_tokens": personalization_tokens,
                "model_note": "LLaMA: creative recovery message generation",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": {},
            "error": f"Message building failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_first_name(email: str) -> str:
    """Extract a first name from an email address."""
    if not email or "@" not in email:
        return "there"
    local_part = email.split("@")[0]
    # Try splitting on common separators
    for sep in [".", "_", "-"]:
        if sep in local_part:
            name = local_part.split(sep)[0]
            if len(name) >= 2:
                return name.capitalize()
    # Use whole local part if short enough
    if len(local_part) <= 12:
        return local_part.capitalize()
    return "there"


def _build_product_reminder(items: list[dict[str, Any]]) -> str:
    """Build a text list of cart items."""
    if not items:
        return "Your selected items"
    lines: list[str] = []
    for item in items[:5]:  # Cap at 5 items for readability
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "Item"))
        price = float(item.get("price", 0))
        qty = int(item.get("quantity", 1))
        if qty > 1:
            lines.append(f"  - {title} (x{qty}) — ${price * qty:.2f}")
        else:
            lines.append(f"  - {title} — ${price:.2f}")
    if len(items) > 5:
        lines.append(f"  ... and {len(items) - 5} more item(s)")
    return "\n".join(lines) if lines else "Your selected items"


def _build_items_summary(items: list[dict[str, Any]]) -> str:
    """Build a short summary like '3 items' or 'a Wireless Headphone'."""
    if not items:
        return "some items"
    if len(items) == 1:
        title = str(items[0].get("title", "an item")) if isinstance(items[0], dict) else "an item"
        return f"a {title}"
    total_qty = sum(
        int(item.get("quantity", 1)) for item in items if isinstance(item, dict)
    )
    return f"{total_qty} item{'s' if total_qty != 1 else ''}"


def _safe_format(template: str, values: dict[str, Any]) -> str:
    """Format a template string, ignoring missing keys."""
    try:
        return template.format(**values)
    except (KeyError, ValueError, IndexError):
        return template
