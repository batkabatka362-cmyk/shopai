"""Live OAuth scope health check.

The OAuth scope registry (PRs #173-#178) declares what scopes
the app needs. The CI gate (PR #177) prevents new adapters from
landing without a declaration. The install manifest generator
(PR #178) emits the deployable config fragment.

But none of that catches the runtime discrepancy: a merchant
might have installed the app with an older / stripped-down set
of scopes than the current code requires. The first symptom is
adapters failing with ACCESS_DENIED at random times — a slow
and confusing debug path.

This module closes that gap. It calls Shopify's
``currentAppInstallation { accessScopes }`` API via the apps
adapter, compares the live granted scopes against the declared
manifest, and reports:

  - **missing_from_app**: scopes the registry declares we need
    but the live install doesn't have. These adapters WILL fail
    at runtime. Operator action: re-request scopes or remove
    the requiring adapters.

  - **extra_in_app**: scopes the live install has but the
    registry doesn't declare. Over-requesting — Shopify review
    will flag this for review-required apps; for managed-install
    apps it's just unused noise. Operator action: regenerate
    the install manifest and re-submit.

  - **is_healthy**: True when missing_from_app is empty. We
    tolerate extras because they don't break functionality —
    they're only a code-review issue.

The check is read-only and best-effort: missing credentials,
adapter init failure, or GraphQL errors all return ``None``
instead of raising. Callers see "no live data available" and
decide what to do.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

from core.adapters.shopify.scope_registry import (
    all_required_scopes,
    collect_manifest,
)

logger = get_logger("adapters.shopify.scope_health")


@dataclass(frozen=True)
class ScopeHealthReport:
    """Live vs declared scope comparison.

    ``missing_adapters`` maps each missing scope to the
    adapter(s) that declared a need for it -- the blast
    radius of the drift. When ``missing_from_app`` lists
    ``read_customers``, ``missing_adapters["read_customers"]``
    lists the adapters whose live calls will fail with
    ``ACCESS_DENIED`` until the install is re-authorized.
    Empty dict when the drift is healthy.
    """

    granted_scopes: frozenset[str]
    required_scopes: frozenset[str]
    missing_from_app: list[str]
    extra_in_app: list[str]
    is_healthy: bool
    missing_adapters: dict[str, list[str]] = field(default_factory=dict)


def compare_to_live(adapter: Any = None) -> ScopeHealthReport | None:
    """Compare the registry's declared scopes against what
    Shopify reports the live app installation actually has.

    Args:
        adapter: Optional pre-constructed
            :class:`ShopifyAppsAdapter` instance — used by tests
            to inject a mock. Production callers pass ``None``
            and the function instantiates one from the configured
            credentials.

    Returns:
        A :class:`ScopeHealthReport` when the live API call
        succeeds, or ``None`` when:
          - The apps adapter cannot be constructed / is not
            configured (no credentials available)
          - The Shopify call fails (network, auth, schema)
          - The response is malformed

        Failing to None instead of raising keeps the CLI surface
        useful in dev environments without live Shopify auth —
        operators see a friendly "no live data" rather than a
        stack trace.
    """
    if adapter is None:
        try:
            from core.adapters.shopify.apps import ShopifyAppsAdapter
            adapter = ShopifyAppsAdapter()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apps adapter init failed: %s", exc,
            )
            return None
        if not adapter.is_configured():
            logger.debug("apps adapter not configured")
            return None

    try:
        from core.adapters.base import Capability
        result = adapter.execute(
            Capability.SHOPIFY_GET_CURRENT_APP_INSTALLATION,
            {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "current_app_installation call failed: %s", exc,
        )
        return None

    if not getattr(result, "ok", False):
        logger.debug(
            "current_app_installation returned not-ok: %s",
            getattr(result, "error", "unknown"),
        )
        return None

    data = getattr(result, "data", {}) or {}
    if not isinstance(data, dict):
        return None
    raw_scopes = data.get("access_scopes")
    if not isinstance(raw_scopes, list):
        return None

    granted = frozenset(
        str(s).strip() for s in raw_scopes if str(s).strip()
    )
    required = all_required_scopes()

    missing = sorted(required - granted)
    extra = sorted(granted - required)

    # Build blast radius: which adapters will fail with
    # ACCESS_DENIED because the scope they need isn't granted.
    # Empty when healthy. Belt-and-braces: a registry import /
    # collect failure shouldn't break the live check -- we still
    # return the granted/missing comparison, just without the
    # adapter resolution.
    missing_adapters: dict[str, list[str]] = {}
    if missing:
        try:
            manifest = collect_manifest()
            for scope in missing:
                adapters = manifest.by_scope.get(scope, [])
                if adapters:
                    missing_adapters[scope] = list(adapters)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "scope_health adapter resolution raised: %s", exc,
            )

    return ScopeHealthReport(
        granted_scopes=granted,
        required_scopes=required,
        missing_from_app=missing,
        extra_in_app=extra,
        is_healthy=not missing,
        missing_adapters=missing_adapters,
    )
