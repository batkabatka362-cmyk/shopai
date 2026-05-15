"""ShopifyMobilePlatformAppAdapter — mobile app deep-link CRUD.

A "mobile platform application" is the merchant's iOS or Android app
registration with Shopify. The registration tells Shopify which
bundle id / app id maps to the storefront and unlocks deep linking
(universal links on iOS, app links on Android), shared web
credentials, and App Clips. Without it, customers tapping a product
URL in iOS Mail or Android Chrome land on the web storefront
instead of the merchant's app.

ShopAI's onboarding engine uses these whenever a merchant says
"we just shipped our iOS app, register the bundle id and turn on
universal links so the existing email campaigns deep-link in".

Capabilities:

  * ``SHOPIFY_LIST_MOBILE_PLATFORM_APPLICATIONS`` — paginated list.
    Returns mixed Android + Apple apps; the union variant is
    surfaced via ``platform`` field on each.
  * ``SHOPIFY_GET_MOBILE_PLATFORM_APPLICATION``  — single app by GID.
  * ``SHOPIFY_CREATE_MOBILE_PLATFORM_APPLICATION`` —
    mobilePlatformApplicationCreate. xor between
    ``android`` and ``apple`` sub-inputs.
  * ``SHOPIFY_UPDATE_MOBILE_PLATFORM_APPLICATION`` —
    mobilePlatformApplicationUpdate. Same xor.
  * ``SHOPIFY_DELETE_MOBILE_PLATFORM_APPLICATION``.

Friendly call shape (Android create)::

    {"platform":                 "android",
     "application_id":           "com.example.shop",
     "sha256_cert_fingerprints": ["AB:CD:EF:..."],
     "app_links_enabled":        True}

Friendly call shape (Apple create)::

    {"platform":                       "apple",
     "app_id":                         "TEAMID.com.example.shop",
     "universal_links_enabled":        True,
     "shared_web_credentials_enabled": True,
     "app_clips_enabled":              False}

Pattern A — id at field level on update + delete; create takes the
``input`` wrapper (with android xor apple sub-input).
Pattern F — MobilePlatformApplicationUserError carries `code`.
Pattern (union response) — MobilePlatformApplication is a UNION
(AndroidApplication | AppleApplication); selections need inline
fragments per concrete type. Same shape pattern as Phase 26.5's
SubscriptionDiscount union remove.

Pattern E note: gated by ``write_mobile_platform_applications`` /
``read_mobile_platform_applications``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_APP_FIELDS = """
__typename
... on AndroidApplication {
  id
  applicationId
  sha256CertFingerprints
  appLinksEnabled
}
... on AppleApplication {
  id
  appId
  universalLinksEnabled
  sharedWebCredentialsEnabled
  appClipsEnabled
  appClipApplicationId
}
""".strip()


_LIST_QUERY = f"""
query mobilePlatformApplications(
  $first: Int!,
  $after: String,
  $reverse: Boolean
) {{
  mobilePlatformApplications(
    first: $first, after: $after, reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_APP_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_QUERY = f"""
query mobilePlatformApplication($id: ID!) {{
  mobilePlatformApplication(id: $id) {{
    {_APP_FIELDS}
  }}
}}
""".strip()


_CREATE_MUTATION = f"""
mutation mobilePlatformApplicationCreate(
  $input: MobilePlatformApplicationCreateInput!
) {{
  mobilePlatformApplicationCreate(input: $input) {{
    mobilePlatformApplication {{
      {_APP_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_MUTATION = f"""
mutation mobilePlatformApplicationUpdate(
  $id: ID!,
  $input: MobilePlatformApplicationUpdateInput!
) {{
  mobilePlatformApplicationUpdate(id: $id, input: $input) {{
    mobilePlatformApplication {{
      {_APP_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_MUTATION = """
mutation mobilePlatformApplicationDelete($id: ID!) {
  mobilePlatformApplicationDelete(id: $id) {
    deletedMobilePlatformApplicationId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250
_VALID_PLATFORMS = {"android", "apple"}


class ShopifyMobilePlatformAppAdapter(ShopifyBaseAdapter):
    name = "shopify_mobile_platform_app"
    capabilities = {
        Capability.SHOPIFY_LIST_MOBILE_PLATFORM_APPLICATIONS,
        Capability.SHOPIFY_GET_MOBILE_PLATFORM_APPLICATION,
        Capability.SHOPIFY_CREATE_MOBILE_PLATFORM_APPLICATION,
        Capability.SHOPIFY_UPDATE_MOBILE_PLATFORM_APPLICATION,
        Capability.SHOPIFY_DELETE_MOBILE_PLATFORM_APPLICATION,
    }
    # App-level mobile platform configuration — no extra scope.
    scope_independent = True

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_LIST_MOBILE_PLATFORM_APPLICATIONS:
            return self._list(params)
        if capability == \
                Capability.SHOPIFY_GET_MOBILE_PLATFORM_APPLICATION:
            return self._get(params)
        if capability == \
                Capability.SHOPIFY_CREATE_MOBILE_PLATFORM_APPLICATION:
            return self._create(params)
        if capability == \
                Capability.SHOPIFY_UPDATE_MOBILE_PLATFORM_APPLICATION:
            return self._update(params)
        if capability == \
                Capability.SHOPIFY_DELETE_MOBILE_PLATFORM_APPLICATION:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

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

        reverse = params.get("reverse")
        data = self._gql(_LIST_QUERY, {
            "first": limit,
            "after": cursor,
            "reverse": bool(reverse) if reverse is not None else None,
        })
        envelope = data.get("mobilePlatformApplications") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        apps = [
            self._normalise(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_MOBILE_PLATFORM_APPLICATIONS,
            data={
                "applications": apps,
                "count": len(apps),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        app_id = self._extract_id(params)
        data = self._gql(_GET_QUERY, {"id": app_id})
        node = data.get("mobilePlatformApplication") or {}
        return self._success(
            Capability.SHOPIFY_GET_MOBILE_PLATFORM_APPLICATION,
            data={
                "application": self._normalise(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        body = self._build_input(params, allow_create=True)
        data = self._gql(_CREATE_MUTATION, {"input": body})
        self._check_user_errors(
            data, "mobilePlatformApplicationCreate",
        )
        payload = data.get(
            "mobilePlatformApplicationCreate",
        ) or {}
        return self._success(
            Capability.SHOPIFY_CREATE_MOBILE_PLATFORM_APPLICATION,
            data={
                "application": self._normalise(
                    payload.get("mobilePlatformApplication") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        app_id = self._extract_id(params)
        body = self._build_input(params, allow_create=False)
        data = self._gql(_UPDATE_MUTATION, {
            "id": app_id, "input": body,
        })
        self._check_user_errors(
            data, "mobilePlatformApplicationUpdate",
        )
        payload = data.get(
            "mobilePlatformApplicationUpdate",
        ) or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_MOBILE_PLATFORM_APPLICATION,
            data={
                "application": self._normalise(
                    payload.get("mobilePlatformApplication") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        app_id = self._extract_id(params)
        data = self._gql(_DELETE_MUTATION, {"id": app_id})
        self._check_user_errors(
            data, "mobilePlatformApplicationDelete",
        )
        payload = data.get(
            "mobilePlatformApplicationDelete",
        ) or {}
        return self._success(
            Capability.SHOPIFY_DELETE_MOBILE_PLATFORM_APPLICATION,
            data={
                "deleted_id": (
                    payload.get(
                        "deletedMobilePlatformApplicationId", "",
                    ) or ""
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        app_id = (
            params.get("id")
            or params.get("application_id")
            or params.get("applicationId")
        )
        if not isinstance(app_id, str) or not app_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the mobile platform "
                "application) is required",
            )
        return app_id.strip()

    def _build_input(
        self, params: dict[str, Any], *, allow_create: bool,
    ) -> dict[str, Any]:
        platform = params.get("platform")
        if not isinstance(platform, str) or not platform.strip():
            raise AdapterValidationError(
                self.name,
                "'platform' is required (one of "
                f"{sorted(_VALID_PLATFORMS)})",
            )
        platform_norm = platform.strip().lower()
        if platform_norm not in _VALID_PLATFORMS:
            raise AdapterValidationError(
                self.name,
                f"'platform' must be one of "
                f"{sorted(_VALID_PLATFORMS)}",
            )

        if platform_norm == "android":
            sub = self._build_android(
                params, require_required=allow_create,
            )
            return {"android": sub}
        sub = self._build_apple(
            params, require_required=allow_create,
        )
        return {"apple": sub}

    def _build_android(
        self, params: dict[str, Any], *, require_required: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        app_id = (
            params.get("application_id")
            or params.get("applicationId")
        )
        if app_id is not None:
            if not isinstance(app_id, str) or not app_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'application_id' must be a non-empty string "
                    "(Android package name, e.g. com.example.app)",
                )
            out["applicationId"] = app_id.strip()
        elif require_required:
            raise AdapterValidationError(
                self.name,
                "'application_id' is required on create (Android "
                "package name)",
            )

        fps = (
            params.get("sha256_cert_fingerprints")
            or params.get("sha256CertFingerprints")
        )
        if fps is not None:
            if isinstance(fps, str):
                fps = [fps]
            if not isinstance(fps, list) or not all(
                isinstance(v, str) for v in fps
            ):
                raise AdapterValidationError(
                    self.name,
                    "'sha256_cert_fingerprints' must be a list of "
                    "fingerprint strings",
                )
            cleaned = [v.strip() for v in fps if v.strip()]
            if cleaned:
                out["sha256CertFingerprints"] = cleaned

        if "app_links_enabled" in params:
            if params["app_links_enabled"] is not None:
                out["appLinksEnabled"] = bool(
                    params["app_links_enabled"],
                )
        elif "appLinksEnabled" in params:
            if params["appLinksEnabled"] is not None:
                out["appLinksEnabled"] = bool(
                    params["appLinksEnabled"],
                )

        if not out and not require_required:
            raise AdapterValidationError(
                self.name,
                "supply at least one Android field on update "
                "(application_id / sha256_cert_fingerprints / "
                "app_links_enabled)",
            )
        return out

    def _build_apple(
        self, params: dict[str, Any], *, require_required: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        app_id = params.get("app_id") or params.get("appId")
        if app_id is not None:
            if not isinstance(app_id, str) or not app_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'app_id' must be a non-empty string "
                    "(Apple bundle id, e.g. TEAMID.com.example.app)",
                )
            out["appId"] = app_id.strip()
        elif require_required:
            raise AdapterValidationError(
                self.name,
                "'app_id' is required on create (Apple bundle id)",
            )

        for snake, camel in (
            ("universal_links_enabled", "universalLinksEnabled"),
            ("shared_web_credentials_enabled",
             "sharedWebCredentialsEnabled"),
            ("app_clips_enabled", "appClipsEnabled"),
        ):
            if snake in params and params[snake] is not None:
                out[camel] = bool(params[snake])
            elif camel in params and params[camel] is not None:
                out[camel] = bool(params[camel])

        clip = (
            params.get("app_clip_application_id")
            or params.get("appClipApplicationId")
        )
        if clip is not None:
            if not isinstance(clip, str) or not clip.strip():
                raise AdapterValidationError(
                    self.name,
                    "'app_clip_application_id' must be a non-empty "
                    "string",
                )
            out["appClipApplicationId"] = clip.strip()

        if not out and not require_required:
            raise AdapterValidationError(
                self.name,
                "supply at least one Apple field on update",
            )
        return out

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        kind = node.get("__typename", "") or ""
        out: dict[str, Any] = {
            "id": node.get("id", "") or "",
            "platform": (
                "android" if kind == "AndroidApplication"
                else "apple" if kind == "AppleApplication"
                else ""
            ),
            "kind": kind,
        }
        if kind == "AndroidApplication":
            out["application_id"] = (
                node.get("applicationId", "") or ""
            )
            fps = node.get("sha256CertFingerprints") or []
            out["sha256_cert_fingerprints"] = [
                f for f in fps if isinstance(f, str)
            ]
            out["app_links_enabled"] = bool(
                node.get("appLinksEnabled", False),
            )
        elif kind == "AppleApplication":
            out["app_id"] = node.get("appId", "") or ""
            out["universal_links_enabled"] = bool(
                node.get("universalLinksEnabled", False),
            )
            out["shared_web_credentials_enabled"] = bool(
                node.get("sharedWebCredentialsEnabled", False),
            )
            out["app_clips_enabled"] = bool(
                node.get("appClipsEnabled", False),
            )
            out["app_clip_application_id"] = (
                node.get("appClipApplicationId", "") or ""
            )
        return out
