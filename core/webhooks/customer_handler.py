"""customers/create webhook → welcome email flow enrol.

Shopify fires ``customers/create`` when:
  * A guest buyer's first order creates a Customer record
  * A storefront sign-up form (email list opt-in) submits
  * Admin manually creates a customer

Only the email-list signup case matches the semantic "welcome
flow needed" — buyers with an order already in flight will be
caught by the ``post_purchase`` trigger on
``order_handler.handle_order_paid``, and sending both would
double-up on the same person.

Filter rule: enroll ONLY when ``orders_count == 0`` on the
customer payload. Shopify populates this field before the
webhook fires.

Idempotency: the email engine's ``(recipient × flow ×
step_id)`` unique key dedupes repeat enrolments, so repeated
webhooks (retry storm, customer re-subscribing) stay a no-op.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_logger = logging.getLogger("shopai.webhooks.customer_handler")


def _extract_email(payload: dict[str, Any]) -> str:
    for key in ("email", "contact_email"):
        v = payload.get(key)
        if v:
            return str(v).strip().lower()
    return ""


def _extract_first_name(
    payload: dict[str, Any], email: str,
) -> str:
    fn = payload.get("first_name")
    if fn:
        return str(fn)
    addresses = payload.get("addresses") or []
    if isinstance(addresses, list):
        for addr in addresses:
            if not isinstance(addr, dict):
                continue
            fn = addr.get("first_name")
            if fn:
                return str(fn)
    if email:
        local = email.split("@", 1)[0] or ""
        return (local.replace(".", " ").title()
                or "there")
    return "there"


def _accepts_marketing(payload: dict[str, Any]) -> bool:
    """Respect Shopify's marketing opt-in signal. Different
    API versions encode this differently; check all."""
    if payload.get("accepts_marketing") is True:
        return True
    if payload.get("accepts_marketing") is False:
        return False
    # 2024+ API — email_marketing_consent.state == "subscribed"
    consent = payload.get("email_marketing_consent") or {}
    if isinstance(consent, dict):
        state = str(consent.get("state") or "").lower()
        if state == "subscribed":
            return True
        if state in ("unsubscribed", "not_subscribed"):
            return False
    # Default policy — if Shopify doesn't mark explicit opt-in,
    # we still enrol. GDPR / CAN-SPAM compliance is the
    # owner's storefront's job; our flow engine respects the
    # per-recipient unsubscribe list separately.
    return True


def handle_customer_create(
    payload: dict[str, Any],
    *,
    email_engine: Any = None,
) -> dict[str, Any]:
    """Process a ``customers/create`` webhook.

    Enrol in the ``welcome`` flow when:
      * payload is a valid customer dict
      * orders_count is 0 (first contact, not post-purchase)
      * email is present
      * customer accepts marketing (Shopify signal)

    Returns a dict summary. ``email_engine`` injectable for
    tests."""
    if not isinstance(payload, dict):
        payload = {}

    result: dict[str, Any] = {
        "customer_id": str(payload.get("id") or ""),
        "enrolled": False,
        "skipped_reason": "",
    }

    # Skip if customer already has orders — post_purchase owns
    # this journey.
    try:
        orders_count = int(payload.get("orders_count", 0) or 0)
    except (TypeError, ValueError):
        orders_count = 0
    if orders_count > 0:
        result["skipped_reason"] = (
            "customer has orders — post_purchase flow owns"
        )
        return result

    email = _extract_email(payload)
    if not email or "@" not in email:
        result["skipped_reason"] = "no email on customer"
        return result

    if not _accepts_marketing(payload):
        result["skipped_reason"] = (
            "customer not subscribed to marketing"
        )
        return result

    first_name = _extract_first_name(payload, email)

    store_host = (
        os.environ.get("SHOPAI_SHOPIFY_URL") or ""
    ).strip()
    store_url = store_host
    if store_url and not store_url.startswith("http"):
        store_url = f"https://{store_url}"
    store_name = os.environ.get(
        "SHOPAI_STORE_NAME", "Deguar",
    )
    discount_code = os.environ.get(
        "SHOPAI_EMAIL_WELCOME_CODE", "WELCOME15",
    )
    # top_products is an owner-curated env so we don't do
    # another Shopify API call per webhook. Owner sets
    # SHOPAI_EMAIL_TOP_PRODUCTS="• Galaxy Projector\n•
    # Moon Lamp" ahead of time; empty fallback is clean.
    top_products = os.environ.get(
        "SHOPAI_EMAIL_TOP_PRODUCTS",
        f"Browse our best sellers at {store_url}"
        if store_url else "Browse our best sellers online",
    )

    if email_engine is None:
        try:
            from core.engines.email_campaigns import (
                get_engine as _ec,
            )
            email_engine = _ec()
        except Exception as exc:  # noqa: BLE001
            _logger.debug(
                "email_campaigns import failed: %s", exc,
            )
            result["skipped_reason"] = "engine unavailable"
            return result

    try:
        enroll_result = email_engine.enroll(
            email, flow="welcome",
            context={
                "first_name": first_name,
                "store_name": store_name,
                "store_url": store_url,
                "discount_code": discount_code,
                "top_products": top_products,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _logger.debug(
            "welcome enroll failed for %s: %s", email, exc,
        )
        result["skipped_reason"] = f"enroll error: {exc}"
        return result

    if enroll_result.get("unsubscribed"):
        result["skipped_reason"] = "recipient unsubscribed"
        return result

    result["enrolled"] = enroll_result.get("enrolled", 0) > 0
    result["newly_enrolled_steps"] = enroll_result.get(
        "enrolled", 0,
    )
    result["already_enrolled_steps"] = enroll_result.get(
        "skipped", 0,
    )
    result["email"] = email
    return result
