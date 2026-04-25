"""Push HIGH/CRITICAL approval requests to the owner via Telegram.

Architecture per owner's layering principle:

  * ``core/system/approval_queue.py``  — CORE state machine (ours)
  * ``core/system/risk_gate.py``       — CORE classification logic (ours)
  * ``core/adapters/telegram_bot/``    — COMMODITY delivery adapter
                                         (swap-able: any notify channel
                                         can substitute by implementing
                                         the same ``send_message`` shape)
  * THIS MODULE                        — the thin wire between them

Fire-and-forget design:

  * ``enqueue`` → notifier renders a message → Telegram send
  * Adapter errors NEVER block the enqueue path — we log at debug
    and move on. A failed notification is recoverable (owner runs
    ``shopai pending-approvals`` to see the queue).
  * No threading / async — ``send_message`` is ~1 HTTP call, fast
    enough inline. If future latency matters we can add a worker
    thread without changing the public surface.

The message format is deterministic (§4a 95/5 rule) — no LLM
involved in rendering. Owner sees:

    🚨 HIGH approval needed

    request_id:  abc123def456789a
    action:      ad_campaign_create
    why gated:   Commits money or touches an external surface.
    payload:     {"daily_budget_usd": 20, "store": "deguar"}

    Reply with:
      approve abc123def456789a
      deny abc123def456789a <reason>

    Expires in 30 min.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from core.contracts import RiskLevel
from core.system import risk_gate
from core.system.approval_queue import ApprovalRequest

_logger = logging.getLogger("shopai.approval_notifier")


# Only these levels push to Telegram. LOW auto-approves.
# MEDIUM queues when `auto_approve` is off but usually the
# owner picks those up via CLI poll; pinging for every MEDIUM
# in a busy cycle would spam the chat.
_PUSH_LEVELS = {RiskLevel.HIGH, RiskLevel.CRITICAL}


EMOJI = {
    RiskLevel.LOW: "🔵",
    RiskLevel.MEDIUM: "🟡",
    RiskLevel.HIGH: "🚨",
    RiskLevel.CRITICAL: "🆘",
}


def render_message(req: ApprovalRequest) -> str:
    """Produce the owner-facing Telegram body. Pure function so
    it's trivially testable + renders the same regardless of
    adapter state."""
    lines: list[str] = []
    emoji = EMOJI[req.risk_level]
    level = req.risk_level.value.upper()
    lines.append(f"{emoji} *{level} approval needed*")
    lines.append("")
    lines.append(f"request_id:  `{req.request_id}`")
    lines.append(f"action:      `{req.action_type}`")
    lines.append(f"why gated:   {risk_gate.describe(req.risk_level)}")
    # Payload — compact + truncated so one wild campaign spec
    # doesn't blow up the chat.
    if req.payload:
        try:
            payload_json = json.dumps(
                req.payload, ensure_ascii=False,
            )
        except (TypeError, ValueError):
            payload_json = str(req.payload)
        if len(payload_json) > 300:
            payload_json = payload_json[:297] + "…"
        lines.append(f"payload:     `{payload_json}`")
    lines.append("")
    lines.append("Reply with:")
    lines.append(f"  `approve {req.request_id}`")
    lines.append(f"  `deny {req.request_id} <reason>`")
    # Derive TTL minutes from enqueued row
    if req.expires_at > req.requested_at:
        ttl_s = req.expires_at - req.requested_at
        lines.append("")
        lines.append(
            f"Expires in {int(ttl_s // 60)} min.",
        )
    return "\n".join(lines)


AdapterFactory = Callable[[], Any]


class ApprovalNotifier:
    """Fire-and-forget Telegram notifier for the approval queue.

    ``adapter_factory`` lets tests inject a fake adapter. In
    production, the default factory pulls the module-level
    Telegram singleton — the commodity layer. If the adapter
    reports ``is_available()`` is False (no token configured),
    ``notify()`` logs + returns False cleanly.
    """

    def __init__(
        self,
        adapter_factory: AdapterFactory | None = None,
        *,
        push_levels: set[RiskLevel] | None = None,
    ) -> None:
        self._factory = adapter_factory or _default_factory
        self._push = set(push_levels or _PUSH_LEVELS)

    def should_push(self, req: ApprovalRequest) -> bool:
        return req.risk_level in self._push

    def notify(self, req: ApprovalRequest) -> bool:
        """Return True on successful send, False on any skip/
        failure. Never raises — the notifier must not break
        the enqueue path."""
        if not self.should_push(req):
            _logger.debug(
                "notify skip: level=%s below push threshold",
                req.risk_level.value,
            )
            return False
        try:
            adapter = self._factory()
        except Exception as exc:  # noqa: BLE001
            _logger.debug(
                "adapter factory failed: %s", exc,
            )
            return False
        if adapter is None:
            return False
        try:
            if hasattr(adapter, "is_available"):
                if not adapter.is_available():
                    _logger.debug(
                        "telegram adapter unavailable — "
                        "owner can poll `shopai "
                        "pending-approvals`",
                    )
                    return False
            result = adapter.send_message(render_message(req))
            return result is not None
        except Exception as exc:  # noqa: BLE001
            _logger.debug(
                "send_message failed: %s", exc,
            )
            return False


def _default_factory() -> Any:
    """Resolve the commodity Telegram adapter lazily. Return
    ``None`` if the module isn't importable — keeps the core
    queue runnable even when the adapter dependency is absent
    (e.g. in a reduced-dependency deploy)."""
    try:
        from core.adapters.telegram_bot import bot as _bot
    except Exception as exc:  # noqa: BLE001
        _logger.debug("telegram_bot import failed: %s", exc)
        return None
    # Adapter exposes either a class or a module-level singleton
    # factory. Prefer ``get_bot()`` if present.
    if hasattr(_bot, "get_bot"):
        try:
            return _bot.get_bot()
        except Exception as exc:  # noqa: BLE001
            _logger.debug("get_bot() failed: %s", exc)
            return None
    if hasattr(_bot, "TelegramBotAdapter"):
        try:
            return _bot.TelegramBotAdapter()
        except Exception as exc:  # noqa: BLE001
            _logger.debug("TelegramBotAdapter() failed: %s", exc)
            return None
    return None


# ── Module-level singleton ──────────────────────────────


_SINGLETON: ApprovalNotifier | None = None


def get_notifier() -> ApprovalNotifier:
    """Shared process-wide notifier. Lazy-init so import of
    this module never fails even when Telegram isn't configured."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = ApprovalNotifier()
    return _SINGLETON


def reset_singleton_for_tests() -> None:
    global _SINGLETON
    _SINGLETON = None
