"""Owner notifier — compose digest + push via Telegram bot.

Sprint 3 S3-5b. Closes the loop that was previously stdout-only:
``shopai report`` shows the launch digest locally, but the owner
sits on Telegram. This module composes the digest and sends it as
a Markdown message through the Telegram adapter, degrading
gracefully when the adapter isn't configured.

Dependency-injected: pass your own ``compose_fn`` + ``bot`` for
testing. Defaults use ``compose_digest`` + ``TelegramBotAdapter``
singletons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("agents.owner_dialog.notify")


@dataclass
class NotifyResult:
    sent: bool
    message_id: int | None = None
    reason: str = ""
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "sent": self.sent,
            "message_id": self.message_id,
            "reason": self.reason,
            "text": self.text,
        }


def notify_owner(
    *,
    period_hours: float = 24.0 * 7,
    bot: Any = None,
    compose_fn: Any = None,
    chat_id: str | None = None,
    dry_run: bool = False,
) -> NotifyResult:
    """Compose digest and send to Telegram.

    ``dry_run=True`` composes the message but never calls
    ``bot.send_message`` — useful for local preview.
    """
    if compose_fn is None:
        from agents.learning.launch_digest import compose_digest
        compose_fn = compose_digest
    try:
        digest = compose_fn(period_hours=period_hours)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compose_digest failed: %s", exc,
        )
        return NotifyResult(
            sent=False,
            reason=f"compose failed: {exc}",
        )
    text = digest.as_markdown()
    if dry_run:
        return NotifyResult(
            sent=False,
            reason="dry_run",
            text=text,
        )
    if bot is None:
        from core.adapters.telegram_bot import (
            TelegramBotAdapter,
        )
        bot = TelegramBotAdapter()
    if not bot.is_available():
        return NotifyResult(
            sent=False,
            reason=(
                "telegram not configured "
                "(set TELEGRAM_BOT_TOKEN + "
                "TELEGRAM_CHAT_ID)"
            ),
            text=text,
        )
    message_id = bot.send_message(text, chat_id=chat_id)
    if message_id is None:
        return NotifyResult(
            sent=False,
            reason=(
                bot.stats().get("last_error", "send failed")
            ),
            text=text,
        )
    return NotifyResult(
        sent=True,
        message_id=int(message_id),
        text=text,
    )
