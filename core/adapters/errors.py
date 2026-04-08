"""Adapter error hierarchy.

Every external-API failure mode that an adapter can encounter is
represented as a typed exception so callers can write narrow
``except`` clauses instead of catching ``Exception`` and parsing
error strings. The base class ``AdapterError`` is what
``BaseAdapter.execute`` raises in its ``AdapterResult`` envelope.

The taxonomy is intentionally small — adapters should classify
the failure when they translate vendor errors, not invent new
subclasses. If a vendor returns "billing limit reached" the
adapter should raise ``AdapterQuotaExhausted``, not a custom
``MyVendorBillingError``.
"""
from __future__ import annotations


class AdapterError(Exception):
    """Base class for every adapter-layer failure.

    Carries the adapter name + a short reason string. Subclasses
    add semantics so the smart router can react differently
    (retry, fall back, circuit-break, etc.) without parsing the
    message.
    """

    def __init__(self, adapter: str, reason: str = "") -> None:
        self.adapter = adapter
        self.reason = reason
        super().__init__(f"{adapter}: {reason}" if reason else adapter)


class AdapterNotConfigured(AdapterError):
    """Adapter is registered but cannot run — missing API key,
    missing credentials, missing local model file, etc. The router
    treats this as "skip and try the next one" rather than a
    real failure."""


class AdapterUnavailable(AdapterError):
    """Adapter is configured but the vendor's HTTP endpoint is
    unreachable (network error, DNS failure, 5xx, timeout). The
    router will trigger the circuit breaker and route to a
    fallback adapter."""


class AdapterRateLimited(AdapterError):
    """Adapter hit the vendor's rate limit (HTTP 429 or vendor
    equivalent). Carries an optional ``retry_after`` (seconds)
    so the router can either back off or fail over."""

    def __init__(
        self,
        adapter: str,
        reason: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(adapter, reason)
        self.retry_after = retry_after


class AdapterQuotaExhausted(AdapterError):
    """The free-tier (or budget) quota for this adapter has been
    burned for the day/month and there is no point retrying. The
    router will permanently disable this adapter for the current
    quota window and fall back."""


class AdapterAuthError(AdapterError):
    """Vendor rejected the credentials (HTTP 401/403). The router
    treats this like ``AdapterNotConfigured`` — skip and route to
    the next available adapter — and surfaces a loud warning so
    operators can rotate the key."""


class AdapterValidationError(AdapterError):
    """The adapter could not satisfy the request — bad capability,
    missing required params, malformed payload. This is a caller
    bug, not a vendor outage, so the router does NOT fall back."""


class AdapterTimeout(AdapterError):
    """The vendor accepted the request but did not respond within
    the adapter's deadline. Treated like ``AdapterUnavailable``
    by the router."""
