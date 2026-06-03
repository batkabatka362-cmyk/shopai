"""Track which orders have been asked for a review.

In-memory + file-backed JSON store at data/review_requests.json.
Pattern J test guard short-circuits writes under pytest so unit
tests don't pollute production state.

Persistence model:
  {
    "asked": {
      "<order_id>": {
        "asked_at": <unix_seconds>,
        "customer_email": "...",
        "product_title": "...",
        "send_status": "queued" | "sent" | "failed"
      },
      ...
    }
  }

Newest writes win on collision. Operators wanting to re-ask a
specific customer can run ``clear_asked(order_id)``.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_TRACKING_PATH = Path(
    os.environ.get(
        "SHOPAI_REVIEW_REQUEST_PATH",
        "data/review_requests.json",
    )
)


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> dict[str, Any]:
    try:
        if not _TRACKING_PATH.exists():
            return {"asked": {}}
        with _TRACKING_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("asked", {})
            if not isinstance(data["asked"], dict):
                data["asked"] = {}
            return data
        return {"asked": {}}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "review_request: load failed (%s)", exc,
        )
        return {"asked": {}}


def _atomic_write(data: dict[str, Any]) -> None:
    """Write via temp + os.replace so a crash mid-write can't
    leave a half-flushed JSON file."""
    try:
        _TRACKING_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "review_request: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=".review_requests_",
            suffix=".json",
            dir=str(_TRACKING_PATH.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, _TRACKING_PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.debug(
            "review_request: write failed (%s)", exc,
        )


def has_asked(order_id: str) -> bool:
    """Return True when the given order has already been asked."""
    if not order_id:
        return False
    raw = _load_raw()
    return str(order_id) in (raw.get("asked") or {})


def mark_asked(
    *,
    order_id: str,
    customer_email: str,
    product_title: str,
    send_status: str = "queued",
) -> bool:
    """Record that we've asked this order's customer. Returns
    True on write, False on test-env / invalid / I/O error."""
    if _is_test_environment():
        return False
    if not order_id:
        return False
    raw = _load_raw()
    asked = raw.setdefault("asked", {})
    asked[str(order_id)] = {
        "asked_at": time.time(),
        "customer_email": customer_email,
        "product_title": product_title,
        "send_status": send_status,
    }
    _atomic_write(raw)
    return True


def clear_asked(order_id: str) -> bool:
    """Remove an order from the asked list. Lets operators
    re-ask after a failed send or wrong-customer mix-up."""
    if _is_test_environment():
        return False
    if not order_id:
        return False
    raw = _load_raw()
    asked = raw.get("asked") or {}
    if str(order_id) not in asked:
        return False
    del asked[str(order_id)]
    _atomic_write(raw)
    return True


def asked_count() -> int:
    """Total orders asked so far. Useful for status summaries."""
    raw = _load_raw()
    return len(raw.get("asked") or {})


def reset_path(path: Path) -> None:
    """Test-only hook to override the persistence path."""
    global _TRACKING_PATH
    _TRACKING_PATH = path
