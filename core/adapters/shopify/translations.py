"""ShopifyTranslationsAdapter — push localised content to Shopify.

ShopAI's content engines emit AI-translated product titles, descriptions,
metafield values, and theme copy in N locales. Shopify exposes a per-
resource translation surface where each translatable field on a
product/collection/page/article/etc. can carry one translation per
locale. Without this adapter the AI translation pipeline can produce
content but not put it on the storefront for non-English shoppers.

Three flows ShopAI engines need:

  * **Read translatable structure.** Before translating a product the
    engine needs to know which fields are translatable (title vs
    body_html vs handle vs SEO meta) and what the source content
    digest is — a translation registered against a stale digest is
    silently invalidated when the source changes.
  * **Push translations.** ``translationsRegister`` writes 1..N
    translations against a resource for a given locale.
  * **Remove stale translations.** When a product is delisted or the
    source field changes intent (e.g. brand rename) the engine pulls
    the old translation rather than serving misleading content.

Capabilities:

  * ``SHOPIFY_GET_TRANSLATABLE_RESOURCE`` — read translatable content
    and existing translations for one resource.
  * ``SHOPIFY_REGISTER_TRANSLATIONS`` — push N translations against
    one resource. Capped at 100 per call (Shopify's limit).
  * ``SHOPIFY_REMOVE_TRANSLATIONS`` — bulk-remove by (resource,
    keys, locales).

Translation digest gotcha: a TranslationInput requires the
``translatableContentDigest`` of the source content. The adapter
asks the caller for it (engines that translate read the digest in
the same call). Submitting a stale digest does not error — Shopify
silently marks the translation outdated, which is more dangerous
than failing loudly. The adapter validates the digest is non-empty
to at least catch the "engine forgot to read the digest" case.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Note: ``TranslatableResource.translations`` requires a ``locale``
# argument in the current schema (caught live as "Field 'translations'
# is missing required arguments: locale"). The query asks for a single
# locale's translations at a time; engines fetching multiple locales
# make multiple calls. The translatable content (source language) is
# locale-independent and surfaces alongside.
_GET_TRANSLATABLE_RESOURCE_QUERY = """
query translatableResource($resourceId: ID!, $locale: String!) {
  translatableResource(resourceId: $resourceId) {
    resourceId
    translatableContent {
      key
      value
      digest
      locale
    }
    translations(locale: $locale) {
      key
      value
      locale
      outdated
      market {
        id
        name
      }
    }
  }
}
""".strip()


_REGISTER_TRANSLATIONS_MUTATION = """
mutation translationsRegister(
  $resourceId: ID!, $translations: [TranslationInput!]!
) {
  translationsRegister(
    resourceId: $resourceId, translations: $translations
  ) {
    translations {
      key
      value
      locale
      outdated
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_REMOVE_TRANSLATIONS_MUTATION = """
mutation translationsRemove(
  $resourceId: ID!,
  $translationKeys: [String!]!,
  $locales: [String!]!
) {
  translationsRemove(
    resourceId: $resourceId,
    translationKeys: $translationKeys,
    locales: $locales
  ) {
    translations {
      key
      locale
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_MAX_TRANSLATIONS_PER_CALL = 100


class ShopifyTranslationsAdapter(ShopifyBaseAdapter):
    name = "shopify_translations"
    capabilities = {
        Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE,
        Capability.SHOPIFY_REGISTER_TRANSLATIONS,
        Capability.SHOPIFY_REMOVE_TRANSLATIONS,
    }
    required_scopes = frozenset({"read_translations", "write_translations"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE:
            return self._get_translatable_resource(params)
        if capability == Capability.SHOPIFY_REGISTER_TRANSLATIONS:
            return self._register_translations(params)
        if capability == Capability.SHOPIFY_REMOVE_TRANSLATIONS:
            return self._remove_translations(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Get translatable resource ─────────────────────────────────

    def _get_translatable_resource(self, params: dict[str, Any]) -> Any:
        resource_id = params.get("resource_id") or params.get("resourceId")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise AdapterValidationError(
                "shopify_translations",
                "'resource_id' (Shopify GID for the translatable "
                "resource) is required",
            )
        # locale is REQUIRED on TranslatableResource.translations in
        # the current schema (caught live). Engines fetching multiple
        # locales make multiple calls.
        locale = params.get("locale")
        if not isinstance(locale, str) or not locale.strip():
            raise AdapterValidationError(
                "shopify_translations",
                "'locale' is required (Shopify's TranslatableResource."
                "translations field requires a locale argument)",
            )

        data = self._gql(
            _GET_TRANSLATABLE_RESOURCE_QUERY,
            {"resourceId": resource_id.strip(), "locale": locale.strip()},
        )
        node = data.get("translatableResource")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE,
                data={"found": False, "resource": None},
            )

        translatable_content = self._normalise_content(
            node.get("translatableContent")
        )
        translations = self._normalise_translations(
            node.get("translations"), None,
        )
        return self._success(
            Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE,
            data={
                "found": True,
                "resource_id": node.get("resourceId", "") or resource_id.strip(),
                "locale": locale.strip(),
                "translatable_content": translatable_content,
                "translations": translations,
            },
        )

    # ── Register translations ─────────────────────────────────────

    def _register_translations(self, params: dict[str, Any]) -> Any:
        resource_id = params.get("resource_id") or params.get("resourceId")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise AdapterValidationError(
                "shopify_translations",
                "'resource_id' (Shopify GID) is required",
            )

        translations_input = self._build_translations_input(params)
        data = self._gql(
            _REGISTER_TRANSLATIONS_MUTATION,
            {
                "resourceId": resource_id.strip(),
                "translations": translations_input,
            },
        )
        self._check_user_errors(data, "translationsRegister")
        payload = data.get("translationsRegister") or {}
        registered = payload.get("translations") or []
        return self._success(
            Capability.SHOPIFY_REGISTER_TRANSLATIONS,
            data={
                "resource_id": resource_id.strip(),
                "registered_count": len(registered),
                "translations": [
                    self._normalise_translation_item(t)
                    for t in registered if isinstance(t, dict)
                ],
            },
        )

    @staticmethod
    def _build_translations_input(params: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert ShopAI's friendly call shape into ``[TranslationInput]``.

        Friendly form — single locale::

            {
              "resource_id": "gid://shopify/Product/X",
              "locale":      "fr",
              "translations": {
                  "title": {"value": "Lampe Lune 3D", "digest": "abc..."},
                  "body_html": {"value": "<p>...</p>", "digest": "def..."},
              },
            }

        Or multi-locale / explicit form::

            {
              "resource_id": "...",
              "translations": [
                  {"key": "title", "value": "...", "locale": "fr",
                   "translatableContentDigest": "abc..."},
                  ...
              ],
            }
        """
        # Branch 1: friendly per-locale dict shape.
        translations_raw = params.get("translations")
        locale = params.get("locale")
        market_id = params.get("market_id") or params.get("marketId")

        if isinstance(translations_raw, dict):
            if not locale or not isinstance(locale, str):
                raise AdapterValidationError(
                    "shopify_translations",
                    "dict-form 'translations' needs 'locale' "
                    "(e.g. 'fr', 'es-ES')",
                )
            out: list[dict[str, Any]] = []
            for key, entry in translations_raw.items():
                if not isinstance(key, str) or not key.strip():
                    raise AdapterValidationError(
                        "shopify_translations",
                        f"translation key must be a non-empty string, "
                        f"got {key!r}",
                    )
                value, digest = _coerce_translation_entry(entry, key)
                trans: dict[str, Any] = {
                    "key": key,
                    "value": value,
                    "locale": locale,
                    "translatableContentDigest": digest,
                }
                if market_id:
                    trans["marketId"] = market_id
                out.append(trans)
            if not out:
                raise AdapterValidationError(
                    "shopify_translations",
                    "'translations' dict must be non-empty",
                )
            if len(out) > _MAX_TRANSLATIONS_PER_CALL:
                raise AdapterValidationError(
                    "shopify_translations",
                    f"max {_MAX_TRANSLATIONS_PER_CALL} translations per "
                    f"call, got {len(out)}",
                )
            return out

        # Branch 2: explicit list-of-dicts shape.
        if isinstance(translations_raw, list):
            if not translations_raw:
                raise AdapterValidationError(
                    "shopify_translations",
                    "'translations' list must be non-empty",
                )
            if len(translations_raw) > _MAX_TRANSLATIONS_PER_CALL:
                raise AdapterValidationError(
                    "shopify_translations",
                    f"max {_MAX_TRANSLATIONS_PER_CALL} translations per "
                    f"call, got {len(translations_raw)}",
                )
            out2: list[dict[str, Any]] = []
            for i, entry in enumerate(translations_raw):
                if not isinstance(entry, dict):
                    raise AdapterValidationError(
                        "shopify_translations",
                        f"translations[{i}] must be a dict",
                    )
                key = entry.get("key")
                if not isinstance(key, str) or not key.strip():
                    raise AdapterValidationError(
                        "shopify_translations",
                        f"translations[{i}] missing 'key'",
                    )
                value = entry.get("value")
                if not isinstance(value, str):
                    raise AdapterValidationError(
                        "shopify_translations",
                        f"translations[{i}] 'value' must be a string",
                    )
                entry_locale = entry.get("locale") or locale
                if not isinstance(entry_locale, str) or not entry_locale.strip():
                    raise AdapterValidationError(
                        "shopify_translations",
                        f"translations[{i}] missing 'locale'",
                    )
                digest = (
                    entry.get("translatableContentDigest")
                    or entry.get("digest")
                )
                if not isinstance(digest, str) or not digest.strip():
                    raise AdapterValidationError(
                        "shopify_translations",
                        f"translations[{i}] missing 'digest' (the "
                        f"translatableContentDigest from a prior "
                        f"get_translatable_resource call)",
                    )
                trans2: dict[str, Any] = {
                    "key": key,
                    "value": value,
                    "locale": entry_locale,
                    "translatableContentDigest": digest,
                }
                entry_market = entry.get("market_id") or entry.get("marketId") or market_id
                if entry_market:
                    trans2["marketId"] = entry_market
                out2.append(trans2)
            return out2

        raise AdapterValidationError(
            "shopify_translations",
            "'translations' must be a dict (per-locale form) or a "
            "list (explicit form)",
        )

    # ── Remove translations ───────────────────────────────────────

    def _remove_translations(self, params: dict[str, Any]) -> Any:
        resource_id = params.get("resource_id") or params.get("resourceId")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise AdapterValidationError(
                "shopify_translations",
                "'resource_id' (Shopify GID) is required",
            )
        keys = params.get("keys") or params.get("translation_keys")
        if isinstance(keys, str):
            keys = [keys]
        if not isinstance(keys, list) or not keys:
            raise AdapterValidationError(
                "shopify_translations",
                "'keys' must be a non-empty list of translation keys",
            )
        for i, k in enumerate(keys):
            if not isinstance(k, str) or not k.strip():
                raise AdapterValidationError(
                    "shopify_translations",
                    f"keys[{i}] must be a non-empty string",
                )
        locales = params.get("locales") or params.get("locale")
        if isinstance(locales, str):
            locales = [locales]
        if not isinstance(locales, list) or not locales:
            raise AdapterValidationError(
                "shopify_translations",
                "'locales' must be a non-empty list of locale codes",
            )
        for i, loc in enumerate(locales):
            if not isinstance(loc, str) or not loc.strip():
                raise AdapterValidationError(
                    "shopify_translations",
                    f"locales[{i}] must be a non-empty string",
                )

        data = self._gql(_REMOVE_TRANSLATIONS_MUTATION, {
            "resourceId": resource_id.strip(),
            "translationKeys": [k.strip() for k in keys],
            "locales": [l.strip() for l in locales],
        })
        self._check_user_errors(data, "translationsRemove")
        payload = data.get("translationsRemove") or {}
        removed = payload.get("translations") or []
        return self._success(
            Capability.SHOPIFY_REMOVE_TRANSLATIONS,
            data={
                "resource_id": resource_id.strip(),
                "removed_count": len(removed),
                "removed": [
                    {"key": t.get("key", ""), "locale": t.get("locale", "")}
                    for t in removed if isinstance(t, dict)
                ],
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_content(raw: Any) -> list[dict[str, str]]:
        """Lift the GraphQL TranslatableContent array — engines need
        ``digest`` to register a translation against this content
        without the result being silently flagged outdated."""
        if not isinstance(raw, list):
            return []
        out: list[dict[str, str]] = []
        for c in raw:
            if not isinstance(c, dict):
                continue
            out.append({
                "key": c.get("key", "") or "",
                "value": c.get("value", "") or "",
                "digest": c.get("digest", "") or "",
                "source_locale": c.get("locale", "") or "",
            })
        return out

    @staticmethod
    def _normalise_translations(
        raw: Any, locale_filter: list[str] | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        for t in raw:
            if not isinstance(t, dict):
                continue
            locale = t.get("locale", "") or ""
            if locale_filter and locale not in locale_filter:
                continue
            market = t.get("market") or {}
            out.append({
                "key": t.get("key", "") or "",
                "value": t.get("value", "") or "",
                "locale": locale,
                "outdated": bool(t.get("outdated", False)),
                "market_id": (
                    market.get("id", "") if isinstance(market, dict) else ""
                ) or "",
                "market_name": (
                    market.get("name", "") if isinstance(market, dict) else ""
                ) or "",
            })
        return out

    @staticmethod
    def _normalise_translation_item(t: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": t.get("key", "") or "",
            "value": t.get("value", "") or "",
            "locale": t.get("locale", "") or "",
            "outdated": bool(t.get("outdated", False)),
        }


def _coerce_translation_entry(
    entry: Any, key: str,
) -> tuple[str, str]:
    """Pull (value, digest) out of a friendly per-key entry.

    Accepts either a {"value", "digest"} dict (preferred) or a bare
    string when the caller has already paired the digest at a higher
    level (rare). Validates both so misuse fails fast.
    """
    if isinstance(entry, dict):
        value = entry.get("value")
        digest = (
            entry.get("digest")
            or entry.get("translatableContentDigest")
        )
        if not isinstance(value, str):
            raise AdapterValidationError(
                "shopify_translations",
                f"translation '{key}' 'value' must be a string",
            )
        if not isinstance(digest, str) or not digest.strip():
            raise AdapterValidationError(
                "shopify_translations",
                f"translation '{key}' missing 'digest' "
                f"(read it from translatableContent[].digest)",
            )
        return value, digest
    raise AdapterValidationError(
        "shopify_translations",
        f"translation '{key}' must be a dict {{value, digest}}, "
        f"got {type(entry).__name__}",
    )
