"""Orchestrate the review-request batch.

  1. Hydrate recent orders via SHOPIFY_FETCH_ORDERS
  2. Filter to delivered orders in the request window
  3. Skip orders already asked (via tracking module)
  4. Build per-order email payloads via templates
  5. Dispatch via SEND_EMAIL_TRANSACTIONAL (W963-8 substrate)
  6. Record each send via Pattern Z
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .templates import get_template, render
from .tracking import has_asked, mark_asked

logger = logging.getLogger(__name__)


_ENGINE = "review_request"
_ACTION_TYPE = "send_review_request"
_DEFAULT_WINDOW_DAYS = 14
_DEFAULT_LIMIT = 20


@dataclass
class ReviewRequest:
    order_id: str
    customer_email: str
    customer_name: str
    product_title: str
    subject: str
    body_html: str
    sent: bool = False
    error: str = ""


@dataclass
class BatchReport:
    eligible: int = 0
    already_asked: int = 0
    queued: int = 0
    sent: int = 0
    failed: int = 0
    requests: list[ReviewRequest] = field(default_factory=list)
    skipped_reasons: dict[str, int] = field(default_factory=dict)


def _hydrate_orders(
    limit: int, window_days: float,
) -> list[dict[str, Any]]:
    """Pull recent orders via SHOPIFY_FETCH_ORDERS."""
    try:
        from engines._shopify_hydrator import hydrate
        return hydrate(
            supplied=[],
            capability_name="SHOPIFY_FETCH_ORDERS",
            list_field="orders",
            limit=int(limit),
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "review_request: order hydrate raised: %s", exc,
        )
        return []


def _order_is_eligible(
    order: dict[str, Any], *, window_days: float, now: float,
) -> tuple[bool, str]:
    """Return (eligible, reason). Reason is empty when eligible
    and a short slug when skipped."""
    if not isinstance(order, dict):
        return False, "non_dict"
    if order.get("cancelled_at"):
        return False, "cancelled"
    # The order must be reasonably old to have been delivered.
    # Skip very-recent orders that the customer hasn't received.
    created = order.get("created_at") or ""
    if not isinstance(created, str) or not created:
        return False, "no_created_at"
    try:
        # ISO 8601 from Shopify -- tolerate Z suffix, +offset,
        # space-separator, date-only. Always produce a UTC-
        # aware datetime so .timestamp() is correct.
        from datetime import datetime, timezone
        s = created.strip().replace(" ", "T", 1)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if len(s) == 10:
            s += "T00:00:00+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        order_ts = dt.timestamp()
    except (ValueError, TypeError):
        return False, "bad_created_at"

    age_seconds = now - order_ts
    if age_seconds < (window_days * 86400):
        return False, "too_recent"
    if age_seconds > (window_days * 86400 * 3):
        # Older than 3x window -- diminishing returns.
        return False, "too_old"

    email = (order.get("customer_email") or "").strip()
    if "@" not in email:
        return False, "no_customer_email"

    return True, ""


def _build_request(
    order: dict[str, Any],
    *,
    niche: str | None,
    store_name: str | None,
    review_link_template: str | None,
) -> ReviewRequest:
    customer_email = str(order.get("customer_email") or "")
    first_name = str(
        order.get("customer_first_name") or "",
    )
    last_name = str(order.get("customer_last_name") or "")
    full_name = (first_name + " " + last_name).strip() or "there"

    # Try to surface a single product title. Shopify orders have
    # line_items; we use the first one as the focus.
    product_title = ""
    line_items = order.get("line_items") or []
    if (
        isinstance(line_items, list)
        and line_items
        and isinstance(line_items[0], dict)
    ):
        product_title = str(line_items[0].get("title") or "")
    if not product_title:
        product_title = "your recent order"

    # Build review_link by substituting the order id into the
    # operator-provided template.
    review_link = ""
    if review_link_template:
        review_link = review_link_template.format(
            order_id=order.get("id", ""),
            order_name=order.get("name", ""),
            product_title=product_title,
        )

    template = get_template(niche)
    subject, body_html = render(
        template,
        customer_name=full_name,
        product_title=product_title,
        store_name=store_name,
        review_link=review_link,
    )

    return ReviewRequest(
        order_id=str(order.get("id") or ""),
        customer_email=customer_email,
        customer_name=full_name,
        product_title=product_title,
        subject=subject,
        body_html=body_html,
    )


def _send_email(
    request: ReviewRequest,
    *,
    from_email: str | None,
) -> ReviewRequest:
    """Dispatch via SEND_EMAIL_TRANSACTIONAL. Records Pattern Z
    inside this function so callers don't need to."""
    ok = False
    err = ""
    try:
        from core.adapters.router import get_router
        from core.adapters.base import Capability
        router = get_router()
        params: dict[str, Any] = {
            "to": request.customer_email,
            "to_name": request.customer_name,
            "subject": request.subject,
            "html": request.body_html,
        }
        if from_email:
            params["from_email"] = from_email
        try:
            result = router.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL, params,
            )
            ok = bool(getattr(result, "ok", False))
            if not ok:
                err = getattr(result, "error", "") or ""
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        err = f"router unavailable: {type(exc).__name__}"

    request.sent = ok
    request.error = err

    # Pattern Z -- ALWAYS record, including the
    # router-unavailable path so attribution sees the failure.
    try:
        from engines._writeback_recorder import (
            record_writeback,
        )
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SEND_EMAIL_TRANSACTIONAL",
            params={
                "order_id": request.order_id,
                "to": request.customer_email,
            },
            success=ok,
            error=None if ok else err,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "review_request writeback raised: %s", exc,
        )

    return request


