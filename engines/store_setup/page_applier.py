"""Push generated storefront pages to Shopify via the
``SHOPIFY_CREATE_PAGE`` adapter.

Workflow::

    from engines.store_setup.page_generator import generate_pages
    from engines.store_setup.page_applier import apply_pages

    pages = generate_pages(
        store_name="Acme Beauty", niche="beauty",
    )
    result = apply_pages(pages)

Each page is pushed via a separate adapter call so a failure
in one doesn't block the others. Records via Pattern Z so
every push enters Phase 8's learning loop.

Handles are derived deterministically from titles so the same
title always lands at the same URL (``/pages/about``,
``/pages/contact``, etc.).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


def _slug(title: str) -> str:
    """Title -> URL handle. Lowercase + hyphen-separated."""
    s = (title or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "page"


def apply_pages(
    pages: dict[str, str],
    *,
    store_id: str | None = None,
    published: bool = True,
) -> dict[str, Any]:
    """Push each generated page via the create-page adapter.

    Args:
        pages: ``{title: html_body}`` dict from
            ``page_generator.generate_pages``.
        store_id: Optional store_id for per-store scope on
            the writeback recorder.
        published: When True (default), the pages publish
            immediately. When False, they're saved as draft.

    Returns:
        ``{
            "applied_count": int,
            "results": list[dict],
        }`` -- one dict per page: ``{title, handle, ok, error}``.
    """
    if not isinstance(pages, dict) or not pages:
        return {"applied_count": 0, "results": []}

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        results = [
            {
                "title": title,
                "handle": _slug(title),
                "ok": False,
                "error": "router_unavailable",
            }
            for title in sorted(pages)
        ]
        for r in results:
            _record(
                title=r["title"], handle=r["handle"],
                success=False, store_id=store_id,
                error=r["error"],
            )
        return {"applied_count": 0, "results": results}

    results: list[dict[str, Any]] = []
    applied_count = 0
    for title, body in sorted(pages.items()):
        handle = _slug(title)
        try:
            adapter_result = router.execute(
                capability,
                {
                    "title": title,
                    "body_html": body,
                    "handle": handle,
                    "published": published,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "page_applier: router.execute raised for %s: %s",
                title, exc,
            )
            results.append({
                "title": title,
                "handle": handle,
                "ok": False,
                "error": f"adapter_raise: {exc}",
            })
            _record(
                title=title, handle=handle, success=False,
                store_id=store_id, error=str(exc),
            )
            continue

        ok = bool(getattr(adapter_result, "ok", False))
        error = getattr(adapter_result, "error", None)
        if ok:
            applied_count += 1
            results.append({
                "title": title,
                "handle": handle,
                "ok": True,
                "error": None,
            })
            _record(
                title=title, handle=handle, success=True,
                store_id=store_id, error=None,
            )
        else:
            results.append({
                "title": title,
                "handle": handle,
                "ok": False,
                "error": str(error or "rejected"),
            })
            _record(
                title=title, handle=handle, success=False,
                store_id=store_id,
                error=str(error or "rejected"),
            )

    return {
        "applied_count": applied_count,
        "results": results,
    }


# --- helpers --------------------------------------------------


def _record(
    *,
    title: str,
    handle: str,
    success: bool,
    store_id: str | None,
    error: str | None,
) -> None:
    params: dict[str, Any] = {
        "title": title,
        "handle": handle,
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_storefront_page",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={"page_title": title, "handle": handle},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "page_applier record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters.router import AdapterRouter
        return AdapterRouter()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "page_applier router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "page_applier capability resolve failed: %s", exc,
        )
        return None
