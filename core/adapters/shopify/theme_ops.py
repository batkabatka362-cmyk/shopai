"""ShopifyThemeOpsAdapter — theme CRUD + publish.

Companion to ``themes.py`` (LIST themes / LIST files / UPSERT
files). The lifecycle operations on the theme record itself —
install from a source URL, rename, publish (make active), and
delete — sit outside the existing read-side adapter.

ShopAI's storefront engine uses these for:

  * **Seasonal theme rollover.** Engine pulls down the holiday
    theme zip from the merchant's CDN, installs it via
    ``themeCreate(source: <url>)`` as UNPUBLISHED, runs theme-
    files upsert to swap brand assets, then publishes it the
    morning of the campaign.
  * **A/B theme tests.** Two themes installed side-by-side as
    UNPUBLISHED; engine flips between them by publishing the
    winner. Loser stays in the catalog ready to roll back.
  * **Cleanup.** Old seasonal themes get archived (DEMO role)
    and eventually deleted to clear the merchant's theme list.

Capabilities:

  * ``SHOPIFY_CREATE_THEME``  — themeCreate. Pattern A: source
    (URL of theme zip) + optional name + role at field level.
  * ``SHOPIFY_UPDATE_THEME``  — themeUpdate. Pattern A: id +
    input dict (currently only `name`).
  * ``SHOPIFY_PUBLISH_THEME`` — themePublish. Pattern A: id.
  * ``SHOPIFY_DELETE_THEME``  — themeDelete. Pattern A: id.

ThemeRole enum: MAIN / UNPUBLISHED / DEMO / DEVELOPMENT /
ARCHIVED / LOCKED. Most engine flows install as UNPUBLISHED
and flip to MAIN via ``themePublish`` rather than passing
role=MAIN to create.

UserError variants are all per-mutation (Theme*UserError, all
with ``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_THEME_FIELDS = """
id
name
role
processing
createdAt
updatedAt
""".strip()


_CREATE_THEME_MUTATION = f"""
mutation themeCreate($source: URL!, $name: String, $role: ThemeRole) {{
  themeCreate(source: $source, name: $name, role: $role) {{
    theme {{
      {_THEME_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_THEME_MUTATION = f"""
mutation themeUpdate($id: ID!, $input: OnlineStoreThemeInput!) {{
  themeUpdate(id: $id, input: $input) {{
    theme {{
      {_THEME_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_PUBLISH_THEME_MUTATION = f"""
mutation themePublish($id: ID!) {{
  themePublish(id: $id) {{
    theme {{
      {_THEME_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_THEME_MUTATION = """
mutation themeDelete($id: ID!) {
  themeDelete(id: $id) {
    deletedThemeId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_VALID_ROLES = {
    "MAIN", "UNPUBLISHED", "DEMO", "DEVELOPMENT", "ARCHIVED", "LOCKED",
}


class ShopifyThemeOpsAdapter(ShopifyBaseAdapter):
    name = "shopify_theme_ops"
    capabilities = {
        Capability.SHOPIFY_CREATE_THEME,
        Capability.SHOPIFY_UPDATE_THEME,
        Capability.SHOPIFY_PUBLISH_THEME,
        Capability.SHOPIFY_DELETE_THEME,
    }
    required_scopes = frozenset({"read_themes", "write_themes"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_THEME:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_THEME:
            return self._update(params)
        if capability == Capability.SHOPIFY_PUBLISH_THEME:
            return self._publish(params)
        if capability == Capability.SHOPIFY_DELETE_THEME:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        source = params.get("source") or params.get("source_url")
        if not isinstance(source, str) or not source.strip():
            raise AdapterValidationError(
                self.name,
                "'source' is required (URL of the theme zip — Shopify "
                "downloads it server-side)",
            )

        variables: dict[str, Any] = {
            "source": source.strip(),
            "name": None,
            "role": None,
        }

        name = params.get("name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise AdapterValidationError(
                    self.name, "'name' must be a non-empty string",
                )
            variables["name"] = name.strip()

        role = params.get("role")
        if role is not None:
            if not isinstance(role, str):
                raise AdapterValidationError(
                    self.name, "'role' must be a string",
                )
            up = role.strip().upper()
            if up not in _VALID_ROLES:
                raise AdapterValidationError(
                    self.name,
                    f"'role' must be one of {sorted(_VALID_ROLES)}",
                )
            variables["role"] = up

        data = self._gql(_CREATE_THEME_MUTATION, variables)
        self._check_user_errors(data, "themeCreate")
        payload = data.get("themeCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_THEME,
            data={
                "theme": self._normalise_theme(
                    payload.get("theme") or {}
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        theme_id = self._extract_id(params)
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                self.name,
                "'name' is required for update (the only patchable "
                "field on OnlineStoreThemeInput)",
            )
        data = self._gql(_UPDATE_THEME_MUTATION, {
            "id": theme_id,
            "input": {"name": name.strip()},
        })
        self._check_user_errors(data, "themeUpdate")
        payload = data.get("themeUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_THEME,
            data={
                "theme": self._normalise_theme(
                    payload.get("theme") or {}
                ),
            },
        )

    # ── Publish ────────────────────────────────────────────────────

    def _publish(self, params: dict[str, Any]) -> Any:
        theme_id = self._extract_id(params)
        data = self._gql(_PUBLISH_THEME_MUTATION, {"id": theme_id})
        self._check_user_errors(data, "themePublish")
        payload = data.get("themePublish") or {}
        return self._success(
            Capability.SHOPIFY_PUBLISH_THEME,
            data={
                "theme": self._normalise_theme(
                    payload.get("theme") or {}
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        theme_id = self._extract_id(params)
        data = self._gql(_DELETE_THEME_MUTATION, {"id": theme_id})
        self._check_user_errors(data, "themeDelete")
        payload = data.get("themeDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_THEME,
            data={
                "deleted_id": (
                    payload.get("deletedThemeId", "") or ""
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        theme_id = (
            params.get("id")
            or params.get("theme_id")
            or params.get("themeId")
        )
        if not isinstance(theme_id, str) or not theme_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the theme) is required",
            )
        return theme_id.strip()

    @staticmethod
    def _normalise_theme(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "role": node.get("role", "") or "",
            "processing": bool(node.get("processing", False)),
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
