"""Shopify themes + theme assets.

Unlocks **creative auto-deploy** — Schema.org JSON-LD blocks,
custom CSS, Liquid snippets can be pushed programmatically
rather than through admin copy-paste. Used by the SEO +
content engines to auto-update the storefront without a human
in the loop.

Two resources:

  * ``Themes`` — top-level theme CRUD. Every store has exactly
    one ``role=main`` theme (what's live) + optional
    ``role=unpublished`` drafts. ``publish`` swaps roles.
  * ``ThemeAssets`` — files inside a theme (snippets/,
    templates/, sections/, assets/, layout/, locales/, config/).
    Create / update = upsert (Shopify overwrites by ``key``);
    delete removes the file.

Safety rails:
  * Publishing a theme is a §4b.G CRITICAL action — the risk
    gate should intercept any push that would swap the main
    theme. This module surfaces the op; gating happens at
    call sites.
  * ``update_asset`` with ``value`` (text) is idempotent —
    same value → same stored state. ``attachment`` (base64)
    path left to callers since binary assets are a tiny
    fraction of our writes.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger("shopai.shopify_admin.themes")


#: Shopify theme roles. The main theme is customer-visible;
#: unpublished themes are drafts; demo is for Shopify
#: theme-store previews (rare in our flows).
_VALID_ROLES = {"main", "unpublished", "demo"}


class Themes:
    """Theme list / get / publish / create / destroy."""

    @staticmethod
    def list_themes(
        client: ShopifyAdminClient,
        *,
        role: str = "",
        fields: str = "",
    ) -> list[dict[str, Any]]:
        """``role`` filter: main / unpublished / demo. Empty
        returns every theme."""
        params: dict[str, Any] = {}
        if role:
            if role not in _VALID_ROLES:
                raise ValueError(
                    f"role must be in {sorted(_VALID_ROLES)}",
                )
            params["role"] = role
        if fields:
            params["fields"] = fields
        result = client.get(
            "themes.json", params=params or None,
        )
        rows = result.get("themes") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient, theme_id: int | str,
        *, fields: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = fields
        result = client.get(
            f"themes/{theme_id}.json",
            params=params or None,
        )
        theme = result.get("theme")
        if not isinstance(theme, dict):
            raise ShopifyAdminError(
                f"theme {theme_id} not returned",
                path=f"themes/{theme_id}.json",
            )
        return theme

    @staticmethod
    def get_main(
        client: ShopifyAdminClient,
    ) -> dict[str, Any] | None:
        """Return the currently-live theme, or None on a
        store with no main theme assigned (pathological but
        we defend)."""
        themes = Themes.list_themes(client, role="main")
        return themes[0] if themes else None

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        name: str,
        src: str = "",
        role: str = "unpublished",
    ) -> dict[str, Any]:
        """Create a theme. ``src`` optional — can be a ZIP
        URL Shopify fetches to import. Default role is
        ``unpublished`` so the new theme isn't customer-
        visible until an explicit ``publish`` call.
        """
        if not name:
            raise ValueError("name: required")
        if role not in _VALID_ROLES:
            raise ValueError(
                f"role must be in {sorted(_VALID_ROLES)}",
            )
        body: dict[str, Any] = {
            "theme": {"name": name, "role": role},
        }
        if src:
            body["theme"]["src"] = src
        result = client.post("themes.json", body)
        created = result.get("theme")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "theme not returned by create",
                path="themes.json", body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        theme_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Partial update — ``name`` + ``role`` are the
        common writable fields. Switching ``role=main`` is
        equivalent to ``publish`` (risk_gate should gate it
        either way at call sites)."""
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"themes/{theme_id}.json",
            {"theme": {
                "id": int(theme_id), **fields,
            }},
        )
        updated = result.get("theme")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "theme not returned by update",
                path=f"themes/{theme_id}.json",
            )
        return updated

    @staticmethod
    def publish(
        client: ShopifyAdminClient,
        theme_id: int | str,
    ) -> dict[str, Any]:
        """Make this theme the live one. Shopify auto-moves
        the previous main to unpublished. CRITICAL action —
        risk_gate should intercept at call sites."""
        return Themes.update(
            client, theme_id, fields={"role": "main"},
        )

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        theme_id: int | str,
    ) -> None:
        """Only unpublished/demo themes are deletable —
        Shopify rejects deleting the main theme."""
        client.delete(f"themes/{theme_id}.json")


class ThemeAssets:
    """Files inside a theme — templates, sections, snippets,
    assets, layout, locales, config."""

    @staticmethod
    def list_assets(
        client: ShopifyAdminClient,
        theme_id: int | str,
        *,
        fields: str = "",
    ) -> list[dict[str, Any]]:
        """Returns list of ``{key, content_type, public_url,
        size, checksum, created_at, updated_at}`` — no
        content. Use ``get_asset(key=...)`` to download one."""
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = fields
        result = client.get(
            f"themes/{theme_id}/assets.json",
            params=params or None,
        )
        rows = result.get("assets") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get_asset(
        client: ShopifyAdminClient,
        theme_id: int | str,
        *, key: str,
    ) -> dict[str, Any]:
        """Download one asset by ``key`` (e.g.
        ``snippets/shopai-schema.liquid``). Response includes
        ``value`` (text) or ``attachment`` (base64)."""
        if not key:
            raise ValueError("key: required")
        result = client.get(
            f"themes/{theme_id}/assets.json",
            params={"asset[key]": key},
        )
        asset = result.get("asset")
        if not isinstance(asset, dict):
            raise ShopifyAdminError(
                f"asset {key!r} not returned from "
                f"theme {theme_id}",
                path=f"themes/{theme_id}/assets.json",
            )
        return asset

    @staticmethod
    def upsert_asset(
        client: ShopifyAdminClient,
        theme_id: int | str,
        *,
        key: str,
        value: str = "",
        src_url: str = "",
    ) -> dict[str, Any]:
        """Create or overwrite a text-based asset. Idempotent
        per §4b.D — retry lands on the same content.

        Exactly one of:
          * ``value``   — inline text (most common — Liquid
                          snippet, CSS, JSON config)
          * ``src_url`` — publicly-fetchable URL Shopify
                          server-downloads (images typically)

        Binary ``attachment`` (base64) path left to callers
        that specifically need it; too rare in our flows to
        warrant a helper yet.
        """
        if not key:
            raise ValueError("key: required")
        if bool(value) == bool(src_url):
            raise ValueError(
                "exactly one of value / src_url required",
            )
        body: dict[str, Any] = {"asset": {"key": key}}
        if value:
            body["asset"]["value"] = value
        else:
            body["asset"]["src"] = src_url
        result = client.put(
            f"themes/{theme_id}/assets.json", body,
        )
        asset = result.get("asset")
        if not isinstance(asset, dict):
            raise ShopifyAdminError(
                "asset not returned by upsert",
                path=f"themes/{theme_id}/assets.json",
                body=str(result),
            )
        return asset

    @staticmethod
    def delete_asset(
        client: ShopifyAdminClient,
        theme_id: int | str,
        *,
        key: str,
    ) -> None:
        """Delete an asset by key. Shopify restores the
        theme-default on main theme files (e.g. removing a
        snippet that overrode a default)."""
        if not key:
            raise ValueError("key: required")
        client.delete(
            f"themes/{theme_id}/assets.json",
            params={"asset[key]": key},
        )
