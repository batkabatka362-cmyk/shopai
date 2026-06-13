"""Send a test transactional email to verify the wire-up.

Uses the SmartRouter to dispatch SEND_EMAIL_TRANSACTIONAL to
whichever ESP adapter is configured + present in the registry.
Records via Pattern Z.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


_ENGINE = "email_connect"
_ACTION_TYPE = "send_test_email"


@dataclass
class SendResult:
    success: bool
    detail: str
    message_id: str = ""
    error: str = ""


def send_test_email(
    *,
    to: str,
    subject: str = "ShopAI: test email — connection verified",
    body_html: str = (
        "<p>This is a ShopAI test email confirming your ESP "
        "credentials are wired correctly.</p>"
        "<p>If you're seeing this, you're ready to send "
        "real customer campaigns.</p>"
    ),
    from_email: str | None = None,
) -> SendResult:
    """Fire a single transactional email via whichever ESP is
    configured. Returns success/failure + detail."""
    if not to or "@" not in to:
        return SendResult(
            success=False,
            detail="'to' must be a valid email address",
        )

    ok = False
    err = ""
    detail = ""
    msg_id = ""
    try:
        from core.adapters.router import get_router
        from core.adapters.base import Capability
        router = get_router()
        params = {
            "to": to,
            "subject": subject,
            "body_html": body_html,
        }
        if from_email:
            params["from"] = from_email
        try:
            result = router.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL, params,
            )
            ok = bool(getattr(result, "ok", False))
            err = getattr(result, "error", "") or ""
            data = getattr(result, "data", None) or {}
            if isinstance(data, dict):
                msg_id = str(
                    data.get("message_id")
                    or data.get("id")
                    or ""
                )
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            detail = (
                f"adapter raised: {type(exc).__name__}"
            )
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        detail = f"router unavailable: {type(exc).__name__}"

    # Pattern Z record -- ALWAYS, including router-unavailable
    # and adapter-raise paths so substrate failures reach
    # the autonomous loop's outcome tracking.
    try:
        from engines._writeback_recorder import (
            record_writeback,
        )
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SEND_EMAIL_TRANSACTIONAL",
            params={"to": to, "subject": subject},
            success=ok,
            error=None if ok else err,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("email_connect writeback raised: %s", exc)

    if not ok:
        return SendResult(
            success=False,
            detail=detail or err or "send failed",
            error=err,
        )

    return SendResult(
        success=True,
        detail=f"sent to {to} (id={msg_id or '?'})",
        message_id=msg_id,
    )
