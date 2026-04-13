"""Fraud Detection Engine — velocity checker.

Counts orders by the same email, IP address, and shipping address across
1-hour, 24-hour, and 7-day time windows. Flags abnormal velocity that may
indicate automated fraud, card testing, or account takeover.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Velocity thresholds
# ---------------------------------------------------------------------------

_THRESH_1H = 3    # max orders in 1 hour before flagging
_THRESH_24H = 10  # max orders in 24 hours
_THRESH_7D = 30   # max orders in 7 days


def check_velocity(
    order: dict[str, Any],
    past_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check order velocity across multiple time windows.

    Args:
        order: Current order dict.
        past_orders: List of historical order dicts with 'created_at' timestamps.

    Returns:
        Structured dict with velocity counts, score, and optional flag.
    """
    try:
        order = copy.deepcopy(order)
        past_orders = copy.deepcopy(past_orders)

        email = str(order.get("email", "")).lower().strip()
        ip_address = str(order.get("ip_address", "")).strip()
        shipping = order.get("shipping_address", {})
        ship_key = _address_key(shipping)

        now = _parse_timestamp(order.get("created_at", ""))

        # Count matches in each time window
        counts_1h = {"email": 0, "ip": 0, "address": 0}
        counts_24h = {"email": 0, "ip": 0, "address": 0}
        counts_7d = {"email": 0, "ip": 0, "address": 0}

        window_1h = now - timedelta(hours=1)
        window_24h = now - timedelta(hours=24)
        window_7d = now - timedelta(days=7)

        for past in past_orders:
            ts = _parse_timestamp(past.get("created_at", ""))
            if ts > now:
                continue

            past_email = str(past.get("email", "")).lower().strip()
            past_ip = str(past.get("ip_address", "")).strip()
            past_ship = past.get("shipping_address", {})
            past_ship_key = _address_key(past_ship)

            email_match = email and past_email == email
            ip_match = ip_address and past_ip == ip_address
            addr_match = ship_key and past_ship_key == ship_key

            if ts >= window_1h:
                if email_match:
                    counts_1h["email"] += 1
                if ip_match:
                    counts_1h["ip"] += 1
                if addr_match:
                    counts_1h["address"] += 1

            if ts >= window_24h:
                if email_match:
                    counts_24h["email"] += 1
                if ip_match:
                    counts_24h["ip"] += 1
                if addr_match:
                    counts_24h["address"] += 1

            if ts >= window_7d:
                if email_match:
                    counts_7d["email"] += 1
                if ip_match:
                    counts_7d["ip"] += 1
                if addr_match:
                    counts_7d["address"] += 1

        # Aggregate: take the max across identifiers for each window
        orders_1h = max(counts_1h["email"], counts_1h["ip"], counts_1h["address"])
        orders_24h = max(counts_24h["email"], counts_24h["ip"], counts_24h["address"])
        orders_7d = max(counts_7d["email"], counts_7d["ip"], counts_7d["address"])

        # Determine flag
        flag: str | None = None
        if orders_1h > _THRESH_1H:
            flag = f"high_velocity_1h: {orders_1h} orders in 1 hour"
        elif orders_24h > _THRESH_24H:
            flag = f"high_velocity_24h: {orders_24h} orders in 24 hours"
        elif orders_7d > _THRESH_7D:
            flag = f"high_velocity_7d: {orders_7d} orders in 7 days"

        # Score: combine window violations with diminishing contribution
        score_1h = min(orders_1h / _THRESH_1H, 1.0) * 0.5
        score_24h = min(orders_24h / _THRESH_24H, 1.0) * 0.3
        score_7d = min(orders_7d / _THRESH_7D, 1.0) * 0.2

        score = round(min(score_1h + score_24h + score_7d, 1.0), 4)

        return {
            "status": "success",
            "score": score,
            "orders_1h": orders_1h,
            "orders_24h": orders_24h,
            "orders_7d": orders_7d,
            "flag": flag,
        }
    except Exception as exc:
        return {
            "status": "error",
            "score": 0.0,
            "orders_1h": 0,
            "orders_24h": 0,
            "orders_7d": 0,
            "flag": None,
            "error": f"Velocity check failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _address_key(address: dict[str, Any]) -> str:
    """Create a normalized key for address comparison."""
    parts = [
        str(address.get("line1", "")).lower().strip(),
        str(address.get("city", "")).lower().strip(),
        str(address.get("state", "")).lower().strip(),
        str(address.get("zip", "")).strip(),
        str(address.get("country", "")).upper().strip(),
    ]
    return "|".join(parts)


def _parse_timestamp(ts: Any) -> datetime:
    """Parse an ISO-format timestamp or return current UTC time."""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    if isinstance(ts, str) and ts:
        for fmt in (
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(ts, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
    return datetime.now(timezone.utc)
