"""Ad spend activity log (Wave 110).

Mirrors ``engines/returns_management/refund_log.py`` but for
ad-budget actions. Every autonomous budget mutation (W112) +
campaign pause/resume action gets appended here.

The autonomous loop will tighten budgets when ROAS degrades.
Operator needs visibility: "did the loop just kill my $500
budget? Why?" Answer lives in ``data/ad_spend_log.json``.

Bounded to 1000 entries (oldest rotated out). Pattern J guard:
``record_ad_spend_event`` no-ops under ``PYTEST_CURRENT_TEST``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOG_PATH = Path("data") / "ad_spend_log.json"
_MAX_ENTRIES = 1000

# W962-45: spanning lock for concurrent record_ad_spend_event.
_LOCK = threading.RLock()


@dataclass
class AdSpendEvent:
    campaign_id: str
    store_id: str = ""
    action: str = ""              # update_budget / pause / resume
    network: str = "meta"         # meta / google / tiktok / ...
    prior_budget: float = 0.0
    new_budget: float = 0.0
    reason: str = ""
    applied: bool = False
    status: str = ""              # recorded / paused / adapter_failed
    error: str = ""
    recorded_at: float = field(default_factory=time.time)


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load() -> list[dict[str, Any]]:
    if not _LOG_PATH.exists():
        return []
    try:
        with _LOG_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return raw
    except Exception as exc:  # noqa: BLE001
        logger.debug("ad_spend_log load raised: %s", exc)
    return []


def _save(entries: list[dict[str, Any]]) -> None:
    """W962-47: atomic write via temp + os.replace."""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if len(entries) > _MAX_ENTRIES:
            entries = entries[-_MAX_ENTRIES:]
        tmp = _LOG_PATH.with_suffix(
            _LOG_PATH.suffix + ".tmp." + str(os.getpid())
        )
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)
        os.replace(tmp, _LOG_PATH)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ad_spend_log save raised: %s", exc)


def record_ad_spend_event(event: AdSpendEvent) -> None:
    """Append an ad-spend event. No-op under pytest."""
    if _is_test_environment():
        return
    if not isinstance(event, AdSpendEvent):
        return
    # W962-45: span load+append+save.
    with _LOCK:
        rows = _load()
        rows.append(asdict(event))
        _save(rows)


def recent_events(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
    network: str | None = None,
) -> list[dict[str, Any]]:
    """Query the log, filtered by window + optional store +
    optional network. Newest first."""
    cutoff = time.time() - max(0.0, window_hours) * 3600.0
    rows = _load()
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ts = r.get("recorded_at")
        if not isinstance(ts, (int, float)) or ts < cutoff:
            continue
        if store_id and r.get("store_id") != store_id:
            continue
        if network and r.get("network") != network:
            continue
        out.append(r)
    out.sort(
        key=lambda row: row.get("recorded_at", 0),
        reverse=True,
    )
    return out


def log_size() -> int:
    return len(_load())
