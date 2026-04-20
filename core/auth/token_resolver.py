"""Token resolver — bridges legacy static tokens + 2026 OAuth.

Wave F D1 of IMPLEMENTATION_PLAN_2026. Shopify's public-app
OAuth flow mandates expiring access tokens (60 min) + long-
lived refresh tokens (90 days) starting 2026-04-01. Custom
apps still issue non-expiring tokens via the admin UI.

Until now ``ExpiringTokenAuth`` existed but nothing called
it — every Shopify request still read
``SHOPAI_SHOPIFY_KEY`` from env. This module is the one-line
activation path:

    token = resolve_access_token(shop)

Resolution order:

  1. If ``SHOPAI_SHOPIFY_CLIENT_ID`` + ``CLIENT_SECRET`` are
     set AND the expiring-token store has a record for
     ``shop``, auto-refresh and return the expiring access
     token.
  2. Otherwise fall back to ``SHOPAI_SHOPIFY_KEY`` (the
     legacy static custom-app token).

Returns ``""`` when neither source is configured — callers
treat that as "connector unavailable" and skip live writes.

Pure stdlib + ExpiringTokenAuth dependency. The resolver
caches the auth instance per client_id to avoid DB-open
churn; tests inject ``_reset_for_tests()``.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.auth.token_resolver")


_ENV_CLIENT_ID = "SHOPAI_SHOPIFY_CLIENT_ID"
_ENV_CLIENT_SECRET = "SHOPAI_SHOPIFY_CLIENT_SECRET"
_ENV_LEGACY_KEY = "SHOPAI_SHOPIFY_KEY"


_LOCK = threading.Lock()
_AUTH_CACHE: dict[str, Any] = {}


def _make_auth(
    *,
    client_id: str,
    client_secret: str,
) -> Any:
    from core.auth.shopify_expiring_token import (
        ExpiringTokenAuth,
    )
    return ExpiringTokenAuth(
        client_id=client_id,
        client_secret=client_secret,
    )


def _get_auth() -> Any:
    """Return a cached ExpiringTokenAuth instance when the
    OAuth env is configured, else None."""
    client_id = os.environ.get(_ENV_CLIENT_ID, "")
    client_secret = os.environ.get(_ENV_CLIENT_SECRET, "")
    if not client_id or not client_secret:
        return None
    cache_key = client_id
    with _LOCK:
        auth = _AUTH_CACHE.get(cache_key)
        if auth is None:
            try:
                auth = _make_auth(
                    client_id=client_id,
                    client_secret=client_secret,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "ExpiringTokenAuth init failed: %s",
                    exc,
                )
                return None
            _AUTH_CACHE[cache_key] = auth
        return auth


def resolve_access_token(shop: str) -> str:
    """Return a valid access token for ``shop`` or '' when
    nothing is configured."""
    if not shop:
        return os.environ.get(_ENV_LEGACY_KEY, "")
    auth = _get_auth()
    if auth is not None:
        try:
            token = auth.get_access_token(shop)
            if token:
                return token
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "expiring-token path failed for %s: %s",
                shop, exc,
            )
    # Legacy fallback
    return os.environ.get(_ENV_LEGACY_KEY, "")


def has_oauth_config() -> bool:
    return bool(
        os.environ.get(_ENV_CLIENT_ID, "")
        and os.environ.get(_ENV_CLIENT_SECRET, ""),
    )


def source_for(shop: str) -> str:
    """Diagnostic: where did we get the token from?"""
    if has_oauth_config():
        auth = _get_auth()
        if auth is not None:
            try:
                status = auth.token_status(shop)
                if status.get("status") not in (
                    "not_installed", None,
                ):
                    return "expiring_oauth"
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "token_status: %s", exc,
                )
    if os.environ.get(_ENV_LEGACY_KEY, ""):
        return "legacy_static"
    return "none"


def _reset_for_tests() -> None:
    with _LOCK:
        _AUTH_CACHE.clear()
