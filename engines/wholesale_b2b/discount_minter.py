"""Wholesale B2B Engine — Shopify discount-code minter.

The wholesale_b2b engine's ``volume_discounts`` output carries
per-line-item discount percentages calculated against the
merchant's pricing tiers. Pre-fix that data was advisory only:
the merchant had to manually create a Shopify discount code per
wholesale order, copy the calculated percentage from the engine
output, and email it to the wholesale account.

This applier closes the loop. It picks the BEST applicable
discount_pct from ``volume_discounts`` (the most generous tier
the order qualifies for) and mints one Shopify code per order:

  * Code prefix: ``WHOLESALE``
  * Suffix: customer token from ``order.customer_id``
  * Value kind: percentage
  * TTL: configurable via ``store.wholesale_code_ttl_days``
    (default 30)
  * One-shot redemption (single-use per order)

Two opt-in modes match the established Phase 6/7 pattern:

  data.apply_wholesale_discount=True + data.require_approval=False
    → mint immediately
  data.apply_wholesale_discount=True + data.require_approval=True
    → enqueue to core.approval; merchant approves before the
      SHOPIFY_CREATE_DISCOUNT mutation lands

Skipped (no API call / no queue entry) when:
  * The order has no items / no customer_id.
  * Every line item came back with ``discount_pct=0`` (no tier
    earned anything — minting a 0% code would be pointless).
  * The router is unavailable / adapter rejects (direct path).
  * The queue is unavailable (approval path).
"""
from __future__ import annotations

from typing import Any

from engines._recovery_codes import mint_recovery_code as _mint


_CODE_PREFIX = "WHOLESALE"
_DEFAULT_TTL_DAYS = 30


def mint_wholesale_code(
    order: dict[str, Any],
    volume_discounts: list[dict[str, Any]],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mint a one-shot wholesale discount code for the order.

    Args:
        order: Order dict — must carry ``customer_id``.
        volume_discounts: Output of ``calculate_volume_discounts``;
            best ``discount_pct`` across the list is what the code
            applies.
        store: Optional config carrying
            ``wholesale_code_ttl_days``.

    Returns:
        ``{"code", "discount_id", "ends_at", "applies_once"}``
        on success; ``None`` on guardrail rejection / adapter
        failure.
    """
    discount_pct = _best_discount(volume_discounts)
    if discount_pct is None or discount_pct <= 0:
        return None

    customer_id = str(order.get("customer_id", "")).strip()
    if not customer_id:
        return None

    token = _build_token(customer_id)
    ttl_days = _resolve_ttl_days(store)
    title = (
        f"Wholesale order discount: {discount_pct:g}% off "
        f"(customer {customer_id[:24]})"
    )

    return _mint(
        token=token,
        code_prefix=_CODE_PREFIX,
        value=discount_pct,
        value_kind="percentage",
        ttl_days=ttl_days,
        title=title,
    )


def enqueue_wholesale_for_approval(
    order: dict[str, Any],
    volume_discounts: list[dict[str, Any]],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Park the wholesale-code proposal in the approval queue.

    Per-engine alternative to :func:`mint_wholesale_code` —
    selected by the flow when ``data.require_approval=True``.
    Same upfront filters (positive ``discount_pct`` + customer_id
    present). Returns the standard
    ``{pending_action_id, narrative, params}`` shape used
    across the Phase 6/7 enqueue helpers.
    """
    discount_pct = _best_discount(volume_discounts)
    if discount_pct is None or discount_pct <= 0:
        return None

    customer_id = str(order.get("customer_id", "")).strip()
    if not customer_id:
        return None

    token = _build_token(customer_id)
    ttl_days = _resolve_ttl_days(store)
    order_total = _safe_float(order.get("total"))
    narrative = (
        f"Wholesale code for customer {customer_id}: "
        f"{discount_pct:g}% off"
        + (f" on ${order_total:g} order" if order_total else "")
        + f" ({ttl_days}d TTL)"
    )
    params = {
        "token": token,
        "value": discount_pct,
        "value_kind": "percentage",
        "ttl_days": ttl_days,
        "customer_id": customer_id,
        "code_prefix": _CODE_PREFIX,
        "order_total": order_total,
    }

    try:
        from core.approval import get_approval_queue
        action = get_approval_queue().enqueue(
            engine="wholesale_b2b",
            action_type="mint_wholesale_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params=params,
            narrative=narrative,
        )
    except Exception:  # noqa: BLE001
        return None

    return {
        "pending_action_id": action.id,
        "narrative": narrative,
        "params": params,
    }


# ── Helpers ───────────────────────────────────────────────────


def _best_discount(
    volume_discounts: list[dict[str, Any]],
) -> float | None:
    """Pick the largest ``discount_pct`` across all line items.

    Returns ``None`` when nothing applied — distinct from the
    "everything was 0%" case, which returns ``0.0`` and lets
    the caller's positive-value guard fire normally.
    """
    if not isinstance(volume_discounts, list) or not volume_discounts:
        return None
    best = 0.0
    for entry in volume_discounts:
        if not isinstance(entry, dict):
            continue
        try:
            pct = float(entry.get("discount_pct", 0) or 0)
        except (TypeError, ValueError):
            continue
        if pct > best:
            best = pct
    return best


def _build_token(customer_id: str) -> str:
    """Sanitised customer id, uppercased, alphanum-only, cap 12.

    Falls back to ``ANON`` for blanks (which never actually fire
    because the caller already gated on truthy customer_id).
    """
    if not customer_id:
        return "ANON"
    # GID like ``gid://shopify/Customer/12345`` → ``12345``
    tail = customer_id.rstrip("/").rsplit("/", 1)[-1] or customer_id
    sanitized = "".join(c for c in tail.upper() if c.isalnum())
    return sanitized[:12] or "ANON"


def _resolve_ttl_days(store: dict[str, Any] | None) -> int:
    if not isinstance(store, dict):
        return _DEFAULT_TTL_DAYS
    raw = store.get("wholesale_code_ttl_days")
    if raw is None:
        return _DEFAULT_TTL_DAYS
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS


def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
