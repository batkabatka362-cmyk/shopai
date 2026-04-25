"""Dispatcher — render template + send via email adapter.

Pops due rows from the ``ScheduleQueue``, renders the flow
step's subject + body against each row's context, and sends
through the highest-priority configured email adapter.
Per-send failures are recorded on the row but never abort
the whole batch (§4b.E failure isolation).

Template rendering uses ``str.format_map`` with a
``DefaultDict`` that marks missing keys so the dispatcher can
distinguish "context incomplete" (skip, don't fail) from
"adapter error" (fail, log).

Commodity layer pluggability: the ``adapter_factory`` parameter
lets tests inject a fake send target. In production, the
factory calls ``core.adapters.get_router().execute(
Capability.SEND_EMAIL_TRANSACTIONAL, ...)``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from core.engines.email_campaigns.flows import FLOWS, FlowStep
from core.engines.email_campaigns.queue import (
    ScheduleQueue, ScheduledEmail,
)

_logger = logging.getLogger("shopai.email_campaigns.dispatcher")


# ── Template rendering with context awareness ──────────


class _MissingKey:
    """Sentinel — lets ``format_map`` complete without raising
    when a key is absent, so we can detect incomplete context
    AFTER rendering rather than mid-render."""

    def __init__(self, key: str) -> None:
        self.key = key

    def __format__(self, spec: str) -> str:
        return f"{{MISSING:{self.key}}}"

    def __str__(self) -> str:
        return f"{{MISSING:{self.key}}}"


class _CtxDict(dict):
    def __missing__(self, key: str) -> _MissingKey:
        return _MissingKey(key)


def _render(template: str, context: dict[str, Any]) -> str:
    """Safe ``str.format_map`` — missing keys render as
    ``{MISSING:key}`` so the caller can detect + reject rather
    than send a half-baked email."""
    if not template:
        return ""
    try:
        return template.format_map(_CtxDict(context))
    except (KeyError, IndexError, ValueError) as exc:
        _logger.debug("render failed: %s", exc)
        return template


def _context_complete(
    step: FlowStep, context: dict[str, Any],
) -> tuple[bool, str]:
    """Return ``(ok, missing_key)``. The first absent
    required_context key is the reason. Ok means all required
    keys have non-empty string values in ``context``."""
    for key in step.required_context:
        val = context.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            return False, key
    return True, ""


# ── Adapter factory contract ───────────────────────────


#: Callable that sends one email. Returns the provider
#: message_id on success, or raises on failure. Takes a dict
#: matching the ``EmailMessage`` TypedDict the adapter layer
#: already uses: to / from_email / from_name / subject /
#: html / text.
SendFn = Callable[[dict[str, Any]], str]


def _default_send_fn() -> SendFn | None:
    """Resolve the highest-priority configured email adapter
    at dispatch time. Returns ``None`` if no adapter is
    configured — dispatcher treats that as skip-unconfigured."""
    try:
        from core.adapters import Capability, get_router
    except Exception as exc:  # noqa: BLE001
        _logger.debug("adapter layer import failed: %s", exc)
        return None

    router = get_router()

    def send(msg: dict[str, Any]) -> str:
        res = router.execute(
            Capability.SEND_EMAIL_TRANSACTIONAL, msg,
        )
        if not res.ok:
            raise RuntimeError(
                str(getattr(res, "error", "send failed")),
            )
        data = res.data or {}
        return str(data.get("message_id", "") or "")

    return send


# ── Dispatch ───────────────────────────────────────────


@dataclass
class DispatchReport:
    """Outcome of a single ``dispatch_due`` pass."""
    due: int = 0
    sent: int = 0
    failed: int = 0
    skipped_missing_ctx: int = 0
    skipped_unsubscribed: int = 0
    skipped_unconfigured: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def as_dict(self) -> dict[str, Any]:
        return {
            "due": self.due,
            "sent": self.sent,
            "failed": self.failed,
            "skipped_missing_ctx": self.skipped_missing_ctx,
            "skipped_unsubscribed": self.skipped_unsubscribed,
            "skipped_unconfigured": self.skipped_unconfigured,
            "errors": list(self.errors[:10]),
        }


def dispatch(
    queue: ScheduleQueue,
    *,
    from_email: str,
    from_name: str = "",
    limit: int = 100,
    send_fn: SendFn | None = None,
) -> DispatchReport:
    """Drain up to ``limit`` due rows. Returns a
    ``DispatchReport`` with per-status counts.

    ``send_fn`` override is for tests + commodity-swap. When
    missing, resolves to the default router-based fn at call
    time (lazy so an unconfigured process keeps booting).
    """
    report = DispatchReport()
    if not from_email:
        raise ValueError("from_email is required")

    due_rows = queue.pop_due(limit=limit)
    report.due = len(due_rows)

    if not due_rows:
        return report

    effective_send = send_fn or _default_send_fn()

    for row in due_rows:
        # Unsubscribe check — highest priority, wins over
        # everything else including template completeness.
        if queue.is_unsubscribed(row.recipient):
            queue.mark_skipped_unsubscribed(row.row_id)
            report.skipped_unsubscribed += 1
            continue

        flow = FLOWS.get(row.flow_id)
        if flow is None:
            queue.mark_failed(
                row.row_id, error=f"unknown flow {row.flow_id!r}",
            )
            report.failed += 1
            report.errors.append(
                f"{row.row_id}: unknown flow "
                f"{row.flow_id!r}",
            )
            continue

        step = _find_step(flow, row.step_id)
        if step is None:
            queue.mark_failed(
                row.row_id,
                error=(
                    f"step {row.step_id!r} not in flow "
                    f"{row.flow_id!r}"
                ),
            )
            report.failed += 1
            continue

        ctx = row.context
        ok, missing = _context_complete(step, ctx)
        if not ok:
            queue.mark_skipped_missing_ctx(
                row.row_id,
                error=f"missing context key: {missing}",
            )
            report.skipped_missing_ctx += 1
            continue

        subject = _render(step.subject, ctx)
        body = _render(step.body, ctx)

        if effective_send is None:
            # No adapter configured — leave the row pending is
            # wrong (we'd reprocess forever). Better: mark
            # failed so stats are truthful; owner sees and
            # configures.
            queue.mark_failed(
                row.row_id,
                error="no email adapter configured",
            )
            report.skipped_unconfigured += 1
            continue

        msg = {
            "to": row.recipient,
            "from_email": from_email,
            "from_name": from_name or "",
            "subject": subject,
            "text": body,
            "tags": [flow.flow_id, step.step_id],
        }
        try:
            message_id = effective_send(msg)
            queue.mark_sent(
                row.row_id, message_id=message_id,
            )
            report.sent += 1
        except Exception as exc:  # noqa: BLE001
            queue.mark_failed(row.row_id, error=str(exc))
            report.failed += 1
            report.errors.append(
                f"{row.row_id}: {type(exc).__name__}: {exc}",
            )

    return report


def _find_step(flow: Any, step_id: str) -> FlowStep | None:
    for s in flow.steps:
        if s.step_id == step_id:
            return s
    return None
