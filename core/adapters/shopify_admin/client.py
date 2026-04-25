"""Canonical Shopify Admin API HTTP wrapper.

Single source of truth for retry / rate-limit / auth logic
across every shopify_admin resource module. Consolidates the
four concurrent clients that drifted across the codebase
(bridge, scripts, store_manager, automation).

Rate-limit handling: Shopify's standard plan allows 2 REST
req/s sustained + a 40-call bucket. We hit 429 ``Retry-After``
headers + back off exponentially; burst protection stays
caller-side (GraphQL's cost system handled per-call by
``graphql_cost_exceeded`` error parsing).

Pure stdlib. No dependency on ``requests`` so the operator
scripts can import this without pulling HTTP infra into a
reduced-dep deploy.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger("shopai.shopify_admin")


#: Default API version — stable + current as of 2026-04.
#: Shopify deprecates quarterly; bump this constant in one
#: place when we migrate.
DEFAULT_API_VERSION = "2024-10"


class ShopifyAdminError(RuntimeError):
    """Any Shopify-reported failure the client couldn't retry
    past (auth, 4xx logical errors, malformed envelope)."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        body: str = "",
        path: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.path = path


class ShopifyAdminMisconfigured(RuntimeError):
    """Missing ``SHOPAI_SHOPIFY_URL`` / ``SHOPAI_SHOPIFY_KEY``
    at construction. Callers typically want to print a
    friendly message + exit rather than propagate."""


