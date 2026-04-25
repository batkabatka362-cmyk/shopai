"""Pre-ship brand gate — one canonical entry point.

Content sites (ad_copy generator, email templates, publisher,
blog post generator) all want the same thing: "check this
draft against the brand; reject if it fails; log either way."

This module bundles that into one call + handles the three
operational modes: ``reject`` (default — block on error),
``warn`` (log but still ship), ``log`` (silent; just record).

Metafields are fetched once per session and memoised — brand
rules rarely change mid-session. Callers can force a reload
via ``reload_brand_rules()`` after a live brand edit.

Usage:

    from core.brand.pre_ship import brand_gate

    verdict = brand_gate(
        text=draft,
        surface="ad_copy",
        mode="reject",  # raise if errors
        trace_id="ad-campaign-123",
    )
    # verdict.passed == True — ship the draft
    # verdict.issues — always populated (errors + warnings)

Internal engines that can't raise can use ``mode="warn"``;
owner-driven flows ("launch this campaign now") should use
``mode="reject"``.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
from typing import Any, Iterable

from core.brand.brand_guard import BrandCheck, BrandGuard


_logger = logging.getLogger("shopai.brand.pre_ship")


class BrandGateRejected(RuntimeError):
    """Raised by ``brand_gate(mode="reject")`` when the
    content violates one or more ERROR-severity brand rules.
    Carries the underlying ``BrandCheck`` so callers can log
    the specific issues."""

    def __init__(self, check: BrandCheck) -> None:
        self.check = check
        super().__init__(
            f"brand_gate rejected {check.surface} — "
            f"{len(check.errors)} error(s): "
            + ", ".join(i.code for i in check.errors),
        )


@dataclasses.dataclass(frozen=True)
class GateVerdict:
    """Outcome of a brand gate call."""
    surface: str
    passed: bool
    text_length: int
    errors: tuple[dict[str, str], ...]
    warnings: tuple[dict[str, str], ...]
    trace_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "passed": self.passed,
            "text_length": self.text_length,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "trace_id": self.trace_id,
        }


# ── Module state ──────────────────────────────────────


_lock = threading.Lock()
_cached_guard: BrandGuard | None = None


def _get_guard(
    metafields: Iterable[dict[str, Any]] | None,
) -> BrandGuard:
    """Return a memoised BrandGuard. Explicit metafields
    override the cache for one call (tests pass
    metafields directly)."""
    global _cached_guard
    if metafields is not None:
        return BrandGuard.from_metafields(metafields)
    with _lock:
        if _cached_guard is None:
            loaded = _load_brand_metafields()
            _cached_guard = BrandGuard.from_metafields(loaded)
        return _cached_guard


def _load_brand_metafields() -> list[dict[str, Any]]:
    """Best-effort fetch of the live ``shopai.brand`` +
    ``shopai.seo_defaults`` metafields. When the bridge or
    adapter isn't available, returns an empty list → neutral
    rules (no errors ever fire), matching the "graceful
    degradation" contract."""
    try:
        from core.adapters.shopify_admin.client import (
            ShopifyAdminClient,
        )
    except Exception:  # noqa: BLE001
        return []
    try:
        client = ShopifyAdminClient.from_env()
    except Exception as exc:  # noqa: BLE001
        _logger.debug(
            "brand metafield fetch skipped "
            "(no client): %s", exc,
        )
        return []
    try:
        result = client.get(
            "metafields.json",
            params={"namespace": "shopai"},
        )
    except Exception as exc:  # noqa: BLE001
        _logger.debug(
            "brand metafield fetch failed: %s", exc,
        )
        return []
    rows = result.get("metafields") or []
    return [r for r in rows if isinstance(r, dict)]


def reload_brand_rules() -> None:
    """Drop the memoised guard — next gate call refetches
    from Shopify. Call after an owner edits the brand
    metafields mid-session."""
    global _cached_guard
    with _lock:
        _cached_guard = None


# ── Public entry ──────────────────────────────────────


def brand_gate(
    *,
    text: str,
    surface: str,
    mode: str = "reject",
    trace_id: str = "",
    metafields: Iterable[dict[str, Any]] | None = None,
) -> GateVerdict:
    """Check content, log, optionally raise.

    ``mode`` options:
      * ``"reject"`` — raise ``BrandGateRejected`` on any
        ERROR issue. Ship only when ``verdict.passed``.
      * ``"warn"``   — never raise; log errors as warnings,
        return the verdict. Callers inspect ``passed``.
      * ``"log"``    — never raise; don't emit warning logs.
        Useful for background drafts / offline learning.

    ``trace_id`` — free-form correlation id (campaign name,
    order id, etc.). Copied through to the verdict + log
    lines so owner can trace a rejection back to the
    originating call.
    """
    if mode not in ("reject", "warn", "log"):
        raise ValueError(
            "mode must be 'reject', 'warn', or 'log'",
        )
    guard = _get_guard(metafields)
    check = guard.check_content(text, surface=surface)
    verdict = GateVerdict(
        surface=check.surface,
        passed=check.passed,
        text_length=check.text_length,
        errors=tuple(
            {
                "code": i.code,
                "reason": i.reason,
                "context": i.context,
            }
            for i in check.errors
        ),
        warnings=tuple(
            {
                "code": i.code,
                "reason": i.reason,
                "context": i.context,
            }
            for i in check.warnings
        ),
        trace_id=str(trace_id or ""),
    )

    # Logging path.
    if check.errors and mode != "log":
        _logger.warning(
            "brand_gate %s (trace=%s) FAIL: %s",
            surface,
            trace_id or "-",
            ", ".join(
                f"{i.code}:{i.reason}" for i in check.errors
            ),
        )
    elif check.warnings and mode == "warn":
        _logger.info(
            "brand_gate %s (trace=%s) warnings: %s",
            surface,
            trace_id or "-",
            ", ".join(i.code for i in check.warnings),
        )

    if mode == "reject" and not check.passed:
        raise BrandGateRejected(check)
    return verdict
