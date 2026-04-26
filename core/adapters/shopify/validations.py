"""ShopifyValidationsAdapter — Function-based checkout validations.

Validations are Shopify Function-backed extensions that fire at
checkout and let the Function block proceeding if cart contents
violate a custom rule. Use cases ShopAI engines need:

  * **Inventory engine — soft-block on out-of-stock fallback.** When
    the inventory engine has flagged an SKU but theme caching means
    the customer still added it, the validation Function can refuse
    checkout with a friendly message rather than letting the order
    place against zero stock.
  * **B2B / wholesale engine.** Block carts that don't meet minimum
    order quantity / minimum order value rules per company tier.
  * **Compliance engine.** Refuse checkouts shipping to restricted
    addresses (sanctioned regions, age-restricted SKUs in non-21+
    states, etc.).

Same Function-deploys-the-logic pattern as cart transforms and the
payment / delivery customisations: Function code lives in the app's
shopify-cli release; this adapter just attaches the Function to the
checkout pipeline so it runs.

Capabilities (CRUD on the registration record itself, no update —
canonical edit path is delete + recreate):

  * ``SHOPIFY_CREATE_VALIDATION`` — register a validation.
  * ``SHOPIFY_LIST_VALIDATIONS``  — list registered validations.
  * ``SHOPIFY_DELETE_VALIDATION`` — unregister.

Live-verified 2026-04-25 against ``ts0efe-ih.myshopify.com``: query
shape is correct (Shopify recognised the field and returned a precise
``ACCESS_DENIED`` error). Listing requires the ``read_validations``
scope; create/delete require ``write_validations``. Same Pattern E
(scope-gated) outcome as cart transforms — adapter is functionally
complete; merchants without the scope get a clean error rather than a
silent failure. The smart router will skip until the scope is granted.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_VALIDATION_FIELDS = """
id
title
enabled
blockOnFailure
shopifyFunction {
  id
  title
  apiType
}
""".strip()


_CREATE_VALIDATION_MUTATION = f"""
mutation validationCreate($validation: ValidationCreateInput!) {{
  validationCreate(validation: $validation) {{
    validation {{
      {_VALIDATION_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_LIST_VALIDATIONS_QUERY = f"""
query validations($first: Int!, $after: String) {{
  validations(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_VALIDATION_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_DELETE_VALIDATION_MUTATION = """
mutation validationDelete($id: ID!) {
  validationDelete(id: $id) {
    deletedId
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


class ShopifyValidationsAdapter(ShopifyBaseAdapter):
    name = "shopify_validations"
    capabilities = {
        Capability.SHOPIFY_CREATE_VALIDATION,
        Capability.SHOPIFY_LIST_VALIDATIONS,
        Capability.SHOPIFY_DELETE_VALIDATION,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_VALIDATION:
            return self._create(params)
        if capability == Capability.SHOPIFY_LIST_VALIDATIONS:
            return self._list(params)
        if capability == Capability.SHOPIFY_DELETE_VALIDATION:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        validation_input = self._build_create_input(params)
        # Variable name follows Shopify's "input named after the type"
        # convention (Pattern A in CLAUDE.md, same as
        # paymentCustomization / marketingEngagement).
        data = self._gql(
            _CREATE_VALIDATION_MUTATION,
            {"validation": validation_input},
        )
        self._check_user_errors(data, "validationCreate")
        payload = data.get("validationCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_VALIDATION,
            data={
                "validation": self._normalise_validation(
                    payload.get("validation") or {}
                ),
            },
        )

    @staticmethod
    def _build_create_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly call shape into ``ValidationCreateInput``.

        Friendly form::

            {
              "function_id":      "fn-min-order",
              "title":            "Block sub-$25 orders",
              "enabled":          True,
              "block_on_failure": True,
              "metafields": [
                  {"namespace": "$app:cfg", "key": "min_total",
                   "type": "number_decimal", "value": "25.00"},
              ],
            }
        """
        function_id = params.get("function_id") or params.get("functionId")
        if not isinstance(function_id, str) or not function_id.strip():
            raise AdapterValidationError(
                "shopify_validations",
                "'function_id' is required — validations are Shopify-"
                "Function-backed; the merchant's app must have a "
                "registered Function",
            )
        out: dict[str, Any] = {
            "functionId": function_id.strip(),
            "enable": bool(params.get("enabled", params.get("enable", True))),
            "blockOnFailure": bool(params.get("block_on_failure", False)),
        }
        title = params.get("title")
        if title is not None:
            if not isinstance(title, str):
                raise AdapterValidationError(
                    "shopify_validations", "'title' must be a string",
                )
            if title.strip():
                out["title"] = title.strip()
        metafields = _build_metafields(params.get("metafields"))
        if metafields:
            out["metafields"] = metafields
        return out

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
                "shopify_validations",
                "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_VALIDATIONS_QUERY, {
            "first": limit, "after": cursor,
        })
        envelope = data.get("validations") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        validations = [
            self._normalise_validation(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_VALIDATIONS,
            data={
                "validations": validations,
                "count": len(validations),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        validation_id = params.get("id") or params.get("validation_id")
        if not isinstance(validation_id, str) or not validation_id.strip():
            raise AdapterValidationError(
                "shopify_validations",
                "'id' (Shopify GID for the validation) is required",
            )
        data = self._gql(_DELETE_VALIDATION_MUTATION, {
            "id": validation_id.strip(),
        })
        self._check_user_errors(data, "validationDelete")
        payload = data.get("validationDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_VALIDATION,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_validation(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        function = node.get("shopifyFunction") or {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "enabled": bool(node.get("enabled", False)),
            "block_on_failure": bool(node.get("blockOnFailure", False)),
            "function_id": (
                function.get("id", "") if isinstance(function, dict) else ""
            ) or "",
            "function_title": (
                function.get("title", "")
                if isinstance(function, dict) else ""
            ) or "",
            "function_api_type": (
                function.get("apiType", "")
                if isinstance(function, dict) else ""
            ) or "",
        }


def _build_metafields(raw: Any) -> list[dict[str, Any]]:
    """Convert a ShopAI-friendly metafields list into MetafieldInput
    shape. Same coercion rules as cart_transforms — numeric values
    serialised to strings, complex values JSON-coerced. Inlined
    rather than imported from cart_transforms to keep error messages
    referencing the adapter at the call site (per CLAUDE.md
    Pattern G — "money input shape coercion is per-adapter")."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AdapterValidationError(
            "shopify_validations",
            "'metafields' must be a list of "
            "{namespace, key, type, value} dicts",
        )
    out: list[dict[str, Any]] = []
    for i, mf in enumerate(raw):
        if not isinstance(mf, dict):
            raise AdapterValidationError(
                "shopify_validations",
                f"metafields[{i}] must be a dict",
            )
        ns = mf.get("namespace") or "shopai"
        key = mf.get("key")
        mf_type = mf.get("type") or "single_line_text_field"
        value = mf.get("value")
        if not isinstance(key, str) or not key.strip():
            raise AdapterValidationError(
                "shopify_validations",
                f"metafields[{i}] missing 'key'",
            )
        if value is None:
            raise AdapterValidationError(
                "shopify_validations",
                f"metafields[{i}] missing 'value'",
            )
        if isinstance(value, str):
            value_str = value
        elif isinstance(value, bool):
            value_str = "true" if value else "false"
        elif isinstance(value, (int, float)):
            value_str = str(value)
        else:
            import json as _json
            try:
                value_str = _json.dumps(value)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_validations",
                    f"metafields[{i}] value not JSON-serialisable",
                ) from exc
        out.append({
            "namespace": ns,
            "key": key,
            "type": mf_type,
            "value": value_str,
        })
    return out
