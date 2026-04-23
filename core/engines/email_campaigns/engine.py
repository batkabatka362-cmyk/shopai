"""EmailCampaignEngine — public surface.

The one class owner-facing code + the autopilot cycle + the
MCP tools call. Thin wrapper around ``ScheduleQueue`` +
``dispatcher.dispatch`` with sensible defaults (from-address,
default send function) so callers don't have to plumb those
themselves.

Usage::

    from core.engines.email_campaigns import get_engine

    engine = get_engine()
    engine.enroll(
        "customer@example.com",
        flow="post_purchase",
        context={
            "first_name": "Jane", "store_name": "Deguar",
            "store_url": "https://deguar.myshopify.com",
            "product_name": "Galaxy Projector",
            "review_url": "https://deguar.myshopify.com/reviews",
            "recommendations": "• 3D Moon Lamp\\n• LED Cloud Light",
            "discount_code": "COME10",
        },
    )

    # Cron / autopilot cycle
    report = engine.dispatch_due()

    # Owner inspects
    engine.stats()
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any

from core.engines.email_campaigns.dispatcher import (
    DispatchReport, SendFn, dispatch,
)
from core.engines.email_campaigns.flows import FLOWS
from core.engines.email_campaigns.queue import (
    ScheduleQueue, ScheduledEmail,
)

_logger = logging.getLogger("shopai.email_campaigns.engine")


class EmailCampaignEngine:
    """Orchestrates flow enrollment + dispatch.

    Thread-safe. Single-instance per process via ``get_engine()``.
    The queue DB path + default from-address come from env at
    construction; tests instantiate directly with a tmp path.
    """

    def __init__(
        self,
        queue: ScheduleQueue | None = None,
        *,
        from_email: str = "",
        from_name: str = "",
        now_fn: Any = None,
    ) -> None:
        self._queue = queue or ScheduleQueue()
        self._from_email = (
            from_email
            or os.environ.get(
                "SHOPAI_EMAIL_FROM", "hello@shopai.test",
            )
        )
        self._from_name = (
            from_name
            or os.environ.get("SHOPAI_EMAIL_FROM_NAME", "")
        )
        self._now = now_fn or time.time

    # ── Public read surface ────────────────────────────

    @property
    def queue(self) -> ScheduleQueue:
        return self._queue

    def stats(self) -> dict[str, Any]:
        return self._queue.stats()

    def list_for_recipient(
        self, recipient: str,
    ) -> list[ScheduledEmail]:
        return self._queue.list_by_recipient(recipient)

    # ── Enrollment ─────────────────────────────────────

    def enroll(
        self,
        recipient: str,
        *,
        flow: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Enqueue every step of ``flow`` for ``recipient``.

        Idempotent — re-enrolling a recipient already in the
        flow is a no-op for each step that already exists.
        Unsubscribed recipients never get enrolled.

        Returns ``{"enrollment_id": ..., "enrolled": N,
        "skipped": M, "unsubscribed": bool}``.
        """
        if not recipient or "@" not in recipient:
            raise ValueError(
                f"recipient must be a valid email, got "
                f"{recipient!r}",
            )
        flow_def = FLOWS.get(flow)
        if flow_def is None:
            raise ValueError(
                f"unknown flow {flow!r}. Known: "
                f"{sorted(FLOWS.keys())}",
            )
        ctx = dict(context or {})

        if self._queue.is_unsubscribed(recipient):
            return {
                "enrollment_id": "",
                "enrolled": 0,
                "skipped": 0,
                "unsubscribed": True,
            }

        enrollment_id = uuid.uuid4().hex[:16]
        now = float(self._now())
        enrolled = 0
        skipped = 0
        for step in flow_def.ordered_steps():
            send_at = now + step.delay_minutes * 60.0
            row = self._queue.enqueue(
                recipient=recipient,
                flow_id=flow,
                step_id=step.step_id,
                send_at=send_at,
                context=ctx,
                enrollment_id=enrollment_id,
            )
            if row is None:
                # Already enqueued (idempotency) — count as
                # skipped so the caller sees how many new rows
                # landed.
                skipped += 1
            else:
                enrolled += 1
        _logger.info(
            "enrolled %s in %s: +%d rows (skipped %d already"
            " pending)",
            recipient, flow, enrolled, skipped,
        )
        return {
            "enrollment_id": enrollment_id,
            "enrolled": enrolled,
            "skipped": skipped,
            "unsubscribed": False,
        }

    # ── Dispatch ───────────────────────────────────────

    def dispatch_due(
        self,
        *,
        limit: int = 100,
        send_fn: SendFn | None = None,
    ) -> DispatchReport:
        """Drain up to ``limit`` due rows. Returns a
        ``DispatchReport``.

        ``send_fn=None`` means "use the default router-based
        sender". Tests inject a fake."""
        return dispatch(
            self._queue,
            from_email=self._from_email,
            from_name=self._from_name,
            limit=limit,
            send_fn=send_fn,
        )

    def cancel_flow(
        self, recipient: str, flow: str,
        *, reason: str = "",
    ) -> int:
        """Bulk-cancel every pending row for (recipient, flow).
        Used when a buyer converts — kills the remaining
        abandoned-cart reminders so they don't get 'you left
        X behind' after they actually checked out."""
        return self._queue.cancel_pending_for_flow(
            recipient, flow, reason=reason,
        )

    # ── Unsubscribe surface ─────────────────────────────

    def unsubscribe(
        self, recipient: str, *, source: str = "",
    ) -> bool:
        return self._queue.unsubscribe(
            recipient, source=source,
        )

    def is_unsubscribed(self, recipient: str) -> bool:
        return self._queue.is_unsubscribed(recipient)


# ── Module-level singleton ─────────────────────────────

_SINGLETON: EmailCampaignEngine | None = None
_SINGLETON_LOCK = threading.Lock()


def get_engine() -> EmailCampaignEngine:
    """Shared process-wide engine. Lazy-init on first call."""
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = EmailCampaignEngine()
    return _SINGLETON


def reset_singleton_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
