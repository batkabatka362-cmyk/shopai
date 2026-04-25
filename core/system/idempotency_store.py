"""Idempotency store — dedup writes to external APIs.

When the retry_policy (v14-D1) re-fires a failed Shopify POST,
the provider may already have processed the first attempt and
the retry creates a duplicate. Classic distributed-systems bug;
the solution is an idempotency key.

IdempotencyStore registers ``(namespace, key)`` before a write
and replays the stored result on any repeat within the TTL. If
the operation succeeded the first time, we never call the
provider again; if it failed we rerun exactly once to avoid
poisoning cache with transient errors.

APIs:

  execute(ns, key, fn, *args, ttl_s=86400) → result
      • First call: run fn, cache the return value, return it.
      • Repeat within TTL: return cached value without calling fn.
      • If first call raised, later calls will retry fn (errors are
        *not* cached unless cache_errors=True).

  seen(ns, key) → bool
  forget(ns, key) → bool
  cleanup() → prune expired entries

Persistence: ``data/idempotency.db``. Thread-safe. Zero LLM.
Stored values round-trip through JSON so any serialisable return
can be cached; raw bytes are base64.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


_DB_PATH = Path("data/idempotency.db")
_DEFAULT_TTL = 86_400            # 24 hours

_SCHEMA = """
CREATE TABLE IF NOT EXISTS keys (
    namespace   TEXT NOT NULL,
    key         TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    is_error    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    PRIMARY KEY (namespace, key)
);
CREATE INDEX IF NOT EXISTS idx_ns ON keys(namespace);
CREATE INDEX IF NOT EXISTS idx_exp ON keys(expires_at);
"""


@dataclass
class Entry:
    namespace: str
    key: str
    value: Any
    is_error: bool
    created_at: float
    expires_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "key": self.key,
            "value": self.value,
            "is_error": self.is_error,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "ttl_remaining_s": max(0.0, self.expires_at - time.time()),
        }


# ── Store ───────────────────────────────────────────────────

class IdempotencyStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Execute ─────────────────────────────────────────────

    def execute(
        self,
        namespace: str,
        key: str,
        fn: Callable[..., Any],
        *args: Any,
        ttl_s: float = _DEFAULT_TTL,
        cache_errors: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Run ``fn(*args, **kwargs)`` once per (namespace, key).

        Repeat calls within TTL return the cached success value
        without invoking fn. Errors are re-raised and (by default)
        NOT cached — retry remains possible."""
        namespace = namespace.strip()
        key = key.strip()
        if not namespace or not key:
            raise ValueError("namespace and key required")
        existing = self.get(namespace, key)
        if existing is not None and not existing.is_error:
            return existing.value
        if existing is not None and existing.is_error and not cache_errors:
            # Stale error cache — let a retry happen.
            self.forget(namespace, key)
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            if cache_errors:
                self._store(
                    namespace, key,
                    value={"error": f"{type(exc).__name__}: {exc}"},
                    is_error=True, ttl_s=ttl_s,
                )
            raise
        self._store(namespace, key, value=result,
                     is_error=False, ttl_s=ttl_s)
        return result

    # ── Direct API ──────────────────────────────────────────

    def get(self, namespace: str, key: str) -> Entry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT namespace, key, value_json, is_error, "
                "created_at, expires_at FROM keys "
                "WHERE namespace=? AND key=?",
                (namespace.strip(), key.strip()),
            ).fetchone()
        if not row:
            return None
        if row[5] < time.time():
            # expired
            self.forget(row[0], row[1])
            return None
        try:
            value = _decode(row[2])
        except (json.JSONDecodeError, ValueError):
            return None
        return Entry(
            namespace=row[0], key=row[1],
            value=value, is_error=bool(row[3]),
            created_at=float(row[4]), expires_at=float(row[5]),
        )

    def seen(self, namespace: str, key: str) -> bool:
        return self.get(namespace, key) is not None

    def forget(self, namespace: str, key: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM keys WHERE namespace=? AND key=?",
                (namespace.strip(), key.strip()),
            )
            conn.commit()
            return cur.rowcount > 0

    def cleanup(self) -> int:
        """Drop expired entries. Returns number pruned."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM keys WHERE expires_at < ?",
                (time.time(),),
            )
            conn.commit()
            return cur.rowcount or 0

    # ── Introspection ─────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM keys"
            ).fetchone()[0]
            live = conn.execute(
                "SELECT COUNT(*) FROM keys WHERE expires_at >= ?",
                (now,),
            ).fetchone()[0]
            errs = conn.execute(
                "SELECT COUNT(*) FROM keys WHERE is_error=1 "
                "AND expires_at >= ?",
                (now,),
            ).fetchone()[0]
            by_ns = conn.execute(
                "SELECT namespace, COUNT(*) FROM keys "
                "WHERE expires_at >= ? GROUP BY namespace",
                (now,),
            ).fetchall()
        return {
            "total": int(total or 0),
            "live": int(live or 0),
            "error_cached": int(errs or 0),
            "by_namespace": {n: int(c) for n, c in by_ns},
        }

    # ── Internals ──────────────────────────────────────────

    def _store(
        self, namespace: str, key: str,
        *, value: Any, is_error: bool, ttl_s: float,
    ) -> None:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO keys "
                "(namespace, key, value_json, is_error, created_at, "
                " expires_at) VALUES (?,?,?,?,?,?)",
                (namespace, key, _encode(value),
                 1 if is_error else 0, now,
                 now + float(ttl_s)),
            )
            conn.commit()


# ── JSON codec (supports bytes) ────────────────────────────

def _encode(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return json.dumps({
            "__bytes__": True,
            "b64": base64.b64encode(bytes(value)).decode(),
        })
    return json.dumps(value, default=str)


def _decode(payload: str) -> Any:
    obj = json.loads(payload)
    if isinstance(obj, dict) and obj.get("__bytes__"):
        return base64.b64decode(obj.get("b64", ""))
    return obj


# ── Singleton ────────────────────────────────────────────────

_STORE_LOCK = threading.Lock()
_STORE: IdempotencyStore | None = None


def store() -> IdempotencyStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = IdempotencyStore()
    return _STORE
