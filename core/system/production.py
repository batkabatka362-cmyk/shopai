"""Production Hardening — error recovery, rate limiting, config, backup, audit.

Makes ShopAI production-ready with enterprise-grade reliability.
"""
from __future__ import annotations
import json
import os
import shutil
import time
import threading
from pathlib import Path
from typing import Any
from utils.logger import get_logger
logger = get_logger("production")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.json"
_BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "backups"
_AUDIT_PATH = Path(__file__).resolve().parents[2] / "data" / "audit_log.json"


# ═══════════════════════════════════════════════
# CONFIG MANAGER
# ═══════════════════════════════════════════════

class ConfigManager:
    """Centralized configuration management."""

    _defaults = {
        "store_id": "deguar",
        "cycle_interval_seconds": 600,
        "max_products_per_cycle": 15,
        "max_shopify_calls_per_second": 2,
        "auto_approve": False,
        "enable_live_execution": False,
        "enable_notifications": True,
        "dashboard_port": 8080,
        "dashboard_ui_port": 8082,
        "memory_prune_days": 30,
        "rl_learn_every_n_cycles": 5,
        "strategy_expand_every_n_cycles": 5,
        "log_level": "INFO",
        "backup_before_shopify_changes": True,
    }

    def __init__(self):
        self._config = dict(self._defaults)
        self._load()

    def _load(self):
        try:
            if _CONFIG_PATH.exists():
                with open(_CONFIG_PATH) as f:
                    stored = json.load(f)
                    self._config.update(stored)
        except Exception as exc:
            logger.debug("config load failed: %s", exc)

    def save(self):
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_PATH, "w") as f:
            json.dump(self._config, f, indent=2)

    def get(self, key: str, default=None):
        return self._config.get(key, default)

    def set(self, key: str, value):
        self._config[key] = value
        self.save()

    def get_all(self) -> dict:
        return dict(self._config)


# ═══════════════════════════════════════════════
# RATE LIMITER (Shopify 2 calls/sec)
# ═══════════════════════════════════════════════

class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, calls_per_second: float = 2.0):
        self._rate = calls_per_second
        self._tokens = calls_per_second
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        """Wait until a token is available."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                time.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


# ═══════════════════════════════════════════════
# ERROR RECOVERY
# ═══════════════════════════════════════════════

class ErrorRecovery:
    """Auto-recover from errors with retry and circuit breaker."""

    def __init__(self, max_retries: int = 3):
        self._max_retries = max_retries
        self._failures: dict[str, int] = {}
        self._circuit_open: dict[str, float] = {}

    def execute_with_retry(self, name: str, func, *args, **kwargs):
        """Execute with automatic retry on failure."""
        # Check circuit breaker
        if name in self._circuit_open:
            if time.time() - self._circuit_open[name] < 300:  # 5 min cooldown
                return {"error": "circuit_open", "component": name}
            del self._circuit_open[name]

        for attempt in range(self._max_retries):
            try:
                result = func(*args, **kwargs)
                self._failures[name] = 0  # Reset on success
                return result
            except Exception as exc:
                self._failures[name] = self._failures.get(name, 0) + 1
                logger.warning("Retry %d/%d for %s: %s",
                              attempt + 1, self._max_retries, name, exc)
                if attempt < self._max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff

        # Open circuit after max failures
        if self._failures.get(name, 0) >= self._max_retries:
            self._circuit_open[name] = time.time()
            logger.error("Circuit open for %s", name)

        return {"error": "max_retries", "component": name}

    def get_status(self) -> dict:
        return {
            "failures": dict(self._failures),
            "circuits_open": list(self._circuit_open.keys()),
        }


# ═══════════════════════════════════════════════
# BACKUP SYSTEM
# ═══════════════════════════════════════════════

class BackupSystem:
    """Database backup before changes."""

    def backup_databases(self) -> dict[str, Any]:
        """Backup all SQLite databases."""
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_dir = _BACKUP_DIR / timestamp

        db_dir = Path(__file__).resolve().parents[2] / "data"
        dbs = list(db_dir.glob("*.db"))

        backed_up = 0
        for db in dbs:
            try:
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(db, backup_dir / db.name)
                backed_up += 1
            except Exception as exc:
                logger.debug("backup failed for %s: %s", db.name, exc)

        # Keep only last 10 backups
        backups = sorted(_BACKUP_DIR.iterdir())
        while len(backups) > 10:
            shutil.rmtree(backups.pop(0), ignore_errors=True)

        return {"backed_up": backed_up, "path": str(backup_dir), "total_dbs": len(dbs)}

    def list_backups(self) -> list[str]:
        if not _BACKUP_DIR.exists():
            return []
        return sorted(str(d.name) for d in _BACKUP_DIR.iterdir() if d.is_dir())


# ═══════════════════════════════════════════════
# AUDIT TRAIL
# ═══════════════════════════════════════════════

class AuditTrail:
    """Logs every Shopify change for accountability."""

    def __init__(self):
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _AUDIT_PATH.exists():
                self._entries = json.loads(_AUDIT_PATH.read_text())
        except Exception:
            self._entries = []

    def log(self, action: str, target: str, details: dict | None = None,
            store_id: str = "") -> None:
        entry = {
            "action": action,
            "target": target,
            "store_id": store_id,
            "details": details or {},
            "timestamp": time.time(),
            "time_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._entries.append(entry)
        self._save()

    def _save(self):
        try:
            _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Keep last 1000
            if len(self._entries) > 1000:
                self._entries = self._entries[-1000:]
            _AUDIT_PATH.write_text(json.dumps(self._entries, indent=2))
        except Exception as exc:
            logger.debug("audit write failed: %s", exc)

    def get_recent(self, limit: int = 50) -> list[dict]:
        return self._entries[-limit:]

    def get_stats(self) -> dict:
        actions = {}
        for e in self._entries:
            a = e.get("action", "unknown")
            actions[a] = actions.get(a, 0) + 1
        return {"total": len(self._entries), "by_action": actions}


# Singletons
_config = None
_rate_limiter = None
_recovery = None
_backup = None
_audit = None
_config_lock = threading.Lock()
_rate_limiter_lock = threading.Lock()
_recovery_lock = threading.Lock()
_backup_lock = threading.Lock()
_audit_lock = threading.Lock()


def get_config():
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = ConfigManager()
    return _config


def get_rate_limiter():
    global _rate_limiter
    if _rate_limiter is None:
        with _rate_limiter_lock:
            if _rate_limiter is None:
                _rate_limiter = RateLimiter()
    return _rate_limiter


def get_error_recovery():
    global _recovery
    if _recovery is None:
        with _recovery_lock:
            if _recovery is None:
                _recovery = ErrorRecovery()
    return _recovery


def get_backup():
    global _backup
    if _backup is None:
        with _backup_lock:
            if _backup is None:
                _backup = BackupSystem()
    return _backup


def get_audit():
    global _audit
    if _audit is None:
        with _audit_lock:
            if _audit is None:
                _audit = AuditTrail()
    return _audit
