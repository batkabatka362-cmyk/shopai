"""ShopifyAppsAdapter — installed app introspection.

The compatibility engine asks "what other apps are installed on
this shop?" so it can:

  * Detect conflicts (e.g. another subscription app already
    installed → don't double-bill).
  * Discover collaborator apps to delegate work to.
  * Surface missing-app diagnostics ("you're missing a fulfillment
    app for this region").

Capabilities (read-only — installing apps is a merchant-driven OAuth
flow that's outside autonomous-AI scope):

  * ``SHOPIFY_GET_CURRENT_APP_INSTALLATION`` — read OUR own app's
    installation record (scopes granted, metafields, accessible
    locations). Engines hit this at startup to confirm the right
    OAuth scopes are present before queuing work.
  * ``SHOPIFY_LIST_APP_INSTALLATIONS`` — list every installed app on
    the shop.

Pattern E note: ``Query.appInstallations`` requires the
``read_apps`` scope (granted automatically to apps installed at the
"Plus" tier or higher, plus a couple of other gated cases). Stores
without the scope hit a precise ACCESS_DENIED. The
``currentAppInstallation`` query is always available — it returns
the calling app's own installation record.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_INSTALLATION_FIELDS = """
id
launchUrl
uninstallUrl
accessScopes {
  handle
  description
}
app {
  id
  title
  handle
  apiKey
  developerName
  embedded
  appStoreAppUrl
  appStoreDeveloperUrl
  installUrl
  description
  installation {
    id
  }
}
""".strip()


_GET_CURRENT_APP_INSTALLATION_QUERY = f"""
query currentAppInstallation {{
  currentAppInstallation {{
    {_INSTALLATION_FIELDS}
  }}
}}
""".strip()


_LIST_APP_INSTALLATIONS_QUERY = f"""
query appInstallations(
  $first: Int!,
  $after: String,
  $category: AppInstallationCategory,
  $privacy: AppInstallationPrivacy
) {{
  appInstallations(
    first: $first,
    after: $after,
    category: $category,
    privacy: $privacy
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_INSTALLATION_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250

_VALID_CATEGORIES = {"CHANNEL", "POS_EMBEDDED"}
_VALID_PRIVACIES = {"PUBLIC", "PRIVATE"}


class ShopifyAppsAdapter(ShopifyBaseAdapter):
    name = "shopify_apps"
    capabilities = {
        Capability.SHOPIFY_GET_CURRENT_APP_INSTALLATION,
        Capability.SHOPIFY_LIST_APP_INSTALLATIONS,
    }
    # `read_apps` is granted automatically to apps installed at
    # the org-level Partner dashboard (see file docstring).
    required_scopes = frozenset({"read_apps"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_GET_CURRENT_APP_INSTALLATION:
            return self._get_current(params)
        if capability == Capability.SHOPIFY_LIST_APP_INSTALLATIONS:
            return self._list(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Get current installation ──────────────────────────────────

    def _get_current(self, _params: dict[str, Any]) -> Any:
        data = self._gql(_GET_CURRENT_APP_INSTALLATION_QUERY, {})
        node = data.get("currentAppInstallation") or {}
        return self._success(
            Capability.SHOPIFY_GET_CURRENT_APP_INSTALLATION,
            data={
                "installation": self._normalise_installation(node),
                "found": bool(node),
            },
        )

    # ── List ──────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                self.name, "'cursor' must be a string or None",
            )

        variables: dict[str, Any] = {"first": limit, "after": cursor}

        category = params.get("category")
        if category is not None:
            if not isinstance(category, str) or category not in _VALID_CATEGORIES:
                raise AdapterValidationError(
                    self.name,
                    f"'category' must be one of: {sorted(_VALID_CATEGORIES)}",
                )
            variables["category"] = category

        privacy = params.get("privacy")
        if privacy is not None:
            if not isinstance(privacy, str) or privacy not in _VALID_PRIVACIES:
                raise AdapterValidationError(
                    self.name,
                    f"'privacy' must be one of: {sorted(_VALID_PRIVACIES)}",
                )
            variables["privacy"] = privacy

        data = self._gql(_LIST_APP_INSTALLATIONS_QUERY, variables)
        envelope = data.get("appInstallations") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        installations = [
            self._normalise_installation(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_APP_INSTALLATIONS,
            data={
                "installations": installations,
                "count": len(installations),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_installation(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        app = node.get("app") or {}
        scopes_raw = node.get("accessScopes") or []
        scopes = [
            s.get("handle", "") or ""
            for s in scopes_raw
            if isinstance(s, dict) and s.get("handle")
        ]
        return {
            "installation_id": node.get("id", "") or "",
            "launch_url": node.get("launchUrl", "") or "",
            "uninstall_url": node.get("uninstallUrl", "") or "",
            "access_scopes": scopes,
            "app_id": (
                app.get("id", "") if isinstance(app, dict) else ""
            ) or "",
            "app_title": (
                app.get("title", "") if isinstance(app, dict) else ""
            ) or "",
            "app_handle": (
                app.get("handle", "") if isinstance(app, dict) else ""
            ) or "",
            "api_key": (
                app.get("apiKey", "") if isinstance(app, dict) else ""
            ) or "",
            "developer_name": (
                app.get("developerName", "")
                if isinstance(app, dict) else ""
            ) or "",
            "embedded": bool(
                app.get("embedded", False)
                if isinstance(app, dict) else False
            ),
            "app_store_url": (
                app.get("appStoreAppUrl", "")
                if isinstance(app, dict) else ""
            ) or "",
            "app_store_developer_url": (
                app.get("appStoreDeveloperUrl", "")
                if isinstance(app, dict) else ""
            ) or "",
            "install_url": (
                app.get("installUrl", "")
                if isinstance(app, dict) else ""
            ) or "",
            "description": (
                app.get("description", "")
                if isinstance(app, dict) else ""
            ) or "",
        }
