"""SharedHTTPClient — stdlib-only HTTP helper with retry, back-off, and circuit breaker.

Uses :mod:`urllib.request` so there are zero external dependencies.
Thread-safe; a single instance is meant to be shared across adapters.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

# W962-69: response-size ceiling. Without this, a hostile or
# misbehaving upstream returning a multi-GB body would OOM the
# process. 16 MB is plenty for any Shopify Admin / ads-API
# response we ever see in production; a real response that hits
# this cap is the bug to investigate, not the cap to raise.
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class ResponseTooLarge(Exception):
    """Raised when an HTTP response exceeds ``_MAX_RESPONSE_BYTES``."""


class CircuitOpen(Exception):
    """Raised when the circuit breaker is open and requests are short-circuited."""


class SharedHTTPClient:
    """Reusable HTTP client with retry, exponential back-off, and circuit breaker.

    Parameters
    ----------
    max_retries:
        Maximum number of *retry* attempts (total attempts = 1 + max_retries).
    backoff_base:
        Base delay in seconds for exponential back-off (delay = base * 2^attempt).
    circuit_failure_threshold:
        Consecutive failures before the circuit opens.
    circuit_cooldown:
        Seconds to wait before allowing a probe request through an open circuit.
    default_timeout:
        Default per-request timeout in seconds.
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        circuit_failure_threshold: int = 5,
        circuit_cooldown: float = 30.0,
        default_timeout: float = 15.0,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_cooldown = circuit_cooldown
        self.default_timeout = default_timeout

        # Circuit-breaker state (keyed per host)
        self._circuits: dict[str, _CircuitState] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        data: Any = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request with retries and circuit-breaker protection.

        Returns
        -------
        dict with keys ``status`` (int), ``headers`` (dict), ``body`` (str),
        and ``json`` (parsed body when applicable, else ``None``).
        """
        host = self._extract_host(url)
        timeout = timeout or self.default_timeout

        last_error: Exception | None = None
        for attempt in range(1 + self.max_retries):
            # --- circuit breaker gate ---
            self._check_circuit(host)

            try:
                result = self._single_request(method, url, headers, data, timeout)
                self._record_success(host)
                return result

            except CircuitOpen:
                raise

            except Exception as exc:
                last_error = exc
                self._record_failure(host)

                # Honour Retry-After header if present in urllib error
                retry_after = self._parse_retry_after(exc)
                if retry_after is not None and attempt < self.max_retries:
                    time.sleep(min(retry_after, 60.0))
                    continue

                if attempt < self.max_retries:
                    delay = self.backoff_base * (2 ** attempt)
                    time.sleep(delay)

        raise last_error or RuntimeError("request failed with no captured error")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _single_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None,
        data: Any,
        timeout: float,
    ) -> dict[str, Any]:
        """One attempt — no retry logic."""
        encoded_data: bytes | None = None
        req_headers = dict(headers) if headers else {}

        if data is not None:
            if isinstance(data, (dict, list)):
                encoded_data = json.dumps(data).encode("utf-8")
                req_headers.setdefault("Content-Type", "application/json")
            elif isinstance(data, str):
                encoded_data = data.encode("utf-8")
            elif isinstance(data, bytes):
                encoded_data = data

        req = urllib.request.Request(
            url, data=encoded_data, headers=req_headers, method=method.upper()
        )

        resp = urllib.request.urlopen(req, timeout=timeout)
        # W962-69: cap response size. Read ONE extra byte so we
        # can distinguish "at exactly the limit" from "exceeded".
        raw = resp.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ResponseTooLarge(
                f"response exceeded {_MAX_RESPONSE_BYTES} bytes from {url}"
            )
        body = raw.decode("utf-8", errors="replace")
        resp_headers = {k: v for k, v in resp.getheaders()}

        parsed_json = None
        content_type = resp_headers.get("Content-Type", "")
        if "json" in content_type or body.startswith(("{", "[")):
            try:
                parsed_json = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                pass

        return {
            "status": resp.status,
            "headers": resp_headers,
            "body": body,
            "json": parsed_json,
        }

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def _check_circuit(self, host: str) -> None:
        with self._lock:
            state = self._circuits.get(host)
            if state is None:
                return
            if state.consecutive_failures >= self.circuit_failure_threshold:
                elapsed = time.monotonic() - state.last_failure_time
                if elapsed < self.circuit_cooldown:
                    raise CircuitOpen(
                        f"Circuit open for {host}: {state.consecutive_failures} "
                        f"consecutive failures, cooldown {self.circuit_cooldown - elapsed:.1f}s remaining"
                    )
                # Cooldown elapsed — allow a probe request (half-open)

    def _record_success(self, host: str) -> None:
        with self._lock:
            state = self._circuits.get(host)
            if state is not None:
                state.consecutive_failures = 0

    def _record_failure(self, host: str) -> None:
        with self._lock:
            if host not in self._circuits:
                self._circuits[host] = _CircuitState()
            state = self._circuits[host]
            state.consecutive_failures += 1
            state.last_failure_time = time.monotonic()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_host(url: str) -> str:
        """Cheaply extract the host portion from a URL."""
        after_scheme = url.split("://", 1)[-1]
        host = after_scheme.split("/", 1)[0].split(":")[0]
        return host

    @staticmethod
    def _parse_retry_after(exc: Exception) -> float | None:
        """Try to read a Retry-After header from an HTTP error response."""
        if isinstance(exc, urllib.error.HTTPError):
            val = exc.headers.get("Retry-After") if exc.headers else None
            if val is not None:
                try:
                    return float(val)
                except ValueError:
                    pass
        return None


class _CircuitState:
    """Mutable state for one circuit-breaker (per host)."""
    __slots__ = ("consecutive_failures", "last_failure_time")

    def __init__(self) -> None:
        self.consecutive_failures: int = 0
        self.last_failure_time: float = 0.0
