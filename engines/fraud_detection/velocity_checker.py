"""Fraud Detection Engine — velocity checker.

Counts recent orders from the same email, IP, or address within
1-hour, 24-hour, and 7-day windows. Flags abnormal velocity.

Thresholds:
  - >3 orders in 1 h   → high velocity
  - >10 orders in 24 h → high velocity
  - >30 orders in 7 d  → high velocity
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any


def check_velocity(
    order: dict[str, Any],
    past_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check order velocity for the same identifiers.

    Args:
        order: Current order dict (must have email, ip_address, shipping_address).
        past_orders: Historical order records with timestamp, email, ip_address.

    Returns:
        Structured dict with velocity counts, score, and optional flag.
    """
    try:
        order = copy.deepcopy(order)
        past_orders = copy.deepcopy(past_orders)

        email = str(order.get("email", "")).lower().strip()
        ip = str(order.get("ip_address", "")).strip()
        shipping = order.get("shipping_address", {})
        addr_key = _address_key(shipping)

        now = _parse_timestamp(order.get("created_at", ""))

        orders_1h = 0
        orders_24h = 0
        orders_7d = 0

        for past in past_orders:
            if not _identifiers_match(past, email, ip, addr_key):
                continue

            ts = _parse_timestamp(past.get("created_at", past.get("timestamp", "")))
            if ts is None:
                continue

            delta_seconds = (now - ts).total_seconds()
            if delta_seconds < 0:
                continue

            if delta_seconds <= 3600:
                orders_1h += 1
            if delta_seconds <= 86400:
                orders_24h += 1
            if delta_seconds <= 604800:
                orders_7d += 1

        # ---- Score calculation ----
        flag: str | None = None
        sub_scores: list[float] = []

        # 1h window
        if orders_1h > 3:
            sub_scores.append(0.9)
            flag = "extreme_velocity_1h"
        elif orders_1h >= 2:
            sub_scores.append(0.6)
            flag = flag or "high_velocity_1h"
        else:
            sub_scores.append(0.0)

        # 24h window
        if orders_24h > 10:
            sub_scores.append(0.9)
            flag = flag or "extreme_velocity_24h"
        elif orders_24h >= 5:
            sub_scores.append(0.5)
            flag = flag or "elevated_velocity_24h"
        else:
            sub_scores.append(0.0)

        # 7d window
        if orders_7d > 30:
            sub_scores.append(0.8)
            flag = flag or "extreme_velocity_7d"
        elif orders_7d >= 15:
            sub_scores.append(0.4)
            flag = flag or "elevated_velocity_7d"
        else:
            sub_scores.append(0.0)

        score = round(max(sub_scores) * 0.6 + (sum(sub_scores) / len(sub_scores)) * 0.4, 4)
        score = max(0.0, min(1.0, score))

        return {
            "status": "success",
            "score": score,
            "orders_1h": orders_1h,
            "orders_24h": orders_24h,
            "orders_7d": orders_7d,
            "flag": flag,
        }
    except Exception as exc:
        return _fail(f"Velocity check failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _address_key(addr: dict[str, Any]) -> str:
    """Produce a normalized key from an address dict."""
    parts = [
        str(addr.get("line1", "")).lower().strip(),
        str(addr.get("zip", "")).strip(),
        str(addr.get("country", "")).upper().strip(),
    ]
    return "|".join(parts)


def _identifiers_match(
    past: dict[str, Any],
    email: str,
    ip: str,
    addr_key: str,
) -> bool:
    """Return True if any identifier overlaps."""
    past_email = str(past.get("email", "")).lower().strip()
    past_ip = str(past.get("ip_address", "")).strip()
    past_addr = _address_key(past.get("shipping_address", past.get("address", {})))

    if email and past_email == email:
        return True
    if ip and past_ip == ip:
        return True
    if addr_key and past_addr == addr_key:
        return True
    return False


def _parse_timestamp(ts: str | Any) -> datetime:
    """Parse an ISO-ish timestamp; fall back to now."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return datetime.now(timezone.utc)
    raw = str(ts).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "score": 0.0,
        "orders_1h": 0,
        "orders_24h": 0,
        "orders_7d": 0,
        "flag": None,
        "error": reason,
    }
