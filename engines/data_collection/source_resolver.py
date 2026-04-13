"""Data Collection Engine — source resolver.

Determines which APIs/sources to call based on requested source names,
resolves endpoints, auth types, and rate limits.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Known source registry
# ---------------------------------------------------------------------------

_SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "shopify": {
        "endpoint": "/api/shopify/v1",
        "auth_type": "oauth2",
        "rate_limit": 40,
        "priority": 1,
    },
    "analytics": {
        "endpoint": "/api/analytics/v1",
        "auth_type": "api_key",
        "rate_limit": 100,
        "priority": 2,
    },
    "google_ads": {
        "endpoint": "/api/google-ads/v1",
        "auth_type": "oauth2",
        "rate_limit": 30,
        "priority": 3,
    },
    "meta_ads": {
        "endpoint": "/api/meta-ads/v1",
        "auth_type": "oauth2",
        "rate_limit": 30,
        "priority": 3,
    },
    "stripe": {
        "endpoint": "/api/stripe/v1",
        "auth_type": "api_key",
        "rate_limit": 50,
        "priority": 2,
    },
}


def resolve_sources(
    requested_sources: list[str],
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve requested source names to API configurations.

    Args:
        requested_sources: List of source name strings.
        filters: Optional filters to narrow source scope.

    Returns:
        Structured dict with resolved sources and any unresolved names.
    """
    try:
        sources = copy.deepcopy(requested_sources)
        resolved: list[dict[str, Any]] = []
        unresolved: list[str] = []

        for src_name in sources:
            name_lower = src_name.lower().strip()
            if name_lower in _SOURCE_REGISTRY:
                cfg = _SOURCE_REGISTRY[name_lower]
                resolved.append({
                    "name": name_lower,
                    "endpoint": cfg["endpoint"],
                    "auth_type": cfg["auth_type"],
                    "rate_limit": cfg["rate_limit"],
                    "priority": cfg["priority"],
                })
            else:
                unresolved.append(src_name)

        # Sort by priority (lower = higher priority)
        resolved.sort(key=lambda s: s["priority"])

        return {
            "status": "success",
            "resolved": resolved,
            "unresolved": unresolved,
            "total_resolved": len(resolved),
        }
    except Exception as exc:
        return {
            "status": "error",
            "resolved": [],
            "unresolved": [],
            "error": f"Source resolution failed: {exc}",
        }