@dataclass(frozen=True)
class ShopifyAdminClient:
    """Stateless HTTP wrapper. Instances are cheap — construct
    one per script / engine call without worrying about
    sharing. Rate-limit backoff is per-request (no in-process
    bucket tracking), which is safe for the expected
    engine-call rate (< 10/s from any one caller).

    ``url`` = bare host (no scheme).
    ``token`` = admin API access token.
    ``api_version`` = stable REST path segment.
    """

    url: str
    token: str
    api_version: str = DEFAULT_API_VERSION
    retries: int = 4
    throttle_s: float = 0.0
    user_agent: str = "ShopAI-Admin/1.0"

    # ── Constructors ────────────────────────────────────

    @classmethod
    def from_env(
        cls,
        *,
        api_version: str = DEFAULT_API_VERSION,
        throttle_s: float = 0.0,
    ) -> "ShopifyAdminClient":
        url = (os.environ.get("SHOPAI_SHOPIFY_URL") or "").strip()
        token = (
            os.environ.get("SHOPAI_SHOPIFY_KEY")
            or os.environ.get("SHOPAI_SHOPIFY_TOKEN")
            or ""
        ).strip()
        if not url or not token:
            raise ShopifyAdminMisconfigured(
                "set SHOPAI_SHOPIFY_URL + SHOPAI_SHOPIFY_KEY",
            )
        return cls(
            url=url, token=token,
            api_version=api_version,
            throttle_s=throttle_s,
        )

    @classmethod
    def from_env_or_exit(
        cls, **kw: Any,
    ) -> "ShopifyAdminClient":
        try:
            return cls.from_env(**kw)
        except ShopifyAdminMisconfigured as exc:
            print(f"ERR: {exc}", file=sys.stderr)
            sys.exit(2)

    # ── Public REST surface ─────────────────────────────

    def get(
        self, path: str, *, params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._send("GET", path, params=params)

    def post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._send("POST", path, body=body, params=params)

    def put(
        self,
        path: str,
        body: dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._send("PUT", path, body=body, params=params)

    def delete(
        self, path: str, *, params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._send("DELETE", path, params=params)

    # ── GraphQL ─────────────────────────────────────────

    def graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST to ``/admin/api/{ver}/graphql.json``. Parses
        ``errors`` + ``userErrors`` — anything non-empty
        surfaces as ``ShopifyAdminError``.

        Caller still has to walk ``data.<mutationName>
        .userErrors`` for mutation-specific error arrays;
        we only parse top-level ``errors`` + any
        ``throttled`` cost issues."""
        body = {"query": query}
        if variables:
            body["variables"] = variables
        result = self._send("POST", "graphql.json", body=body)

        top_errors = result.get("errors")
        if top_errors:
            # Shopify returns a list of {message, extensions{code}}
            msg = "; ".join(
                str(e.get("message") or e)
                for e in top_errors
            )
            raise ShopifyAdminError(
                f"GraphQL error: {msg}",
                path="graphql.json",
                body=json.dumps(top_errors),
            )
        return result

    # ── HTTP plumbing (internal) ────────────────────────

    def _url(self, path: str) -> str:
        """Build a full URL for ``/admin/api/{ver}/{path}``.

        ``path`` may start with ``/`` or not — normalised.
        Callers pointing at the bare ``/admin/oauth/*``
        surface use ``_url_admin`` instead (this client
        doesn't expose oauth endpoints yet)."""
        p = path.lstrip("/")
        return (
            f"https://{self.url}/admin/api/"
            f"{self.api_version}/{p}"
        )

    def _send(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        full = self._url(path)
        if params:
            # Keep GraphQL JSON body but attach params to URL
            # when present (some admin endpoints use both).
            qs = urllib.parse.urlencode(
                [
                    (k, str(v))
                    for k, v in params.items()
                    if v is not None
                ],
                doseq=True,
            )
            full = f"{full}?{qs}" if qs else full

        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "X-Shopify-Access-Token": self.token,
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(
                    full, data=data, headers=headers,
                    method=method,
                )
                with urllib.request.urlopen(
                    req, timeout=30,
                ) as resp:
                    raw = resp.read()
                    if self.throttle_s > 0:
                        time.sleep(self.throttle_s)
                    if not raw:
                        return {}
                    try:
                        return json.loads(raw)
                    except (TypeError, ValueError) as exc:
                        raise ShopifyAdminError(
                            f"Shopify returned non-JSON: "
                            f"{exc}",
                            path=path,
                            body=(
                                raw.decode(
                                    "utf-8", errors="replace",
                                )[:500]
                            ),
                        )
            except urllib.error.HTTPError as exc:
                last_exc = exc
                snippet = self._read_error_body(exc)
                if exc.code == 429:
                    retry_after = (
                        self._parse_retry_after(exc)
                        or (2 ** (attempt + 1))
                    )
                    if attempt < self.retries - 1:
                        _logger.info(
                            "shopify 429 on %s %s — "
                            "retry in %ss",
                            method, path, retry_after,
                        )
                        time.sleep(retry_after)
                        continue
                if exc.code in (502, 503, 504):
                    if attempt < self.retries - 1:
                        wait = 2 ** (attempt + 1)
                        _logger.info(
                            "shopify %s on %s %s — retry "
                            "in %ss",
                            exc.code, method, path, wait,
                        )
                        time.sleep(wait)
                        continue
                # 4xx non-retryable → structured error
                raise ShopifyAdminError(
                    f"Shopify {exc.code} on {method} "
                    f"{path}: {snippet}",
                    status=exc.code, body=snippet, path=path,
                ) from exc
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt < self.retries - 1:
                    wait = 2 ** (attempt + 1)
                    _logger.info(
                        "shopify net err on %s %s — retry "
                        "in %ss",
                        method, path, wait,
                    )
                    time.sleep(wait)
                    continue
                raise ShopifyAdminError(
                    f"Shopify network error on "
                    f"{method} {path}: {exc}",
                    path=path,
                ) from exc
        # Fell through retries
        if last_exc is not None:
            raise ShopifyAdminError(
                f"Shopify retries exhausted on "
                f"{method} {path}: {last_exc}",
                path=path,
            )
        raise ShopifyAdminError(
            f"Shopify retries exhausted on {method} {path}",
            path=path,
        )

    @staticmethod
    def _read_error_body(exc: urllib.error.HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _parse_retry_after(
        exc: urllib.error.HTTPError,
    ) -> float | None:
        try:
            ra = exc.headers.get("Retry-After")
            if ra is None:
                return None
            return float(ra)
        except (TypeError, ValueError):
            return None
