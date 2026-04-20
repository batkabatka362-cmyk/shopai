"""Shopify expiring offline-access token auth (2026-01+).

Per Shopify's April 1, 2026 requirement, new public apps must use
expiring offline-access tokens. The shape:

  * access_token  — short TTL (60 min)
  * refresh_token — long TTL (90 days)
  * Both issued at install time via the standard OAuth code
    exchange. Refresh uses the token-exchange endpoint with
    ``grant_type=refresh_token``.

This module lives alongside the older ``ShopifyAuth`` (client-
credentials-style for private/custom apps) and is selected at
runtime when the app type is "public" (apps distributed via the
Shopify App Store).

Surface:

  * ``ExpiringTokenRecord`` — one (shop, access_token,
    access_expires_at, refresh_token, refresh_expires_at) row.
  * ``ExpiringTokenStore`` — SQLite persistence.
  * ``ExpiringTokenAuth`` — ``get_access_token(shop)`` returns a
    valid token, refreshing on demand; ``invalidate(shop)`` is
    called on 401 ``invalid_grant`` so the next call forces a
    fresh exchange.

Pure stdlib. Thread-safe (RLock). Dependency-injected HTTP for
offline tests.

Docs reference:
* shopify.dev/changelog/expiring-offline-access-tokens-required-
  for-public-apps-april-1-2026
* shopify.dev/docs/apps/build/authentication-authorization/
  access-tokens/token-exchange
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.auth.shopify_expiring_token")


_DEFAULT_ACCESS_TTL_S = 60 * 60.0          # 60 min
_DEFAULT_REFRESH_TTL_S = 90 * 24 * 3600.0  # 90 days
_REFRESH_BUFFER_S = 5 * 60.0               # refresh with 5 min left


_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_tokens (
    shop                 TEXT PRIMARY KEY,
    access_token         TEXT NOT NULL,
    access_expires_at    REAL NOT NULL,
    refresh_token        TEXT NOT NULL,
    refresh_expires_at   REAL NOT NULL,
    updated_at           REAL NOT NULL
);
"""


@dataclass
class ExpiringTokenRecord:
    shop: str
    access_token: str
    access_expires_at: float
    refresh_token: str
    refresh_expires_at: float
    updated_at: float = 0.0

    def access_valid(self, *, now: float, buffer: float) -> bool:
        return self.access_token != "" and (
            self.access_expires_at - now > buffer
        )

    def refresh_valid(self, *, now: float) -> bool:
        return self.refresh_token != "" and (
            self.refresh_expires_at > now
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "shop": self.shop,
            "access_token": self.access_token,
            "access_expires_at": self.access_expires_at,
            "refresh_token": self.refresh_token,
            "refresh_expires_at": self.refresh_expires_at,
            "updated_at": self.updated_at,
        }


class TokenExchangeError(Exception):
    pass


