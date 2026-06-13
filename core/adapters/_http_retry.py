"""Shared HTTP retry helper for adapter bases (W962-65).

Extracts the retry contract documented in Pattern Adapter-Retry
audit so each adapter base doesn't duplicate ~80 lines of
identical retry logic.

Contract:
  - 3 retries (configurable) on 429 / 5xx / transient transport
    errors (Timeout, ConnectionError, ChunkedEncoding, SSL,
    ProtocolError, RemoteDisconnected)
  - Exponential backoff: min(2^attempt, 8) seconds
  - Retry-After header honored on 429 (capped at 30s)
  - 4xx (other than 429) raises immediately -- caller bug
  - Empty-body 2xx returns {} instead of raising on JSON parse

The caller passes a `request_fn` thunk that performs ONE HTTP
call + returns a response-like object exposing
``status_code``, ``text``, ``headers``, and ``json()``. The
helper wraps the call in the retry loop and raises typed
AdapterError subclasses.

Usage from an adapter base:

    from core.adapters._http_retry import http_retry

    def _http_post(self, url, body, headers):
        return http_retry(
            lambda: requests.post(
                url, json=body, headers=headers,
                timeout=self.timeout,
            ),
            adapter_name=self.name,
            timeout=self.timeout,
        )
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from .errors import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
)

logger = logging.getLogger(__name__)

# requests is optional -- we only need Timeout / ConnectionError
# class references when it's present.
try:
    import requests as _requests  # type: ignore[import-not-found]
    _REQUESTS_AVAILABLE = True
except ImportError:
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


_TRANSIENT_MSG_TOKENS = (
    "chunkedencoding",
    "ssl",
    "protocol",
    "remote disconnected",
)


def http_retry(
    request_fn: Callable[[], Any],
    *,
    adapter_name: str,
    timeout: float = 30.0,
    max_retries: int = 3,
    parse_json: bool = True,
) -> Any:
    """Execute ``request_fn()`` with retry on 429 / 5xx /
    transient transport errors. Returns parsed JSON (if
    ``parse_json``) or the raw response.

    Args:
        request_fn: Thunk that performs ONE HTTP call.
        adapter_name: Used in AdapterError messages.
        timeout: For error-message context (the actual
            timeout lives inside ``request_fn``).
        max_retries: Total attempts (so 3 = 1 + 2 retries).
        parse_json: When True, returns response.json() or {}
            on empty body. When False, returns the response
            object.

    Raises:
        AdapterTimeout, AdapterUnavailable, AdapterRateLimited,
        AdapterAuthError, AdapterError -- typed by failure class.
    """
    if not _REQUESTS_AVAILABLE:
        raise AdapterUnavailable(
            adapter_name, "'requests' library not installed",
        )
    last_exc: Exception | None = None
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            response = request_fn()
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            last_exc = exc
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 8))
                continue
            raise AdapterTimeout(
                adapter_name,
                f"timeout after {timeout}s: {exc}",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            last_exc = exc
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 8))
                continue
            raise AdapterUnavailable(
                adapter_name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            msg = str(exc).lower()
            if any(
                t in msg for t in _TRANSIENT_MSG_TOKENS
            ) and attempt < max_retries:
                time.sleep(min(2 ** attempt, 8))
                continue
            raise AdapterError(
                adapter_name,
                f"HTTP request failed: {type(exc).__name__}: {exc}",
            ) from exc

        status = getattr(response, "status_code", 0)
        if status >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if status in (401, 403):
                raise AdapterAuthError(
                    adapter_name,
                    f"vendor rejected credentials ({status}): {snippet}",
                )
            if status == 429:
                retry_after_hdr = response.headers.get(
                    "Retry-After", "1",
                ) if hasattr(response, "headers") else "1"
                try:
                    wait = float(retry_after_hdr)
                except (TypeError, ValueError):
                    wait = 1.0
                if attempt < max_retries:
                    time.sleep(min(wait, 30))
                    continue
                raise AdapterRateLimited(
                    adapter_name,
                    f"rate limit (429): {snippet}",
                )
            if 500 <= status < 600:
                if attempt < max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterUnavailable(
                    adapter_name,
                    f"vendor 5xx ({status}): {snippet}",
                )
            # 4xx other than 429 / 401 / 403 -- caller bug;
            # raise immediately, no retry.
            raise AdapterError(
                adapter_name,
                f"vendor returned {status}: {snippet}",
            )

        # 2xx success path
        if not parse_json:
            return response
        # Empty body -> return empty dict
        text = getattr(response, "text", "") or ""
        if not text:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise AdapterError(
                adapter_name,
                f"invalid JSON response: {exc}",
            ) from exc

    # Should not reach -- the for-else equivalent
    raise AdapterError(
        adapter_name,
        f"exhausted retries: {last_exc}"
        if last_exc else "exhausted retries",
    )