def build_batch(
    *,
    limit: int = _DEFAULT_LIMIT,
    window_days: float = _DEFAULT_WINDOW_DAYS,
    niche: str | None = None,
    store_name: str | None = None,
    review_link_template: str | None = None,
    orders: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> BatchReport:
    """Build the candidate batch without sending. Returns the
    eligible requests + per-reason skip counts."""
    if now is None:
        now = time.time()

    raw_orders = (
        orders
        if orders is not None
        else _hydrate_orders(limit=limit * 3, window_days=window_days)
    )

    report = BatchReport()
    for o in raw_orders:
        eligible, reason = _order_is_eligible(
            o, window_days=window_days, now=now,
        )
        if not eligible:
            report.skipped_reasons[reason] = (
                report.skipped_reasons.get(reason, 0) + 1
            )
            continue
        report.eligible += 1
        order_id = str(o.get("id") or "")
        if has_asked(order_id):
            report.already_asked += 1
            continue
        req = _build_request(
            o,
            niche=niche,
            store_name=store_name,
            review_link_template=review_link_template,
        )
        report.requests.append(req)
        if len(report.requests) >= limit:
            break

    report.queued = len(report.requests)
    return report


def send_batch(
    *,
    limit: int = _DEFAULT_LIMIT,
    window_days: float = _DEFAULT_WINDOW_DAYS,
    niche: str | None = None,
    store_name: str | None = None,
    review_link_template: str | None = None,
    from_email: str | None = None,
    orders: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> BatchReport:
    """Build + dispatch. Each send is wrapped in try/except so a
    bad address doesn't halt the batch."""
    report = build_batch(
        limit=limit,
        window_days=window_days,
        niche=niche,
        store_name=store_name,
        review_link_template=review_link_template,
        orders=orders,
        now=now,
    )

    for req in report.requests:
        _send_email(req, from_email=from_email)
        if req.sent:
            report.sent += 1
            mark_asked(
                order_id=req.order_id,
                customer_email=req.customer_email,
                product_title=req.product_title,
                send_status="sent",
            )
        else:
            report.failed += 1
            mark_asked(
                order_id=req.order_id,
                customer_email=req.customer_email,
                product_title=req.product_title,
                send_status="failed",
            )

    return report