class ExpiringTokenStore:
    """SQLite-backed per-shop token cache."""

    def __init__(
        self,
        db_path: str | Path = "data/shopify_tokens.db",
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def save(self, record: ExpiringTokenRecord) -> None:
        now = float(time.time())
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO shop_tokens("
                "shop, access_token, access_expires_at, "
                "refresh_token, refresh_expires_at, "
                "updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    record.shop,
                    record.access_token,
                    float(record.access_expires_at),
                    record.refresh_token,
                    float(record.refresh_expires_at),
                    now,
                ),
            )
            self._conn.commit()

    def load(
        self, shop: str,
    ) -> ExpiringTokenRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT shop, access_token, "
                "access_expires_at, refresh_token, "
                "refresh_expires_at, updated_at "
                "FROM shop_tokens WHERE shop=?",
                (shop,),
            ).fetchone()
        if row is None:
            return None
        return ExpiringTokenRecord(
            shop=row[0],
            access_token=row[1],
            access_expires_at=float(row[2]),
            refresh_token=row[3],
            refresh_expires_at=float(row[4]),
            updated_at=float(row[5]),
        )

    def delete(self, shop: str) -> bool:
        with self._lock:
            n = self._conn.execute(
                "DELETE FROM shop_tokens WHERE shop=?",
                (shop,),
            ).rowcount
            self._conn.commit()
        return bool(n)

    def list_shops(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT shop FROM shop_tokens "
                "ORDER BY updated_at DESC",
            ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class ExpiringTokenAuth:
    """Manages offline-access tokens that expire every 60 min."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        store: ExpiringTokenStore | None = None,
        http: Any = None,
        now_fn: Any = None,
        refresh_buffer_s: float = _REFRESH_BUFFER_S,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError(
                "client_id + client_secret required",
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._store = store or ExpiringTokenStore()
        self._http = http
        self._now_fn = now_fn or time.time
        self._buffer = float(refresh_buffer_s)
        self._lock = threading.RLock()

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        import requests
        return requests

    # ── Public API ───────────────────────────────────────

    def install(
        self,
        *,
        shop: str,
        access_token: str,
        refresh_token: str,
        access_ttl_s: float = _DEFAULT_ACCESS_TTL_S,
        refresh_ttl_s: float = _DEFAULT_REFRESH_TTL_S,
    ) -> ExpiringTokenRecord:
        """Called right after the OAuth install callback.

        Caller provides both tokens + TTLs from Shopify's
        response; this just persists them.
        """
        if not shop:
            raise ValueError("shop required")
        now = float(self._now_fn())
        record = ExpiringTokenRecord(
            shop=shop,
            access_token=access_token,
            access_expires_at=now + float(access_ttl_s),
            refresh_token=refresh_token,
            refresh_expires_at=now + float(refresh_ttl_s),
            updated_at=now,
        )
        self._store.save(record)
        return record

    def get_access_token(self, shop: str) -> str:
        """Return a valid access token for the shop, refreshing
        if the current one is within ``refresh_buffer_s`` of
        expiry."""
        if not shop:
            raise ValueError("shop required")
        with self._lock:
            record = self._store.load(shop)
            if record is None:
                raise TokenExchangeError(
                    f"no tokens cached for {shop!r}; "
                    "run install() first",
                )
            now = float(self._now_fn())
            if record.access_valid(
                now=now, buffer=self._buffer,
            ):
                return record.access_token
            if not record.refresh_valid(now=now):
                raise TokenExchangeError(
                    f"refresh_token expired for {shop!r}; "
                    "owner must re-auth via Shopify install",
                )
            refreshed = self._do_refresh(
                shop=shop, record=record,
            )
            return refreshed.access_token

    def invalidate(self, shop: str) -> None:
        """Forget the cached access_token (called on 401
        `invalid_grant`). The next get_access_token() will do
        a fresh token-exchange using the refresh_token."""
        with self._lock:
            record = self._store.load(shop)
            if record is None:
                return
            record.access_token = ""
            record.access_expires_at = 0.0
            self._store.save(record)

    def token_status(
        self, shop: str,
    ) -> dict[str, Any]:
        record = self._store.load(shop)
        if record is None:
            return {
                "shop": shop,
                "status": "not_installed",
            }
        now = float(self._now_fn())
        return {
            "shop": shop,
            "status": (
                "active"
                if record.access_valid(
                    now=now, buffer=self._buffer,
                )
                else "expired_needs_refresh"
                if record.refresh_valid(now=now)
                else "refresh_expired_reinstall"
            ),
            "access_expires_in_s": max(
                0.0, record.access_expires_at - now,
            ),
            "refresh_expires_in_s": max(
                0.0, record.refresh_expires_at - now,
            ),
        }

    # ── Internal ─────────────────────────────────────────

    def _do_refresh(
        self,
        *,
        shop: str,
        record: ExpiringTokenRecord,
    ) -> ExpiringTokenRecord:
        """Call Shopify's token-exchange endpoint with the
        refresh_token. Shopify also rotates the refresh_token
        on every exchange — store the new one."""
        url = (
            f"https://{shop}/admin/oauth/access_token"
        )
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "refresh_token",
            "refresh_token": record.refresh_token,
        }
        try:
            resp = self._client().post(
                url,
                json=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
        except Exception as exc:  # noqa: BLE001
            raise TokenExchangeError(
                f"network error: {exc}",
            ) from exc
        status = int(
            getattr(resp, "status_code", 0),
        )
        if status >= 400:
            text = getattr(resp, "text", "") or ""
            raise TokenExchangeError(
                f"HTTP {status}: {text[:120]}",
            )
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise TokenExchangeError(
                f"bad JSON: {exc}",
            ) from exc
        new_access = data.get("access_token") or ""
        new_refresh = (
            data.get("refresh_token")
            or record.refresh_token
        )
        if not new_access:
            raise TokenExchangeError(
                "no access_token in response",
            )
        try:
            access_in = float(
                data.get(
                    "expires_in", _DEFAULT_ACCESS_TTL_S,
                ),
            )
        except (TypeError, ValueError):
            access_in = _DEFAULT_ACCESS_TTL_S
        try:
            refresh_in = float(
                data.get(
                    "refresh_token_expires_in",
                    _DEFAULT_REFRESH_TTL_S,
                ),
            )
        except (TypeError, ValueError):
            refresh_in = _DEFAULT_REFRESH_TTL_S
        now = float(self._now_fn())
        new_record = ExpiringTokenRecord(
            shop=shop,
            access_token=new_access,
            access_expires_at=now + access_in,
            refresh_token=new_refresh,
            refresh_expires_at=now + refresh_in,
            updated_at=now,
        )
        self._store.save(new_record)
        logger.info(
            "token-exchange ok for %s (access %.0fs, refresh %.0fd)",
            shop, access_in, refresh_in / 86400,
        )
        return new_record
