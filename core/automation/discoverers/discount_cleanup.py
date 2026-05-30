"""Discoverer for the discount_cleanup autonomy domain (W830).

Walks active discount codes from Shopify, surfaces stale /
unused ones, emits ``deactivate`` payloads. The applier
deactivates codes via SHOPIFY_DEACTIVATE_CODE_DISCOUNT
behind 6 safety gates (status, age, per-run cap, etc.).

Per-row payload: ``{discount_id, code, store_id, action,
age_days, reason}``. The applier re-checks age + cap so the
discoverer's threshold is just the initial filter.

Default: surface codes that are >= 30 days old AND have 0
usage in the last 30 days. Both knobs env-overridable.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from core.automation.payload_discoverer import (
    DiscoveryResult,
    register_discoverer,
)

logger = logging.getLogger(__name__)

_DOMAIN = "discount_cleanup"
_DEFAULT_LIMIT = 100
_DEFAULT_MIN_AGE_DAYS = 30


def _limit(store_id: str | None = None) -> int:
    """W882: per-store override via
    SHOPAI_DISCOUNT_CLEANUP_DISCOVER_LIMIT_<STORE>."""
    from core.automation.discoverer_env import resolve_int
    return resolve_int(
        _DOMAIN, "LIMIT",
        default=_DEFAULT_LIMIT,
        store_id=store_id,
        min_value=1,
    )


def _min_age_days(store_id: str | None = None) -> int:
    """W888: standardised naming with legacy back-compat.

    New: SHOPAI_DISCOUNT_CLEANUP_DISCOVER_MIN_AGE_DAYS[_<STORE>]
    Legacy: SHOPAI_DISCOUNT_CLEANUP_MIN_AGE_DAYS[_<STORE>]"""
    from core.automation.discoverer_env import resolve_int
    return resolve_int(
        _DOMAIN, "MIN_AGE_DAYS",
        default=_DEFAULT_MIN_AGE_DAYS,
        store_id=store_id,
        min_value=0,
        legacy_env=(
            "SHOPAI_DISCOUNT_CLEANUP_MIN_AGE_DAYS"
        ),
    )


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(
            str(ts).replace("Z", "+00:00"),
        )
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _classify_discount(
    disc: dict[str, Any], min_age: int,
) -> tuple[str, int] | None:
    """Return (reason, age_days) for a discount that should be
    cleaned up, or None to skip."""
    if not isinstance(disc, dict):
        return None
    # Skip if already inactive
    status = str(disc.get("status") or "").lower()
    if status in ("expired", "inactive", "deactivated"):
        return None

    created = _parse_iso(
        disc.get("created_at") or "",
    )
    if created is None:
        return None
    age_days = int(
        (
            datetime.now(timezone.utc) - created
        ).total_seconds() / 86400.0
    )
    if age_days < min_age:
        return None

    # Prefer unused first
    try:
        usage = int(disc.get("usage_count") or 0)
    except (TypeError, ValueError):
        usage = 0
    if usage == 0:
        return (f"unused for {age_days}d", age_days)

    # Check expiration in the past
    ends_at = _parse_iso(
        disc.get("ends_at") or disc.get("expires_at") or "",
    )
    if ends_at is not None and ends_at < datetime.now(
        timezone.utc,
    ):
        return (f"expired {age_days}d ago", age_days)

    return None


def _fetch_discounts(
    store_id: str | None = None,
) -> list[dict[str, Any]]:
    try:
        from core.adapters.router import get_router  # noqa
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discount_cleanup discoverer: router import "
            "raised: %s", exc,
        )
        return []
    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discount_cleanup discoverer: router unavail: %s",
            exc,
        )
        return []
    cap = getattr(
        Capability, "SHOPIFY_LIST_CODE_DISCOUNTS", None,
    )
    if cap is None:
        # Try fallback names some adapters use
        cap = getattr(Capability, "SHOPIFY_LIST_DISCOUNTS", None)
    if cap is None:
        return []
    try:
        res = router.execute(cap, {"limit": _limit(store_id)})
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discount_cleanup discoverer: execute raised: %s",
            exc,
        )
        return []
    if not getattr(res, "ok", False):
        return []
    data = getattr(res, "data", None) or {}
    if not isinstance(data, dict):
        return []
    discounts = (
        data.get("discounts") or data.get("codes")
        or data.get("price_rules") or []
    )
    if not isinstance(discounts, list):
        return []
    return discounts


def discover_discount_cleanup(*, store_id: str | None = None) -> DiscoveryResult:
    now = time.time()
    try:
        discounts = _fetch_discounts(store_id=store_id)
    except Exception as exc:  # noqa: BLE001
        return DiscoveryResult(
            domain=_DOMAIN,
            payload=[],
            source="shopify_discounts",
            discovered_at=now,
            store_id=store_id,
            error=f"fetch raised: {exc!s:.200}",
        )
    min_age = _min_age_days(store_id)
    payload: list[dict] = []
    for d in discounts:
        if not isinstance(d, dict):
            continue
        verdict = _classify_discount(d, min_age)
        if verdict is None:
            continue
        reason, age_days = verdict
        did = str(d.get("id") or d.get("gid") or "").strip()
        code = str(d.get("code") or d.get("title") or "").strip()
        if not did or not code:
            continue
        sid = str(d.get("store_id") or "").strip()
        payload.append({
            "discount_id": did,
            "code": code,
            "store_id": sid,
            "action": "deactivate",
            "age_days": age_days,
            "reason": reason,
            "signal_source": "discount_cleanup_discoverer",
        })
    return DiscoveryResult(
        domain=_DOMAIN,
        payload=payload,
        source="shopify_discounts",
        discovered_at=now,
            store_id=store_id,
    )


register_discoverer(_DOMAIN, discover_discount_cleanup)
