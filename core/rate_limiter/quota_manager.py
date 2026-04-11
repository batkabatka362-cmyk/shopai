"""QuotaManager — model call quotas per engine/role."""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.helpers import safe_int
from utils.logger import get_logger

logger = get_logger("rate_limiter.quota")


class QuotaManager:
    """Manages model call quotas. Resets periodically."""

    def __init__(self) -> None:
        self._quotas: dict[str, dict[str, Any]] = {}
        self._usage: dict[str, int] = {}
        # RLock so ``get_all_quotas`` can call ``_check_locked``
        # without deadlocking on the non-reentrant lock the
        # pre-audit code used. Audit pass 53.
        self._lock = threading.RLock()

    def set_quota(self, key: str, limit: int, period_seconds: int = 3600) -> None:
        """Set quota: max calls per period."""
        if not isinstance(key, str) or not key:
            return
        limit = max(0, safe_int(limit))
        period_seconds = max(1, safe_int(period_seconds, default=3600))
        with self._lock:
            self._quotas[key] = {
                "limit": limit,
                "period": period_seconds,
                "reset_at": time.time() + period_seconds,
            }
            self._usage.setdefault(key, 0)

    def check(self, key: str) -> dict[str, Any]:
        """Check quota status. Returns remaining, used, limit."""
        with self._lock:
            return self._check_locked(key)

    def _check_locked(self, key: str) -> dict[str, Any]:
        """Caller must hold ``self._lock``."""
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
        """Consume quota. Returns True if allowed.

        SECURITY: pre-audit accepted a negative ``amount`` and
        silently SUBTRACTED from usage — a caller sending
        ``consume(key, -10)`` could refill an exhausted quota
        below zero. Audit pass 53 rejects non-positive amounts.

        Non-numeric / None ``amount`` is also rejected
        (``safe_int`` returns 0 on parse failure → ``0 <= 0``
        → False).
        """
        # default=0 so a non-numeric / None amount coerces to
        # 0 and hits the rejection branch below. Pre-audit a
        # ``default=1`` would let ``consume(key, "bad")``
        # silently succeed.
        amount = safe_int(amount, default=0)
        if amount <= 0:
            return False
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
        """Return all quota statuses.

        Pre-audit deadlocked: held the non-reentrant
        ``self._lock`` then called ``self.check(key)`` which
        tried to acquire the SAME lock again. Python's
        ``threading.Lock`` is non-reentrant so this blocked
        forever on the first call with any configured quotas.
        Audit pass 53: use ``RLock`` + a ``_check_locked``
        helper that assumes the lock is already held.
        """
        with self._lock:
            return {key: self._check_locked(key) for key in self._quotas}

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key:
                self._usage[key] = 0
            else:
                self._usage.clear()
