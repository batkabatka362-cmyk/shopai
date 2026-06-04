"""Orchestrate the welcome-series batch.

  1. Hydrate recent customers via SHOPIFY_FETCH_CUSTOMERS
  2. For each: compute the next stage based on tracking
  3. Skip customers whose cadence isn't due yet (T+0 / T+48h /
     T+5d gates)
  4. Build per-customer email via templates
  5. Dispatch via SEND_EMAIL_TRANSACTIONAL
  6. Record outcome via tracking + Pattern Z
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .templates import get_stage, render
from .tracking import has_completed, mark_sent, next_stage, stages_sent

logger = logging.getLogger(__name__)


_ENGINE = "welcome_series"
_ACTION_TYPE = "send_welcome_email"
_DEFAULT_LIMIT = 20
_STAGE_GATE_HOURS = {
    1: 0.0,    # send immediately on first encounter
    2: 48.0,   # 48 hours after registration
    3: 120.0,  # 5 days after registration
}


@dataclass
class WelcomeRequest:
    customer_id: str
    customer_email: str
    customer_name: str
    stage: int
    subject: str
    body_html: str
    sent: bool = False
    error: str = ""


@dataclass
class WelcomeBatchReport:
    eligible: int = 0
    already_completed: int = 0
    not_due_yet: int = 0
    queued: int = 0
    sent: int = 0
    failed: int = 0
    requests: list[WelcomeRequest] = field(default_factory=list)
    skipped_reasons: dict[str, int] = field(default_factory=dict)


def _hydrate_customers(limit: int) -> list[dict[str, Any]]:
    """Pull recent customers via SHOPIFY_FETCH_CUSTOMERS."""
    try:
        from engines._shopify_hydrator import hydrate
        return hydrate(
            supplied=[],
            capability_name="SHOPIFY_FETCH_CUSTOMERS",
            list_field="customers",
            limit=int(limit),
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "welcome_series: customer hydrate raised: %s", exc,
        )
        return []


def _parse_created(created_at: str) -> float | None:
    """Parse a Shopify created_at ISO string -> unix seconds.

    Tolerates: 'Z' suffix, '+' offset, space separator instead
    of 'T', date-only ('2026-06-04'). Always produces a UTC-
    aware datetime so .timestamp() is timezone-correct."""
    if not isinstance(created_at, str) or not created_at:
        return None
    s = created_at.strip()
    if not s:
        return None
    try:
        s = s.replace(" ", "T", 1)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if len(s) == 10:
            s += "T00:00:00+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _eligible(
    customer: dict[str, Any],
    *,
    now: float,
) -> tuple[bool, str, int | None]:
    """Return (eligible, reason, stage). reason is the skip
    slug when not eligible. stage is the next stage to send
    when eligible."""
    if not isinstance(customer, dict):
        return False, "non_dict", None
    cid = str(customer.get("id") or "")
    if not cid:
        return False, "no_customer_id", None
    email = (customer.get("email") or "").strip()
    if "@" not in email:
        return False, "no_email", None

    if has_completed(cid):
        return False, "already_completed", None

    stage = next_stage(cid)
    if stage is None:
        return False, "already_completed", None

    # Check cadence gate. Stage 1 fires immediately (gate=0)
    # so a missing/malformed created_at is fine for stage 1.
    # For stages 2-3 we MUST know created_at — without it we
    # can't tell whether 48h/120h has elapsed, so we fail
    # closed (skip rather than risk firing the whole series
    # in a single cron run).
    created_at = customer.get("created_at") or ""
    created_ts = _parse_created(created_at)
    gate = _STAGE_GATE_HOURS.get(stage, 0.0)
    if created_ts is None:
        if gate > 0.0:
            return False, "bad_created_at", stage
        return True, "", stage
    elapsed_hours = (now - created_ts) / 3600.0
    if elapsed_hours < gate:
        return False, "not_due_yet", stage
    return True, "", stage


def _build_request(
    customer: dict[str, Any],
    *,
    stage: int,
    store_name: str | None,
    discount_code: str | None,
    shop_url: str | None,
) -> WelcomeRequest:
    cid = str(customer.get("id") or "")
    email = str(customer.get("email") or "")
    first = str(customer.get("first_name") or "")
    last = str(customer.get("last_name") or "")
    full_name = (first + " " + last).strip() or "there"

    template = get_stage(stage)
    subject, body_html = render(
        template,
        customer_name=full_name,
        store_name=store_name,
        discount_code=discount_code,
        shop_url=shop_url,
    )

    return WelcomeRequest(
        customer_id=cid,
        customer_email=email,
        customer_name=full_name,
        stage=stage,
        subject=subject,
        body_html=body_html,
    )


def _send_email(
    request: WelcomeRequest,
    *,
    from_email: str | None,
) -> WelcomeRequest:
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

    # Pattern Z -- ALWAYS record, including router-unavailable
    # path so attribution sees the failure.
    try:
        from engines._writeback_recorder import (
            record_writeback,
        )
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SEND_EMAIL_TRANSACTIONAL",
            params={
                "customer_id": request.customer_id,
                "stage": request.stage,
                "to": request.customer_email,
            },
            success=ok,
            error=None if ok else err,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "welcome_series writeback raised: %s", exc,
        )

    return request


def build_batch(
    *,
    limit: int = _DEFAULT_LIMIT,
    store_name: str | None = None,
    discount_code: str | None = None,
    shop_url: str | None = None,
    customers: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> WelcomeBatchReport:
    """Build the candidate batch without sending."""
    if now is None:
        now = time.time()
    raw = (
        customers
        if customers is not None
        else _hydrate_customers(limit=limit * 3)
    )

    report = WelcomeBatchReport()
    for c in raw:
        ok, reason, stage = _eligible(c, now=now)
        if not ok:
            if reason == "already_completed":
                report.already_completed += 1
            elif reason == "not_due_yet":
                report.not_due_yet += 1
            else:
                report.skipped_reasons[reason] = (
                    report.skipped_reasons.get(reason, 0) + 1
                )
            continue
        report.eligible += 1
        if stage is None:
            continue
        req = _build_request(
            c,
            stage=stage,
            store_name=store_name,
            discount_code=discount_code,
            shop_url=shop_url,
        )
        report.requests.append(req)
        if len(report.requests) >= limit:
            break

    report.queued = len(report.requests)
    return report


def send_batch(
    *,
    limit: int = _DEFAULT_LIMIT,
    store_name: str | None = None,
    discount_code: str | None = None,
    shop_url: str | None = None,
    from_email: str | None = None,
    customers: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> WelcomeBatchReport:
    """Build + dispatch."""
    report = build_batch(
        limit=limit,
        store_name=store_name,
        discount_code=discount_code,
        shop_url=shop_url,
        customers=customers,
        now=now,
    )
    for req in report.requests:
        _send_email(req, from_email=from_email)
        if req.sent:
            report.sent += 1
            mark_sent(
                customer_id=req.customer_id,
                stage=req.stage,
                status="sent",
            )
        else:
            report.failed += 1
            mark_sent(
                customer_id=req.customer_id,
                stage=req.stage,
                status="failed",
            )
    return report


def stages_sent_export(customer_id: str) -> list[int]:
    """Pass-through for tests + flow consumers."""
    return stages_sent(customer_id)
