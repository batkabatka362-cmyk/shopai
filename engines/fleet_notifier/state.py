"""Persistent cooldown state for the fleet notifier.

JSON-backed at data/fleet_notifier_state.json (env-overridable).
Records the last_sent timestamp per (kind, scope) so the same
event isn't re-sent more often than its cooldown allows.

Pattern J test guard (with SHOPAI_FORCE_PRODUCTION_WRITES
override) so unit tests don't pollute prod state.
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


_PATH = Path(
    os.environ.get(
        "SHOPAI_FLEET_NOTIFIER_PATH",
        "data/fleet_notifier_state.json",
    )
)


def _is_test_environment() -> bool:
    if os.environ.get(
        "SHOPAI_FORCE_PRODUCTION_WRITES", "",
    ).strip().lower() in ("1", "true", "yes", "on"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> dict[str, Any]:
    try:
        if not _PATH.exists():
            return {"sent": {}}
        with _PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("sent", {})
            if not isinstance(data["sent"], dict):
                data["sent"] = {}
            return data
        return {"sent": {}}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "fleet_notifier: load failed (%s)", exc,
        )
        return {"sent": {}}


def _atomic_write(data: dict[str, Any]) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.debug(
            "fleet_notifier: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=".fleet_notifier_",
            suffix=".json",
            dir=str(_PATH.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, _PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.debug(
            "fleet_notifier: write failed (%s)", exc,
        )


def _key(kind: str, scope: str = "") -> str:
    return f"{kind}::{scope}" if scope else kind


def last_sent_at(kind: str, scope: str = "") -> float:
    """Return unix seconds of last send, 0 if never."""
    raw = _load_raw()
    return float(
        (raw.get("sent") or {}).get(_key(kind, scope), 0)
    )


def mark_sent(
    kind: str, scope: str = "", *, ts: float | None = None,
) -> bool:
    """Mark (kind, scope) as just sent. Returns True on
    write, False on test-env / I/O error."""
    if _is_test_environment():
        return False
    if not kind:
        return False
    raw = _load_raw()
    raw.setdefault("sent", {})
    raw["sent"][_key(kind, scope)] = (
        ts if ts is not None else time.time()
    )
    _atomic_write(raw)
    return True


def clear_all() -> bool:
    """Wipe all cooldown state. Returns True on write."""
    if _is_test_environment():
        return False
    _atomic_write({"sent": {}})
    return True


def cooldown_remaining(
    kind: str,
    cooldown_seconds: float,
    *,
    scope: str = "",
    now: float | None = None,
) -> float:
    """Return seconds remaining until next allowed send.
    0 means safe to send."""
    last = last_sent_at(kind, scope)
    if last == 0:
        return 0.0
    n = now if now is not None else time.time()
    elapsed = n - last
    if elapsed >= cooldown_seconds:
        return 0.0
    return max(0.0, cooldown_seconds - elapsed)


def reset_path(path: Path) -> None:
    """Test-only hook to override the persistence path."""
    global _PATH
    _PATH = path
