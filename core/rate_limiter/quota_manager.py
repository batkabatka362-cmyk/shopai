"""QuotaManager — model call quotas per engine/role."""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("rate_limiter.quota")


class QuotaManager:
    """Manages model call quotas. Resets periodically."""

    def __init__(self) -> None:
        self._quotas: dict[str, dict[str, Any]] = {}
        self._usage: dict[str, int] = {}
        self._lock = threading.Lock()

    def set_quota(self, key: str, limit: int, period_seconds: int = 3600) -> None:
        """Set quota: max calls per period."""
        with self._lock:
            self._quotas[key] = {"limit": limit, "period": period_seconds, "reset_at": time.time() + period_seconds}
            self._usage.setdefault(key, 0)

    def check(self, key: str) -> dict[str, Any]:
        """Check quota status. Returns remaining, used, limit."""
        with self._lock:
            quota = self._quotas.get(key)
            if quota is None:
                return {"key": key, "limited": False}

            # Reset if period expired
            if time.time() > quota["reset_at"]:
                self._usage[key] = 0
                quota["reset_at"] = time.time() + quota["period"]

            used = self._usage.get(key, 0)
            remaining = max(0, quota["limit"] - used)
            return {
                "key": key,
                "limited": True,
                "used": used,
                "remaining": remaining,
                "limit": quota["limit"],
                "reset_in_seconds": round(quota["reset_at"] - time.time()),
                "exhausted": remaining == 0,
            }

    def consume(self, key: str, amount: int = 1) -> bool:
        """Consume quota. Returns True if allowed."""
        with self._lock:
            quota = self._quotas.get(key)
            if quota is None:
                return True

            if time.time() > quota["reset_at"]:
                self._usage[key] = 0
                quota["reset_at"] = time.time() + quota["period"]

            used = self._usage.get(key, 0)
            if used + amount > quota["limit"]:
                return False

            self._usage[key] = used + amount
            return True

    def get_all_quotas(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: self.check(key) for key in self._quotas}

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key:
                self._usage[key] = 0
            else:
                self._usage.clear()
