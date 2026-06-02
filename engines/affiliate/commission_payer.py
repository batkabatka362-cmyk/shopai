"""Affiliate Engine — Shopify gift-card commission payer.

Bridges the engine's calculated ``commissions_due`` into actual
Shopify gift cards issued to each partner as commission payout.
Each commission carries
``{partner_id, name, period_sales, commission_rate,
commission_amount, tier}``; the payer joins to the ``partners``
input list (for email / customer_id lookup) and calls
``SHOPIFY_CREATE_GIFT_CARD`` with the commission_amount as the
gift card's initial value.

Why gift cards (and not external payouts): Shopify Gift Cards are
already part of the merchant's billing surface — no separate
payment processor / W-9 / 1099 setup needed for small operators.
For higher-stakes affiliate programs the merchant probably wants
ACH/PayPal; that's a different writeback for a future commit.
For now, gift-card payouts unblock the autonomous loop for the
common case.

Skipped (no API call) when:

  * ``commission_amount`` is non-positive (rare but possible
    after rounding).
  * The partner can't be located in the ``partners`` input list
    — without it we have no email / customer_id and would mint
    an unattached gift card that the merchant has no way to
    deliver.
  * The router is unavailable / the adapter call fails.

Returns per-commission results so the engine output shows what
was paid and what was skipped (with a per-skip reason).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._agi_context import (
    explain_thrash_block,
    log_thrash_block,
    should_block_thrashing_store,
)
from engines._writeback_recorder import record_writeback

logger = get_logger("engines.affiliate.payer")


# Default note prefix on the gift card so the merchant can audit
# which payouts came from this engine.
_NOTE_PREFIX = "Affiliate commission"

# Default expiry in days. Gift cards live longer than recovery
# codes / loyalty rewards because affiliates may take time to
# spend or pass the value along.
_DEFAULT_EXPIRY_DAYS = 365


def pay_commissions(
    commissions: list[dict[str, Any]],
    partners: list[dict[str, Any]],
    *,
    currency: str = "USD",
) -> list[dict[str, Any]]:
    """Issue Shopify gift cards as commission payouts.

    Args:
        commissions: ``commissions_due`` list from the engine.
            Each entry needs ``partner_id`` and ``commission_amount``.
        partners: The partners input list — used to look up
            ``email`` / ``name`` / ``customer_id`` for the gift
            card recipient.
        currency: Currency code for the gift card. Default USD.
            Match it to the merchant's storefront currency.

    Returns:
        Per-commission list with ``{partner_id, paid, amount,
        gift_card_id, code, error}``. ``paid`` is True when the
        adapter call succeeded; ``error`` is set on every skip /
        failure mode.
    """
    if not isinstance(commissions, list) or not commissions:
        return []

    partner_map = _build_partner_map(partners)

    router = _get_router()
    capability = _get_capability_create_gift_card()
    if router is None or capability is None:
        return [
            {
                "partner_id": str(c.get("partner_id", "")),
                "paid": False,
                "amount": _safe_float(c.get("commission_amount")),
                "gift_card_id": "",
                "code": "",
                "error": "router_unavailable",
            }
            for c in commissions
        ]

    # Wave 922: thrash guardrail (system-level kill switch).
    # Commission payouts mint REAL gift cards -- real money
    # out the door. Refuse during thrash; partner gets paid
    # later when the loop stabilizes.
    try:
        from core.context import get_active_store_id
        active_store_id = get_active_store_id()
    except Exception:  # noqa: BLE001
        active_store_id = None
    if should_block_thrashing_store(active_store_id):
        reason = explain_thrash_block(active_store_id)
        record_writeback(
            engine="affiliate",
            action_type="pay_commission",
            capability="SHOPIFY_CREATE_GIFT_CARD",
            params={"commission_count": len(commissions)},
            success=False,
            error=reason,
        )
        log_thrash_block(
            engine="affiliate",
            action_type="pay_commission",
            capability="SHOPIFY_CREATE_GIFT_CARD",
            store_id=active_store_id,
        )
        return [
            {
                "partner_id": str(c.get("partner_id", "")),
                "paid": False,
                "amount": _safe_float(c.get("commission_amount")),
                "gift_card_id": "",
                "code": "",
                "error": reason,
            }
            for c in commissions
        ]

    results: list[dict[str, Any]] = []
    for commission in commissions:
        if not isinstance(commission, dict):
            continue
        pid = str(commission.get("partner_id", "")).strip()
        amount = _safe_float(commission.get("commission_amount"))
        if not pid or amount is None:
            continue
        if amount <= 0:
            results.append({
                "partner_id": pid,
                "paid": False,
                "amount": amount,
                "gift_card_id": "",
                "code": "",
                "error": "non_positive_amount",
            })
            continue

        partner = partner_map.get(pid)
        if not partner:
            results.append({
                "partner_id": pid,
                "paid": False,
                "amount": amount,
                "gift_card_id": "",
                "code": "",
                "error": "partner_not_in_input",
            })
            continue

        params = _build_gift_card_params(
            commission=commission,
            partner=partner,
            currency=currency,
        )

        recorder_params = {
            "partner_id": pid,
            "amount": amount,
            "currency": currency,
        }

        try:
            result = router.execute(capability, params)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "pay_commissions raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="affiliate",
                action_type="pay_commission",
                capability="SHOPIFY_CREATE_GIFT_CARD",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "partner_id": pid,
                "paid": False,
                "amount": amount,
                "gift_card_id": "",
                "code": "",
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "pay_commissions failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="affiliate",
                action_type="pay_commission",
                capability="SHOPIFY_CREATE_GIFT_CARD",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "partner_id": pid,
                "paid": False,
                "amount": amount,
                "gift_card_id": "",
                "code": "",
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="affiliate",
            action_type="pay_commission",
            capability="SHOPIFY_CREATE_GIFT_CARD",
            params=recorder_params,
            success=True,
        )
        data = getattr(result, "data", {}) or {}
        gift_card = data.get("gift_card") or {}
        results.append({
            "partner_id": pid,
            "paid": True,
            "amount": amount,
            "gift_card_id": gift_card.get("id") or "",
            "code": data.get("code") or "",
            "error": None,
        })

    return results


def enqueue_commissions_for_approval(
    commissions: list[dict[str, Any]],
    partners: list[dict[str, Any]],
    *,
    currency: str = "USD",
) -> list[dict[str, Any]]:
    """Park commission payouts in the approval queue.

    Per-engine alternative to :func:`pay_commissions` — selected
    by the flow when ``data.require_approval=True``. Same upfront
    filters (positive amount, partner present in input). Each
    surviving commission enqueues one pending action.

    Returns the same shape as :func:`pay_commissions` plus a
    ``pending_action_id`` field on successfully-queued entries.
    Commission payouts are higher-stakes than discount minting
    (real money out the door), so the queue gating matters more
    here than for any of the other appliers.
    """
    if not isinstance(commissions, list) or not commissions:
        return []

    partner_map = _build_partner_map(partners)

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "partner_id": str(c.get("partner_id", "")),
                "paid": False,
                "amount": _safe_float(c.get("commission_amount")),
                "gift_card_id": "",
                "code": "",
                "error": "approval_queue_unavailable",
                "pending_action_id": None,
            }
            for c in commissions
        ]

    results: list[dict[str, Any]] = []
    for commission in commissions:
        if not isinstance(commission, dict):
            continue
        pid = str(commission.get("partner_id", "")).strip()
        amount = _safe_float(commission.get("commission_amount"))
        if not pid or amount is None:
            continue
        if amount <= 0:
            results.append({
                "partner_id": pid,
                "paid": False,
                "amount": amount,
                "gift_card_id": "",
                "code": "",
                "error": "non_positive_amount",
                "pending_action_id": None,
            })
            continue

        partner = partner_map.get(pid)
        if not partner:
            results.append({
                "partner_id": pid,
                "paid": False,
                "amount": amount,
                "gift_card_id": "",
                "code": "",
                "error": "partner_not_in_input",
                "pending_action_id": None,
            })
            continue

        gift_params = _build_gift_card_params(
            commission=commission,
            partner=partner,
            currency=currency,
        )
        partner_name = (
            partner.get("name") or commission.get("name") or pid
        )
        narrative = (
            f"Pay ${amount:.2f} {currency} to {partner_name} "
            f"(period sales: ${commission.get('period_sales', 0)} × "
            f"{commission.get('commission_rate', 0)}%) "
            f"as Shopify gift card"
        )

        try:
            action = queue.enqueue(
                engine="affiliate",
                action_type="pay_commission",
                capability="SHOPIFY_CREATE_GIFT_CARD",
                params=gift_params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "enqueue raised for %s: %s", pid, exc,
            )
            results.append({
                "partner_id": pid,
                "paid": False,
                "amount": amount,
                "gift_card_id": "",
                "code": "",
                "error": f"enqueue_raised: {exc}",
                "pending_action_id": None,
            })
            continue

        results.append({
            "partner_id": pid,
            "paid": False,
            "amount": amount,
            "gift_card_id": "",
            "code": "",
            "error": "queued",
            "pending_action_id": action.id,
        })

    return results


# ── Helpers ────────────────────────────────────────────────────


def _build_partner_map(
    partners: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index the partners list by ``id`` / ``partner_id``."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(partners, list):
        return out
    for p in partners:
        if not isinstance(p, dict):
            continue
        # Accept either ``id`` or ``partner_id`` as the key —
        # different engines / fixtures use different conventions.
        pid = (
            str(p.get("id", "")).strip()
            or str(p.get("partner_id", "")).strip()
        )
        if pid:
            out[pid] = p
    return out


def _build_gift_card_params(
    *,
    commission: dict[str, Any],
    partner: dict[str, Any],
    currency: str,
) -> dict[str, Any]:
    """Build the SHOPIFY_CREATE_GIFT_CARD friendly call shape."""
    # W962-71: use Decimal for the gift-card face value to
    # avoid IEEE-754 binary drift on commission_amount =
    # revenue * rate. Float ops upstream may have introduced
    # tiny artifacts (e.g. 0.1+0.2 = 0.300000000000000004);
    # quantizing in Decimal with ROUND_HALF_UP produces the
    # cent value a human accountant expects.
    from decimal import Decimal, ROUND_HALF_UP
    raw_amount = commission.get("commission_amount", 0.0)
    try:
        amount_dec = Decimal(str(raw_amount)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
    except (ValueError, ArithmeticError):
        amount_dec = Decimal("0.00")
    amount = float(amount_dec)
    period_sales = commission.get("period_sales", 0.0)

    params: dict[str, Any] = {
        "initial_value": amount,
        "currency": currency,
        "note": (
            f"{_NOTE_PREFIX}: ${period_sales} in sales × "
            f"{commission.get('commission_rate', 0)}%"
        ),
    }

    # Optional recipient fields — included only when the partner
    # carries them. The adapter accepts missing fields silently.
    email = partner.get("email")
    if isinstance(email, str) and email.strip():
        params["recipient_email"] = email.strip()

    name = partner.get("name") or commission.get("name")
    if isinstance(name, str) and name.strip():
        params["recipient_name"] = name.strip()

    customer_id = (
        partner.get("customer_id")
        or partner.get("shopify_customer_id")
    )
    if isinstance(customer_id, str) and customer_id.strip():
        params["customer_id"] = customer_id.strip()

    return params


def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("router import failed: %s", exc)
        return None
    try:
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("router init failed: %s", exc)
        return None


def _get_capability_create_gift_card() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_CREATE_GIFT_CARD
