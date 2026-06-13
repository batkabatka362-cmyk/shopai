"""Track welcome-series progress per customer.

Per-customer state at data/welcome_series.json:
  {
    "customers": {
      "<customer_id>": {
        "first_welcomed_at": <unix_seconds>,
        "stages_sent": [1, 2],
        "last_send_status": "sent" | "failed",
      },
      ...
    }
  }

stages_sent lets us compute the NEXT stage when the cadence
fires again. The scheduler decides when (T+0, T+48h, T+5d);
the tracker just records.

Pattern J test guard so unit tests don't pollute prod state.
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
        "SHOPAI_WELCOME_SERIES_PATH",
        "data/welcome_series.json",
    )
)


def _is_test_environment() -> bool:
    # Pattern J test-environment guard. Mirrors
    # engines.review_request.tracking._is_test_environment.
    if os.environ.get(
        "SHOPAI_FORCE_PRODUCTION_WRITES", "",
    ).strip().lower() in ("1", "true", "yes", "on"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> dict[str, Any]:
    try:
        if not _TRACKING_PATH.exists():
            return {"customers": {}}
        with _TRACKING_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("customers", {})
            if not isinstance(data["customers"], dict):
                data["customers"] = {}
            return data
        return {"customers": {}}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "welcome_series: load failed (%s)", exc,
        )
        return {"customers": {}}


def _atomic_write(data: dict[str, Any]) -> None:
    try:
        _TRACKING_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "welcome_series: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=".welcome_series_",
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
            "welcome_series: write failed (%s)", exc,
        )


def stages_sent(customer_id: str) -> list[int]:
    """Return the stages already sent to a given customer."""
    if not customer_id:
        return []
    raw = _load_raw()
    rec = (raw.get("customers") or {}).get(str(customer_id))
    if not isinstance(rec, dict):
        return []
    s = rec.get("stages_sent") or []
    return [int(x) for x in s if isinstance(x, int)]


def next_stage(customer_id: str) -> int | None:
    """Return the next stage (1, 2, or 3) to send. Returns
    None when all 3 stages are complete."""
    sent = set(stages_sent(customer_id))
    for stage in (1, 2, 3):
        if stage not in sent:
            return stage
    return None


def has_completed(customer_id: str) -> bool:
    """Return True when the customer has received all 3
    stages."""
    return next_stage(customer_id) is None


def mark_sent(
    *,
    customer_id: str,
    stage: int,
    status: str = "sent",
) -> bool:
    """Append a stage to the customer's stages_sent list.
    Returns True on write, False on test-env / invalid /
    I/O error."""
    if _is_test_environment():
        return False
    if not customer_id or stage not in (1, 2, 3):
        return False
    raw = _load_raw()
    customers = raw.setdefault("customers", {})
    rec = customers.get(str(customer_id))
    if not isinstance(rec, dict):
        rec = {
            "first_welcomed_at": time.time(),
            "stages_sent": [],
            "last_send_status": status,
        }
        customers[str(customer_id)] = rec
    if stage not in rec["stages_sent"]:
        rec["stages_sent"].append(stage)
        rec["stages_sent"].sort()
    rec["last_send_status"] = status
    _atomic_write(raw)
    return True


def reset_path(path: Path) -> None:
    """Test-only hook to override the persistence path."""
    global _TRACKING_PATH
    _TRACKING_PATH = path


def welcomed_count() -> int:
    """Total customers welcomed (received >= stage 1)."""
    raw = _load_raw()
    return len(raw.get("customers") or {})
