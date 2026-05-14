"""Email Marketing Engine — Shopify discount-code minter.

The email_marketing engine assembles a campaign (subject lines,
body, send-time, A/B variants, audience selection) that almost
always references a discount: ``data.discount = {type, value}``.
Pre-fix that reference was a *string in the body copy only* — the
merchant had to manually mint a matching Shopify code, copy the
generated code back into the email template, and re-render before
sending.

This applier closes the loop. When the caller opts in via
``data.apply_email_campaign=True`` and the campaign carries a
non-zero discount, mint ONE multi-use storewide code matching
the campaign discount; the engine output then carries
``minted_code`` so downstream email-send tooling can substitute
the real Shopify code into the body.

Same multi-use shape as the discount_strategy minter — emails
go to many recipients so the code is multi-use, reusable per
customer, audience-scoped only by the campaign goal token.

Two opt-in modes match the established Phase 6/7 pattern:

  data.apply_email_campaign=True + data.require_approval=False
    → mint immediately
  data.apply_email_campaign=True + data.require_approval=True
    → enqueue to core.approval; merchant approves before the
      SHOPIFY_CREATE_DISCOUNT mutation lands

Skipped (no API call / no queue entry) when:
  * ``data.discount`` is missing / non-dict.
  * ``discount.value <= 0`` — no actual discount means no code
    to mint.
  * ``discount.type`` not in {percentage, fixed_amount, amount} —
    other types need different mutations.
  * The router is unavailable / adapter rejects (direct path).
  * The queue is unavailable (approval path).
"""
from __future__ import annotations

from typing import Any

from engines._recovery_codes import mint_recovery_code as _mint


_CODE_PREFIX = "EMAIL"
_DEFAULT_TTL_DAYS = 30
_PERCENTAGE_TYPES = {"percentage", "percent", "percentage_off"}
_AMOUNT_TYPES = {"fixed_amount", "amount", "dollar_off", "fixed"}


def mint_campaign_code(
    goal: str,
    discount: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mint a multi-use storewide code matching the campaign discount.

    Args:
        goal: Campaign goal string (e.g. ``"winter sale"``,
            ``"abandoned cart"``) — drives the token suffix so
            operators can identify codes by campaign.
        discount: ``{"type": "percentage"|"fixed_amount",
            "value": <numeric>}`` from the email_marketing input.
        store: Optional config carrying
            ``email_campaign_ttl_days`` (default 30).

    Returns:
        ``{"code", "discount_id", "ends_at", "applies_once"}``
        on success; ``None`` on guardrail rejection / adapter
        failure.
    """
    resolved = _resolve_discount(discount)
    if resolved is None:
        return None
    kind, value = resolved

    token = _build_token(goal)
    ttl_days = _resolve_ttl_days(store)
    suffix = "% off" if kind == "percentage" else " off"
    title = (
        f"Email campaign: {value:g}{suffix} ({goal.strip() or 'general'})"
    )

    return _mint(
        token=token,
        code_prefix=_CODE_PREFIX,
        value=value,
        value_kind=kind,
        ttl_days=ttl_days,
        title=title,
        # Multi-use storewide code — many recipients, reusable.
        usage_limit=None,
        applies_once_per_customer=False,
    )


def enqueue_campaign_for_approval(
    goal: str,
    discount: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Park the campaign-code proposal in the approval queue.

    Per-engine alternative to :func:`mint_campaign_code` —
    selected by the flow when ``data.require_approval=True``.
    Same upfront filters (non-zero discount + recognised type).
    Returns the standard
    ``{pending_action_id, narrative, params}`` shape used
    across Phase 6/7 enqueue helpers.
    """
    resolved = _resolve_discount(discount)
    if resolved is None:
        return None
    kind, value = resolved

    token = _build_token(goal)
    ttl_days = _resolve_ttl_days(store)
    suffix = "% off" if kind == "percentage" else " off"
    narrative = (
        f"Email campaign code for '{goal.strip() or 'general'}': "
        f"{value:g}{suffix} ({ttl_days}d TTL, multi-use)"
    )
    params = {
        "goal": goal.strip(),
        "token": token,
        "value": value,
        "value_kind": kind,
        "ttl_days": ttl_days,
        "code_prefix": _CODE_PREFIX,
    }

    try:
        from core.approval import get_approval_queue
        action = get_approval_queue().enqueue(
            engine="email_marketing",
            action_type="mint_campaign_code",
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


def _resolve_discount(
    discount: dict[str, Any] | None,
) -> tuple[str, float] | None:
    """Validate the engine-side discount dict, return ``(kind, value)``.

    Returns ``None`` when the discount is missing, type is
    unrecognised, or value is non-positive. The shared
    ``mint_recovery_code`` accepts ``"percentage"`` / ``"amount"``
    so we normalise both engine-side aliases here.
    """
    if not isinstance(discount, dict):
        return None
    raw_type = str(discount.get("type", "")).strip().lower()
    if not raw_type:
        return None

    if raw_type in _PERCENTAGE_TYPES:
        kind = "percentage"
    elif raw_type in _AMOUNT_TYPES:
        kind = "amount"
    else:
        return None

    try:
        value = float(discount.get("value", 0) or 0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return kind, value


def _build_token(goal: str) -> str:
    """Sanitise the goal string into an uppercase alphanum suffix."""
    if not isinstance(goal, str):
        return "EMAIL"
    cleaned = "".join(c for c in goal if c.isalnum()).upper()
    return cleaned[:12] or "EMAIL"


def _resolve_ttl_days(store: dict[str, Any] | None) -> int:
    if not isinstance(store, dict):
        return _DEFAULT_TTL_DAYS
    raw = store.get("email_campaign_ttl_days")
    if raw is None:
        return _DEFAULT_TTL_DAYS
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS
    return max(1, days)
