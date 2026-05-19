"""Brand asset uploader -- logo + favicon for autonomous
store branding.

Every Shopify store needs visual identity at launch:
  * Logo (header)
  * Favicon (browser tab icon)
  * Optional: hero image, og:image for social sharing

This module wraps the EXISTING ``SHOPIFY_UPLOAD_FILE`` adapter
(URL-based fileCreate) into a brand-aware orchestrator. The
operator (or autonomous controller) supplies public URLs and
this module pushes them to Shopify Files where the theme can
reference them.

What "real measurable outcome" looks like here::

    {
        "uploaded_count": 2,
        "files": [
            {"asset": "logo",
             "url": "https://...", "file_id": "gid://...",
             "alt": "Acme Beauty logo"},
            {"asset": "favicon",
             "url": "https://...", "file_id": "gid://...",
             "alt": "Acme Beauty favicon"},
        ],
        "missing_assets": [],
        "ok": True,
    }

After this PR ships, the launch checklist gains a measurable
"brand_assets" check that ``launch_audit`` can verify by
listing Shopify Files for the expected alt-text patterns.

Records via Pattern Z so every upload attempt feeds Phase 8's
learning loop -- if logos consistently fail to upload due to
URL-size issues, the learning system surfaces it.
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# The brand asset types we know how to upload. Extending this
# tuple is a deliberate API change -- the alt-text convention
# below has to be maintained or launch_audit won't recognise
# the assets later.
_BRAND_ASSETS: tuple[str, ...] = (
    "logo",
    "favicon",
    "hero",
    "og_image",
)


def upload_brand_assets(
    *,
    store_name: str,
    logo_url: str | None = None,
    favicon_url: str | None = None,
    hero_url: str | None = None,
    og_image_url: str | None = None,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Push the brand asset URLs through the file adapter.

    Args:
        store_name: Used to build alt text per asset.
        logo_url: Public HTTPS URL for the logo (required for
            a launchable store; missing = ``ok: False``).
        favicon_url: Public HTTPS URL for the favicon. Missing
            is acceptable but flagged.
        hero_url: Optional hero image.
        og_image_url: Optional social-sharing image.
        store_id: Optional per-store recording scope.

    Returns:
        ``{uploaded_count, files, missing_assets, ok}``.
        ``ok`` is True only when at LEAST the logo + favicon
        uploaded successfully (the minimum for a launchable
        storefront).
    """
    name = (store_name or "").strip()
    if not name:
        return {
            "uploaded_count": 0,
            "files": [],
            "missing_assets": list(_BRAND_ASSETS),
            "ok": False,
            "error": "store_name_required",
        }

    asset_urls = {
        "logo": (logo_url or "").strip() or None,
        "favicon": (favicon_url or "").strip() or None,
        "hero": (hero_url or "").strip() or None,
        "og_image": (og_image_url or "").strip() or None,
    }
    # The minimum viable set for "ok"
    required = {"logo", "favicon"}

    router = _get_router()
    capability = _get_capability()

    files_input: list[dict[str, Any]] = []
    asset_by_url: dict[str, str] = {}
    for asset, url in asset_urls.items():
        if not url:
            continue
        alt = _build_alt(name, asset)
        files_input.append({
            "url": url,
            "alt": alt,
            "type": "IMAGE",
        })
        asset_by_url[url] = asset

    missing_assets = [
        a for a in _BRAND_ASSETS if not asset_urls.get(a)
    ]

    if not files_input:
        return {
            "uploaded_count": 0,
            "files": [],
            "missing_assets": missing_assets,
            "ok": False,
            "error": "no_asset_urls_provided",
        }

    if router is None or capability is None:
        _record_summary(
            uploaded=0, missing=missing_assets,
            store_id=store_id, ok=False,
            error="router_unavailable",
        )
        return {
            "uploaded_count": 0,
            "files": [],
            "missing_assets": missing_assets,
            "ok": False,
            "error": "router_unavailable",
        }

    try:
        adapter_result = router.execute(
            capability,
            {"files": files_input},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brand_uploader router.execute raised: %s", exc,
        )
        _record_summary(
            uploaded=0, missing=missing_assets,
            store_id=store_id, ok=False,
            error=f"adapter_raise: {exc}",
        )
        return {
            "uploaded_count": 0,
            "files": [],
            "missing_assets": missing_assets,
            "ok": False,
            "error": f"adapter_raise: {exc}",
        }

    if not getattr(adapter_result, "ok", False):
        err = getattr(adapter_result, "error", "rejected")
        _record_summary(
            uploaded=0, missing=missing_assets,
            store_id=store_id, ok=False,
            error=str(err),
        )
        return {
            "uploaded_count": 0,
            "files": [],
            "missing_assets": missing_assets,
            "ok": False,
            "error": str(err),
        }

    data_payload = getattr(adapter_result, "data", {}) or {}
    uploaded_files = data_payload.get("files") or []

    files_out: list[dict[str, Any]] = []
    uploaded_assets: set[str] = set()
    for f in uploaded_files:
        if not isinstance(f, dict):
            continue
        url = f.get("preview_url") or f.get("url") or ""
        file_id = f.get("id") or ""
        alt = f.get("alt") or ""
        asset_label = _asset_from_alt(alt)
        if asset_label:
            uploaded_assets.add(asset_label)
        files_out.append({
            "asset": asset_label or "unknown",
            "url": url,
            "file_id": file_id,
            "alt": alt,
        })

    # ``ok`` requires logo + favicon at minimum.
    ok = required.issubset(uploaded_assets)
    final_missing = [
        a for a in _BRAND_ASSETS
        if a not in uploaded_assets
    ]
    _record_summary(
        uploaded=len(uploaded_files),
        missing=final_missing,
        store_id=store_id,
        ok=ok,
        error=None,
    )
    return {
        "uploaded_count": len(uploaded_files),
        "files": files_out,
        "missing_assets": final_missing,
        "ok": ok,
        "error": None,
    }


# ── Helpers ─────────────────────────────────────────────────


def _build_alt(store_name: str, asset: str) -> str:
    """Stable alt-text convention: ``<store> <asset>`` so
    ``launch_audit`` can identify uploaded brand assets in
    Shopify Files later.

    Examples::

        Acme Beauty logo
        Acme Beauty favicon
    """
    return f"{store_name} {asset}".strip()


def _asset_from_alt(alt: str) -> str | None:
    """Reverse of :func:`_build_alt` -- extract the brand
    asset label from the alt text Shopify echoes back."""
    if not isinstance(alt, str):
        return None
    lowered = alt.lower().strip()
    for asset in _BRAND_ASSETS:
        suffix = f" {asset}"
        if lowered.endswith(suffix):
            return asset
    return None


def _record_summary(
    *,
    uploaded: int,
    missing: list[str],
    store_id: str | None,
    ok: bool,
    error: str | None,
) -> None:
    params: dict[str, Any] = {
        "uploaded_count": uploaded,
        "missing_assets": list(missing),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="upload_brand_assets",
            capability="SHOPIFY_UPLOAD_FILE",
            params=params,
            success=ok,
            error=error,
            metrics={
                "uploaded_count": uploaded,
                "missing_assets": list(missing),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brand_uploader record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brand_uploader router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPLOAD_FILE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brand_uploader capability resolve failed: %s",
            exc,
        )
        return None
