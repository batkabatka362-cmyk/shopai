"""ShopifyAuth — OAuth token manager for Shopify API (2026+).

Since January 2026, Shopify custom apps require OAuth tokens generated
from Client ID + Client Secret. Tokens expire after 24 hours.

This module handles:
  - Token generation from Client ID + Client Secret
  - Auto-refresh before expiration
  - Thread-safe token access
  - Token caching to disk (survives restarts)
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("shopify.auth")

_TOKEN_CACHE_DIR = Path(__file__).resolve().parents[2] / "data"
_TOKEN_CACHE_FILE = _TOKEN_CACHE_DIR / ".shopify_tokens.json"


class ShopifyAuth:
    """Manages Shopify OAuth tokens with auto-refresh.

    Usage:
        auth = ShopifyAuth("mystore.myshopify.com", client_id, client_secret)
        token = auth.get_token()  # Always returns a valid token
    """

    # Token refresh buffer — refresh 1 hour before expiry
    _REFRESH_BUFFER_S = 3600

    def __init__(self, shop_url: str, client_id: str, client_secret: str) -> None:
        self._shop_url = shop_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str = ""
        self._expires_at: float = 0
        self._lock = threading.Lock()

        # Try loading cached token
        self._load_cached_token()

    # ── Public API ───────────────────────────────────────────

    def get_token(self) -> str:
        """Get a valid access token. Auto-refreshes if expired."""
        with self._lock:
            if self._is_valid():
                return self._access_token

        # Need new token
        return self.refresh_token()

    def refresh_token(self) -> str:
        """Force refresh the access token."""
        with self._lock:
            try:
                token_data = self._request_token()
                self._access_token = token_data["access_token"]
                # Shopify tokens expire in 24 hours (86400 seconds)
                expires_in = int(token_data.get("expires_in", 86400))
                self._expires_at = time.time() + expires_in
                self._save_cached_token()
                logger.info("Token refreshed for %s (expires in %dh)",
                           self._shop_url, expires_in // 3600)
                return self._access_token
            except Exception as exc:
                logger.error("Token refresh failed for %s: %s", self._shop_url, exc)
                raise

    @property
    def is_configured(self) -> bool:
        return bool(self._shop_url and self._client_id and self._client_secret)

    @property
    def token_status(self) -> dict[str, Any]:
        remaining = max(0, self._expires_at - time.time())
        return {
            "shop": self._shop_url,
            "has_token": bool(self._access_token),
            "expires_in_s": int(remaining),
            "expires_in_h": round(remaining / 3600, 1),
            "is_valid": self._is_valid(),
        }

    # ── Token Request ────────────────────────────────────────

    def _request_token(self) -> dict[str, Any]:
        """Request new access token from Shopify using client credentials."""
        url = f"https://{self._shop_url}/admin/oauth/access_token"

        payload = json.dumps({
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "access_token" not in data:
                    raise ValueError(f"No access_token in response: {data}")
                return data
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Shopify token request failed ({exc.code}): {body}"
            ) from exc

    # ── Token Validation ─────────────────────────────────────

    def _is_valid(self) -> bool:
        """Check if current token is still valid (with buffer)."""
        if not self._access_token:
            return False
        return time.time() < (self._expires_at - self._REFRESH_BUFFER_S)

    # ── Token Cache (disk persistence) ───────────────────────

    def _save_cached_token(self) -> None:
        """Save token to disk so it survives restarts."""
        try:
            _TOKEN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache = self._load_all_cached()
            cache[self._shop_url] = {
                "access_token": self._access_token,
                "expires_at": self._expires_at,
                "client_id": self._client_id[:8] + "...",  # Don't store full credentials
            }
            _TOKEN_CACHE_FILE.write_text(json.dumps(cache, indent=2))
        except Exception as exc:
            logger.debug("Token cache save failed: %s", exc)

    def _load_cached_token(self) -> None:
        """Load cached token from disk."""
        try:
            cache = self._load_all_cached()
            if self._shop_url in cache:
                entry = cache[self._shop_url]
                token = entry.get("access_token", "")
                expires = entry.get("expires_at", 0)
                if token and time.time() < expires:
                    self._access_token = token
                    self._expires_at = expires
                    logger.info("Loaded cached token for %s (%.1fh remaining)",
                               self._shop_url, (expires - time.time()) / 3600)
        except Exception:
            pass

    @staticmethod
    def _load_all_cached() -> dict[str, Any]:
        if _TOKEN_CACHE_FILE.exists():
            return json.loads(_TOKEN_CACHE_FILE.read_text())
        return {}


class ShopifyAuthManager:
    """Manages OAuth for multiple stores."""

    def __init__(self) -> None:
        self._auths: dict[str, ShopifyAuth] = {}

    def add_store(self, shop_url: str, client_id: str, client_secret: str) -> ShopifyAuth:
        """Register a store for OAuth."""
        auth = ShopifyAuth(shop_url, client_id, client_secret)
        self._auths[shop_url] = auth
        return auth

    def get_auth(self, shop_url: str) -> ShopifyAuth | None:
        return self._auths.get(shop_url)

    def get_token(self, shop_url: str) -> str:
        """Get valid token for a store."""
        auth = self._auths.get(shop_url)
        if not auth:
            raise ValueError(f"Store not registered: {shop_url}")
        return auth.get_token()

    def refresh_all(self) -> dict[str, Any]:
        """Refresh tokens for all stores."""
        results = {}
        for shop, auth in self._auths.items():
            try:
                auth.refresh_token()
                results[shop] = {"status": "refreshed", **auth.token_status}
            except Exception as exc:
                results[shop] = {"status": "failed", "error": str(exc)}
        return results

    def get_all_status(self) -> list[dict[str, Any]]:
        return [auth.token_status for auth in self._auths.values()]

    def load_from_env(self) -> int:
        """Load store credentials from environment variables."""
        count = 0

        # Primary store
        url = os.environ.get("SHOPAI_SHOPIFY_URL", "")
        cid = os.environ.get("SHOPAI_SHOPIFY_CLIENT_ID", "")
        secret = os.environ.get("SHOPAI_SHOPIFY_CLIENT_SECRET", "")
        # Also support legacy key (for backward compat)
        legacy_key = os.environ.get("SHOPAI_SHOPIFY_KEY", "")

        if url and cid and secret:
            self.add_store(url, cid, secret)
            count += 1
        elif url and legacy_key:
            # Legacy mode — use static token directly
            auth = ShopifyAuth(url, "", "")
            auth._access_token = legacy_key
            auth._expires_at = time.time() + 86400 * 365  # Never expires
            self._auths[url] = auth
            count += 1

        # Additional stores
        for i in range(2, 20):
            url = os.environ.get(f"SHOPAI_STORE_{i}_URL", "")
            cid = os.environ.get(f"SHOPAI_STORE_{i}_CLIENT_ID", "")
            secret = os.environ.get(f"SHOPAI_STORE_{i}_CLIENT_SECRET", "")
            key = os.environ.get(f"SHOPAI_STORE_{i}_KEY", "")

            if url and cid and secret:
                self.add_store(url, cid, secret)
                count += 1
            elif url and key:
                auth = ShopifyAuth(url, "", "")
                auth._access_token = key
                auth._expires_at = time.time() + 86400 * 365
                self._auths[url] = auth
                count += 1
            else:
                break

        return count
