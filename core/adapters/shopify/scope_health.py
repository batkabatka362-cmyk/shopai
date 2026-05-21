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

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.logger import get_logger

from core.adapters.shopify.scope_registry import all_required_scopes

logger = get_logger("adapters.shopify.scope_health")


# ── Cache location ─────────────────────────────────────────────
#
# Snapshot of the most recent live drift check, written by
# CLI / autonomous-loop callers and consumed by cron-able
# read-only surfaces (daily-brief) that can't afford their own
# Shopify round-trip.
#
# Path follows the ``SHOPAI_DATA_DIR`` env-var convention used
# elsewhere in the codebase (alert_history.json,
# quarantine_state.json) -- defaults to ``./data`` when unset.
_CACHE_FILENAME = ".scope_health.json"


def _cache_path() -> Path:
    """Resolve the cache file location each call so tests can
    point ``SHOPAI_DATA_DIR`` at ``tmp_path``."""
    base = os.environ.get("SHOPAI_DATA_DIR") or "data"
    return Path(base) / _CACHE_FILENAME


def _is_test_environment() -> bool:
    """Pattern J guard: tests should not pollute the production
    cache file. Tests that exercise save behaviour monkeypatch
    this back to ``False`` (typically combined with redirecting
    ``SHOPAI_DATA_DIR`` to ``tmp_path``)."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def save_report_to_cache(report: "ScopeHealthReport") -> bool:
    """Persist a snapshot of the live drift check.

    Cron-able read-only surfaces (daily-brief, world-model
    bulk renders) want to *show* current scope drift without
    making a Shopify round-trip on every render. They read
    from this cache. Live callers (CLI / autonomous loop)
    refresh it.

    The saved shape is intentionally JSON-primitive (no
    frozensets) so the file is human-readable and forward-
    compatible if the dataclass evolves.

    Args:
        report: The successful comparison to persist.

    Returns:
        True on successful write, False on any failure
        (missing dir, permission denied, disk full,
        serialisation error). Never raises -- the cache is
        non-critical; the live check already happened.

    Pattern J: short-circuits under pytest so unit tests
    that exercise ``compare_to_live`` via the CLI surface
    don't write to the dev ``data/`` directory. Tests that
    DO need to exercise the save path monkeypatch
    ``_is_test_environment`` to ``False``.
    """
    if _is_test_environment():
        return False

    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": time.time(),
            "is_healthy": bool(report.is_healthy),
            "granted_count": len(report.granted_scopes),
            "required_count": len(report.required_scopes),
            "missing_from_app": list(report.missing_from_app),
            "extra_in_app": list(report.extra_in_app),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.debug(
            "scope_health cache write failed: %s", exc,
        )
        return False


def load_report_from_cache() -> dict | None:
    """Read the most recent cached snapshot.

    Returns:
        A dict with ``generated_at``, ``is_healthy``,
        ``granted_count``, ``required_count``,
        ``missing_from_app``, ``extra_in_app`` on success.
        ``None`` when the cache is missing, malformed, or
        unreadable.

    Fails open: callers see "no cached data" rather than a
    stack trace.
    """
    try:
        path = _cache_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug(
            "scope_health cache read failed: %s", exc,
        )
        return None
    if not isinstance(data, dict):
        return None
    # Defensive: ensure required keys present with sane types.
    try:
        return {
            "generated_at": float(data.get("generated_at", 0.0)),
            "is_healthy": bool(data.get("is_healthy", False)),
            "granted_count": int(data.get("granted_count", 0)),
            "required_count": int(data.get("required_count", 0)),
            "missing_from_app": [
                str(s) for s in data.get("missing_from_app") or []
            ],
            "extra_in_app": [
                str(s) for s in data.get("extra_in_app") or []
            ],
        }
    except (TypeError, ValueError) as exc:
        logger.debug(
            "scope_health cache malformed: %s", exc,
        )
        return None


@dataclass(frozen=True)
class ScopeHealthReport:
    """Live vs declared scope comparison."""

    granted_scopes: frozenset[str]
    required_scopes: frozenset[str]
    missing_from_app: list[str]
    extra_in_app: list[str]
    is_healthy: bool


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

    return ScopeHealthReport(
        granted_scopes=granted,
        required_scopes=required,
        missing_from_app=missing,
        extra_in_app=extra,
        is_healthy=not missing,
    )
