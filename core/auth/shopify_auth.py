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

# Module-level lock for ``_TOKEN_CACHE_FILE`` read-modify-write
# cycles. Pre-audit ``_save_cached_token`` did:
#     cache = _load_all_cached()    # full dict
#     cache[self._shop_url] = ...   # mutate
#     _TOKEN_CACHE_FILE.write_text(json.dumps(cache))  # whole
# Without a lock, two ShopifyAuth instances (e.g. for store A
# and store B) saving concurrently could interleave:
#   A: load → {}
#   B: load → {}
#   A: write → {"A": ...}
#   B: write → {"B": ...}   # A's update LOST
# Audit pass 53.
_CACHE_LOCK = threading.Lock()


def _normalize_shop_url(raw: Any) -> str:
    """Strip any ``http(s)://`` prefix and trailing slashes.

    Same helper as pass 43 for shopify_api — pre-audit the
    auth module had the same double-scheme bug, producing
    ``https://https://mystore.myshopify.com/...`` when a
    caller passed a scheme-prefixed URL. Audit pass 53.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip().rstrip("/")
    if s.startswith("https://"):
        s = s[len("https://"):]
    elif s.startswith("http://"):
        s = s[len("http://"):]
    return s


class ShopifyAuth:
    """Manages Shopify OAuth tokens with auto-refresh.

    Usage:
        auth = ShopifyAuth("mystore.myshopify.com", client_id, client_secret)
        token = auth.get_token()  # Always returns a valid token
    """

    # Token refresh buffer — refresh 1 hour before expiry
    _REFRESH_BUFFER_S = 3600
    # After a failed refresh, wait this long before trying again
    _REFRESH_BACKOFF_S = 300

    def __init__(self, shop_url: str, client_id: str, client_secret: str) -> None:
        # Pre-audit ``shop_url.rstrip("/")`` crashed on None
        # and produced ``https://https://...`` URLs downstream
        # when callers passed a scheme-prefixed URL. Same
        # double-scheme bug fixed in pass 43 for shopify_api.
        # Audit pass 53.
        self._shop_url = _normalize_shop_url(shop_url)
        self._client_id = client_id if isinstance(client_id, str) else ""
        self._client_secret = client_secret if isinstance(client_secret, str) else ""
        self._access_token: str = ""
        self._expires_at: float = 0
        self._last_refresh_failure: float = 0.0
        self._lock = threading.Lock()

        # Try loading cached token
        self._load_cached_token()

    # ── Public API ───────────────────────────────────────────

    def get_token(self) -> str:
        """Get a valid access token. Auto-refreshes if expired.

        If a refresh attempt failed recently (within REFRESH_BACKOFF_S),
        returns the last known token (even if stale) instead of hammering
        the Shopify token endpoint. Callers get to decide whether to retry.
        """
        with self._lock:
            if self._is_valid():
                return self._access_token
            # Back off after a recent refresh failure — hammering auth
            # costs ~400ms per attempt and floods logs
            if self._last_refresh_failure and \
               (time.time() - self._last_refresh_failure) < self._REFRESH_BACKOFF_S:
                return self._access_token  # may be empty/stale

        try:
            return self.refresh_token()
        except Exception:  # noqa: BLE001
            with self._lock:
                self._last_refresh_failure = time.time()
            return self._access_token

    def refresh_token(self) -> str:
        """Force refresh the access token.

        Pre-audit the whole refresh (including the blocking
        HTTP call) ran under ``self._lock`` — fine for
        correctness, but the double-check on entry is now
        kept to avoid hammering Shopify when multiple threads
        race past ``get_token``'s check. Audit pass 53.
        """
        with self._lock:
            # Double-checked locking: another thread may have
            # refreshed the token while we were waiting for
            # the lock. Pre-audit this path re-requested even
            # when the token was already valid.
            if self._is_valid():
                return self._access_token
            try:
                token_data = self._request_token()
                self._access_token = token_data["access_token"]
                # Shopify tokens expire in 24 hours (86400 seconds).
                # Coerce defensively so a non-int expires_in
                # (None / string) doesn't crash the int() call.
                raw_expires = token_data.get("expires_in", 86400)
                try:
                    expires_in = int(raw_expires) if raw_expires is not None else 86400
                except (TypeError, ValueError):
                    expires_in = 86400
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
        """Request new access token from Shopify using authorization code exchange."""
        if not self._shop_url:
            raise RuntimeError("ShopifyAuth: shop_url not configured")
        url = f"https://{self._shop_url}/admin/oauth/access_token"

        payload = json.dumps({
            "client_id": self._client_id,
            "client_secret": self._client_secret,
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
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Shopify token request failed ({exc.code}): {body}"
            ) from exc

        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise RuntimeError(f"Shopify token response was not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(
                f"Shopify token response is {type(data).__name__}, expected dict"
            )
        if "access_token" not in data or not data["access_token"]:
            raise ValueError(f"No access_token in response: {data}")
        return data

    def get_auth_url(self, scopes: str = "", redirect_uri: str = "") -> str:
        """Generate the Shopify authorization URL for browser approval.

        User opens this URL → approves → gets redirected with ?code=XXX
        """
        if not scopes:
            scopes = "read_products,write_products,read_orders,read_customers,read_inventory,write_inventory"
        if not redirect_uri:
            redirect_uri = f"https://{self._shop_url}/admin/auth/callback"

        params = urllib.parse.urlencode({
            "client_id": self._client_id,
            "scope": scopes,
            "redirect_uri": redirect_uri,
        })
        return f"https://{self._shop_url}/admin/oauth/authorize?{params}"

    def exchange_code(self, code: str) -> str:
        """Exchange authorization code for access token."""
        url = f"https://{self._shop_url}/admin/oauth/access_token"

        payload = json.dumps({
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if "access_token" not in data:
            raise ValueError(f"No access_token: {data}")

        self._access_token = data["access_token"]
        # New Shopify tokens may or may not expire
        expires_in = int(data.get("expires_in", 86400))
        self._expires_at = time.time() + expires_in
        self._save_cached_token()

        logger.info("Token obtained for %s via code exchange", self._shop_url)
        return self._access_token

    # ── Token Validation ─────────────────────────────────────

    def _is_valid(self) -> bool:
        """Check if current token is still valid (with buffer)."""
        if not self._access_token:
            return False
        return time.time() < (self._expires_at - self._REFRESH_BUFFER_S)

    # ── Token Cache (disk persistence) ───────────────────────

    def _save_cached_token(self) -> None:
        """Save token to disk so it survives restarts.

        Audit pass 53: the whole read-modify-write cycle runs
        inside ``_CACHE_LOCK`` so two instances saving
        concurrently can't stomp on each other, AND the write
        goes to ``<path>.tmp`` + ``os.replace`` so a crash
        mid-write doesn't corrupt the shared cache file.
        """
        try:
            _TOKEN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.debug("Token cache dir create failed: %s", exc)
            return
        with _CACHE_LOCK:
            try:
                cache = self._load_all_cached()
                cache[self._shop_url] = {
                    "access_token": self._access_token,
                    "expires_at": self._expires_at,
                    "client_id": self._client_id[:8] + "..." if self._client_id else "",
                }
                tmp = _TOKEN_CACHE_FILE.with_suffix(_TOKEN_CACHE_FILE.suffix + ".tmp")
                tmp.write_text(json.dumps(cache, indent=2))
                os.replace(str(tmp), str(_TOKEN_CACHE_FILE))
                # Restrict file permissions — tokens are
                # sensitive. 0600 = owner read/write only.
                try:
                    os.chmod(str(_TOKEN_CACHE_FILE), 0o600)
                except OSError:
                    pass
            except OSError as exc:
                logger.debug("Token cache save failed: %s", exc)
                # Clean up half-written tmp.
                try:
                    tmp_path = _TOKEN_CACHE_FILE.with_suffix(_TOKEN_CACHE_FILE.suffix + ".tmp")
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass

    def _load_cached_token(self) -> None:
        """Load cached token from disk."""
        try:
            with _CACHE_LOCK:
                cache = self._load_all_cached()
            if self._shop_url in cache:
                entry = cache[self._shop_url]
                if not isinstance(entry, dict):
                    return
                token = entry.get("access_token", "")
                expires = entry.get("expires_at", 0)
                if not isinstance(expires, (int, float)):
                    return
                if token and time.time() < expires:
                    self._access_token = token
                    self._expires_at = expires
                    logger.info("Loaded cached token for %s (%.1fh remaining)",
                               self._shop_url, (expires - time.time()) / 3600)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _load_all_cached() -> dict[str, Any]:
        """Load the full token cache, with corrupted-file backup.

        Pre-audit a corrupted cache file (crash mid-write, or
        a manual edit) raised JSONDecodeError which leaked up
        past ``_load_cached_token``'s broad except, leaving
        the auth layer in a confused state. Now the corrupted
        file is moved to ``<path>.corrupted.<ts>`` and an
        empty cache is returned — same pattern as passes
        48/49/52. Audit pass 53.
        """
        if not _TOKEN_CACHE_FILE.exists():
            return {}
        try:
            data = json.loads(_TOKEN_CACHE_FILE.read_text())
            if not isinstance(data, dict):
                raise ValueError(
                    f"token cache is {type(data).__name__}, expected dict"
                )
            return data
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            try:
                backup = _TOKEN_CACHE_FILE.with_suffix(
                    _TOKEN_CACHE_FILE.suffix + f".corrupted.{int(time.time())}"
                )
                os.replace(str(_TOKEN_CACHE_FILE), str(backup))
                logger.warning(
                    "Corrupted token cache %s: %s — moved to %s",
                    _TOKEN_CACHE_FILE, exc, backup,
                )
            except OSError:
                logger.warning("Corrupted token cache %s: %s", _TOKEN_CACHE_FILE, exc)
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
