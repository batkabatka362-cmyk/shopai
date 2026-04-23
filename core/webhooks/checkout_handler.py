"""Abandoned-cart webhook handler.

Shopify fires ``checkouts/create`` when a buyer lands on the
checkout page + ``checkouts/update`` on any mutation (email
entry, shipping address, line-item change). We enroll in the
``abandoned_cart`` email flow on every update that:

  * has an email address on the checkout (buyer got past the
    first step)
  * has at least one line item (cart isn't empty)
  * has NOT converted yet (no ``order_id`` / completed_at)

The flow's built-in timing (1h reminder → 1d discount) does
the waiting — we don't need to detect abandonment ourselves.
Shopify's engine idempotency (recipient × flow × step_id) keeps
repeated updates from duplicating sends.

When the buyer DOES convert, ``order_handler.handle_order_paid``
calls ``email_engine.cancel_flow(email, "abandoned_cart")`` so
the scheduled reminders get cancelled before they fire.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_logger = logging.getLogger("shopai.webhooks.checkout_handler")


def _is_completed(payload: dict[str, Any]) -> bool:
    """Return True if this checkout has already converted to
    an order — skip enrollment so we don't spam someone who
    just bought."""
    if payload.get("order_id"):
        return True
    if payload.get("completed_at"):
        return True
    # Some Shopify versions send "status": "completed"
    if str(payload.get("status") or "").lower() == "completed":
        return True
    return False


def _extract_email(payload: dict[str, Any]) -> str:
    """Shopify puts the email at different depths depending on
    which endpoint generated the payload. Check in order of
    priority."""
    for key in ("email", "contact_email"):
        v = payload.get(key)
        if v:
            return str(v).strip().lower()
    customer = payload.get("customer") or {}
    if isinstance(customer, dict):
        v = customer.get("email")
        if v:
            return str(v).strip().lower()
    return ""


def _extract_first_name(
    payload: dict[str, Any], email: str,
) -> str:
    """Derive a greeting name from checkout payload. Falls
    back to email local-part, then "there"."""
    customer = payload.get("customer") or {}
    if isinstance(customer, dict):
        fn = customer.get("first_name")
        if fn:
            return str(fn)
    # shipping_address carries first_name for guest checkouts
    shipping = payload.get("shipping_address") or {}
    if isinstance(shipping, dict):
        fn = shipping.get("first_name")
        if fn:
            return str(fn)
    if email:
        local = email.split("@", 1)[0] or ""
        return (local.replace(".", " ").title()
                or "there")
    return "there"


def _extract_item_name(payload: dict[str, Any]) -> str:
    """First line item title — what we reference in the
    reminder email's ``{item_name}`` tag."""
    items = payload.get("line_items") or []
    if not isinstance(items, list) or not items:
        return ""
    first = items[0] if isinstance(items[0], dict) else {}
    return str(
        first.get("title")
        or first.get("name")
        or first.get("variant_title")
        or "",
    )


def _build_cart_url(
    payload: dict[str, Any], store_host: str,
) -> str:
    """Shopify attaches ``abandoned_checkout_url`` to the
    payload for both checkouts/update + checkouts/create.
    Fall back to a store root URL if absent (owner still sees
    the reminder, just without a direct link)."""
    url = payload.get("abandoned_checkout_url")
    if url:
        return str(url)
    # Some older payloads use "recovery_url"
    url = payload.get("recovery_url")
    if url:
        return str(url)
    if store_host:
        if not store_host.startswith("http"):
            return f"https://{store_host}/cart"
        return f"{store_host}/cart"
    return ""


def handle_checkout_update(
    payload: dict[str, Any],
    *,
    email_engine: Any = None,
) -> dict[str, Any]:
    """Enroll the buyer into the ``abandoned_cart`` flow when
    the checkout has enough data + isn't yet converted.

    Returns a summary dict with ``enrolled`` (bool) + counts.
    ``email_engine`` injectable for tests; production callers
    pass None to use the module-level singleton.
    """
    if not isinstance(payload, dict):
        payload = {}

    result: dict[str, Any] = {
        "checkout_id": str(payload.get("id") or ""),
        "enrolled": False,
        "skipped_reason": "",
    }

    if _is_completed(payload):
        result["skipped_reason"] = "checkout already converted"
        return result

    email = _extract_email(payload)
    if not email or "@" not in email:
        result["skipped_reason"] = "no email on checkout yet"
        return result

    items = payload.get("line_items") or []
    if not isinstance(items, list) or not items:
        result["skipped_reason"] = "empty cart"
        return result

    first_name = _extract_first_name(payload, email)
    item_name = _extract_item_name(payload) or "your item"
    store_host = (
        os.environ.get("SHOPAI_SHOPIFY_URL") or ""
    ).strip()
    cart_url = _build_cart_url(payload, store_host)
    discount_code = str(
        os.environ.get("SHOPAI_EMAIL_CART_CODE")
        or "SAVE10",
    )

    # Lazy import — keeps webhook path importable even if the
    # engine package isn't available (reduced-dep deploys).
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
            email, flow="abandoned_cart",
            context={
                "first_name": first_name,
                "item_name": item_name,
                "cart_url": cart_url,
                "discount_code": discount_code,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _logger.debug(
            "abandoned_cart enroll failed for %s: %s",
            email, exc,
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
