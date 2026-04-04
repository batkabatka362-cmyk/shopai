"""Email Reporter Engine — recipient manager.

Manages and validates report recipients.
"""
from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def manage_recipients(
    recipients: list[str],
) -> dict[str, Any]:
    """Validate and manage recipient list."""
    try:
        valid: list[str] = []
        invalid: list[str] = []

        for email in recipients:
            email = str(email).strip().lower()
            if _EMAIL_RE.match(email):
                valid.append(email)
            else:
                invalid.append(email)

        # Deduplicate
        valid = sorted(set(valid))

        recipient_list = {
            "recipients": valid,
            "valid_count": len(valid),
            "invalid_count": len(invalid),
        }

        if invalid:
            recipient_list["invalid_emails"] = invalid

        return {"status": "success", "recipient_list": recipient_list}
    except Exception as exc:
        return {"status": "error", "recipient_list": {}, "error": f"Recipient management failed: {exc}"}
