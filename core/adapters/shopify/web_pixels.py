"""ShopifyWebPixelsAdapter — install / configure custom tracking pixels.

Web pixels are Shopify's modern replacement for ``script_tag``-based
analytics injection. They run in a sandboxed iframe (no DOM access),
subscribe to the Shopify customer-events stream (page_viewed, cart_
viewed, checkout_completed, etc.), and forward events to whatever
analytics destination the merchant configured.

ShopAI's ads-spy → launch flow ships campaigns with UTMs; the
attribution side needs a pixel that captures checkout events and
forwards them to the ad platform's conversion API. Without this
adapter the pixel install was a manual app-config step; engines
that wanted to swap pixel destinations or A/B-test pixel logic had
to be done by hand.

Capabilities (CRUD on the pixel record itself; pixel JS code lives
in the app):

  * ``SHOPIFY_CREATE_WEB_PIXEL``  — install a pixel.
  * ``SHOPIFY_UPDATE_WEB_PIXEL``  — change its settings JSON.
  * ``SHOPIFY_DELETE_WEB_PIXEL``  — uninstall.

The pixel's ``settings`` blob is an arbitrary JSON object the
merchant's app reads at runtime to configure behaviour (e.g.
``{"meta_pixel_id": "1234", "events": ["checkout_completed"]}``).
The adapter accepts a Python dict and JSON-encodes it on the wire,
since Shopify expects a string here.
"""
from __future__ import annotations

import json
from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_WEB_PIXEL_FIELDS = """
id
settings
""".strip()


_CREATE_WEB_PIXEL_MUTATION = f"""
mutation webPixelCreate($webPixel: WebPixelInput!) {{
  webPixelCreate(webPixel: $webPixel) {{
    webPixel {{
      {_WEB_PIXEL_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_WEB_PIXEL_MUTATION = f"""
mutation webPixelUpdate($id: ID!, $webPixel: WebPixelInput!) {{
  webPixelUpdate(id: $id, webPixel: $webPixel) {{
    webPixel {{
      {_WEB_PIXEL_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_WEB_PIXEL_MUTATION = """
mutation webPixelDelete($id: ID!) {
  webPixelDelete(id: $id) {
    deletedWebPixelId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifyWebPixelsAdapter(ShopifyBaseAdapter):
    name = "shopify_web_pixels"
    capabilities = {
        Capability.SHOPIFY_CREATE_WEB_PIXEL,
        Capability.SHOPIFY_UPDATE_WEB_PIXEL,
        Capability.SHOPIFY_DELETE_WEB_PIXEL,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_WEB_PIXEL:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_WEB_PIXEL:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_WEB_PIXEL:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        settings = self._build_settings(params, where="create")
        data = self._gql(_CREATE_WEB_PIXEL_MUTATION, {
            "webPixel": {"settings": settings},
        })
        self._check_user_errors(data, "webPixelCreate")
        payload = data.get("webPixelCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_WEB_PIXEL,
            data={
                "web_pixel": self._normalise_pixel(
                    payload.get("webPixel") or {}
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        pixel_id = params.get("id") or params.get("web_pixel_id")
        if not isinstance(pixel_id, str) or not pixel_id.strip():
            raise AdapterValidationError(
                "shopify_web_pixels",
                "'id' (Shopify GID for the web pixel) is required",
            )
        settings = self._build_settings(params, where="update")
        data = self._gql(_UPDATE_WEB_PIXEL_MUTATION, {
            "id": pixel_id.strip(),
            "webPixel": {"settings": settings},
        })
        self._check_user_errors(data, "webPixelUpdate")
        payload = data.get("webPixelUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_WEB_PIXEL,
            data={
                "web_pixel": self._normalise_pixel(
                    payload.get("webPixel") or {}
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        pixel_id = params.get("id") or params.get("web_pixel_id")
        if not isinstance(pixel_id, str) or not pixel_id.strip():
            raise AdapterValidationError(
                "shopify_web_pixels",
                "'id' (Shopify GID for the web pixel) is required",
            )
        data = self._gql(_DELETE_WEB_PIXEL_MUTATION, {
            "id": pixel_id.strip(),
        })
        self._check_user_errors(data, "webPixelDelete")
        payload = data.get("webPixelDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_WEB_PIXEL,
            data={
                "deleted_id": payload.get("deletedWebPixelId", "") or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _build_settings(params: dict[str, Any], *, where: str) -> str:
        """Coerce a friendly ``settings`` dict (or pre-serialised
        string) into the JSON-string form Shopify wants on the wire.

        Friendly form::

            {"settings": {"meta_pixel_id": "1234",
                          "events": ["checkout_completed"]}}

        OR::

            {"settings": '{"meta_pixel_id": "1234"}'}    # already JSON

        Anything else (None, list, int) is rejected — the WebPixelInput
        schema only accepts a JSON object string.
        """
        settings = params.get("settings")
        if settings is None:
            raise AdapterValidationError(
                "shopify_web_pixels",
                f"{where}: 'settings' is required (dict or JSON string)",
            )
        if isinstance(settings, str):
            # Pre-serialised — validate it's valid JSON to fail early
            # rather than ship a malformed payload.
            try:
                json.loads(settings)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_web_pixels",
                    f"{where}: 'settings' string must be valid JSON",
                ) from exc
            return settings
        if isinstance(settings, dict):
            try:
                return json.dumps(settings, separators=(",", ":"))
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_web_pixels",
                    f"{where}: 'settings' dict not JSON-serialisable",
                ) from exc
        raise AdapterValidationError(
            "shopify_web_pixels",
            f"{where}: 'settings' must be a dict or a JSON string, "
            f"got {type(settings).__name__}",
        )

    @staticmethod
    def _normalise_pixel(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        # ``settings`` comes back as a JSON-encoded string; parse so
        # callers can read fields with normal dict access.
        settings_raw = node.get("settings", "") or ""
        if isinstance(settings_raw, str) and settings_raw.strip():
            try:
                settings = json.loads(settings_raw)
            except (TypeError, ValueError):
                settings = settings_raw  # surface the raw string if malformed
        else:
            settings = settings_raw
        return {
            "id": node.get("id", "") or "",
            "settings": settings,
        }
