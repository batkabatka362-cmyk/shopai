"""ShopifyCatalogWriteAdapter — B2B catalog CRUD + context binding.

Companion to ``catalogs.py`` (which is read-only — LIST + GET).
A B2B catalog binds a price list + a publication to a "context" —
specific company locations or markets — so different B2B tiers
see different prices and product availability. Without writes, an
operator can only DISCOVER catalogs the merchant set up by hand;
ShopAI's pricing + B2B engines need to MINT them programmatically.

Capabilities:

  * ``SHOPIFY_CREATE_CATALOG``         — catalogCreate. Pattern B
    (input wrapper): full CatalogCreateInput including the
    initial context bindings.
  * ``SHOPIFY_UPDATE_CATALOG``         — catalogUpdate. Pattern A:
    id at field level + CatalogUpdateInput. Title / status /
    price list / publication / context all settable.
  * ``SHOPIFY_DELETE_CATALOG``         — catalogDelete. Pattern A:
    id at field level + optional deleteDependentResources flag.
  * ``SHOPIFY_UPDATE_CATALOG_CONTEXT`` — catalogContextUpdate.
    Pattern A: catalogId at field level. Adds / removes specific
    market or company-location bindings without touching the
    rest of the catalog config.

Friendly create call shape::

    {"title":            "Wholesale tier — APAC",
     "status":           "active",       # or DRAFT / ARCHIVED
     "context": {
       "company_location_ids": ["gid://shopify/CompanyLocation/1"],
       # OR: "market_ids": ["gid://shopify/Market/2"]
     },
     "price_list_id":    "gid://shopify/PriceList/3",
     "publication_id":   "gid://shopify/Publication/4"}

CatalogContextInput accepts ``marketIds`` xor ``companyLocationIds``
— the catalog is one type or the other, not both. The adapter
validates this client-side.

Pattern F: ``CatalogUserError`` HAS the ``code`` field — keep it
in the selection.

Pattern E note: gated by ``write_publications`` + ``write_price_lists``
plus ``write_companies`` for company-location-bound catalogs.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CATALOG_FIELDS = """
__typename
id
title
status
priceList {
  id
  name
  currency
}
publication {
  id
  catalog { id }
}
""".strip()


_CREATE_MUTATION = f"""
mutation catalogCreate($input: CatalogCreateInput!) {{
  catalogCreate(input: $input) {{
    catalog {{
      {_CATALOG_FIELDS}
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
mutation catalogUpdate(
  $id: ID!,
  $input: CatalogUpdateInput!
) {{
  catalogUpdate(id: $id, input: $input) {{
    catalog {{
      {_CATALOG_FIELDS}
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
mutation catalogDelete(
  $id: ID!,
  $deleteDependentResources: Boolean
) {
  catalogDelete(
    id: $id,
    deleteDependentResources: $deleteDependentResources
  ) {
    deletedId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_CONTEXT_UPDATE_MUTATION = f"""
mutation catalogContextUpdate(
  $catalogId: ID!,
  $contextsToAdd: CatalogContextInput,
  $contextsToRemove: CatalogContextInput
) {{
  catalogContextUpdate(
    catalogId: $catalogId,
    contextsToAdd: $contextsToAdd,
    contextsToRemove: $contextsToRemove
  ) {{
    catalog {{
      {_CATALOG_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_VALID_STATUSES = {"ACTIVE", "ARCHIVED", "DRAFT"}


class ShopifyCatalogWriteAdapter(ShopifyBaseAdapter):
    name = "shopify_catalog_write"
    capabilities = {
        Capability.SHOPIFY_CREATE_CATALOG,
        Capability.SHOPIFY_UPDATE_CATALOG,
        Capability.SHOPIFY_DELETE_CATALOG,
        Capability.SHOPIFY_UPDATE_CATALOG_CONTEXT,
    }
    required_scopes = frozenset({"read_products", "write_products"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_CATALOG:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_CATALOG:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_CATALOG:
            return self._delete(params)
        if capability == Capability.SHOPIFY_UPDATE_CATALOG_CONTEXT:
            return self._context_update(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                self.name,
                "'title' is required (the operator-facing catalog name)",
            )
        status = self._normalise_status(params.get("status"), required=True)
        context = self._build_context(
            params.get("context"), required=True,
        )

        body: dict[str, Any] = {
            "title": title.strip(),
            "status": status,
            "context": context,
        }
        price_list_id = (
            params.get("price_list_id") or params.get("priceListId")
        )
        if isinstance(price_list_id, str) and price_list_id.strip():
            body["priceListId"] = price_list_id.strip()
        publication_id = (
            params.get("publication_id") or params.get("publicationId")
        )
        if isinstance(publication_id, str) and publication_id.strip():
            body["publicationId"] = publication_id.strip()

        data = self._gql(_CREATE_MUTATION, {"input": body})
        self._check_user_errors(data, "catalogCreate")
        payload = data.get("catalogCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_CATALOG,
            data={
                "catalog": self._normalise_catalog(
                    payload.get("catalog") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        catalog_id = self._extract_id(params, key_label="id")
        body: dict[str, Any] = {}
        title = params.get("title")
        if isinstance(title, str) and title.strip():
            body["title"] = title.strip()
        if "status" in params and params["status"] is not None:
            body["status"] = self._normalise_status(
                params["status"], required=True,
            )
        if "context" in params and params["context"] is not None:
            body["context"] = self._build_context(
                params["context"], required=True,
            )
        price_list_id = (
            params.get("price_list_id") or params.get("priceListId")
        )
        if isinstance(price_list_id, str) and price_list_id.strip():
            body["priceListId"] = price_list_id.strip()
        publication_id = (
            params.get("publication_id") or params.get("publicationId")
        )
        if isinstance(publication_id, str) and publication_id.strip():
            body["publicationId"] = publication_id.strip()

        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of: title, status, context, "
                "price_list_id, publication_id",
            )

        data = self._gql(_UPDATE_MUTATION, {
            "id": catalog_id, "input": body,
        })
        self._check_user_errors(data, "catalogUpdate")
        payload = data.get("catalogUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_CATALOG,
            data={
                "catalog": self._normalise_catalog(
                    payload.get("catalog") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        catalog_id = self._extract_id(params, key_label="id")
        delete_deps = (
            params.get("delete_dependent_resources")
            if "delete_dependent_resources" in params
            else params.get("deleteDependentResources")
        )
        variables: dict[str, Any] = {"id": catalog_id}
        if delete_deps is not None:
            variables["deleteDependentResources"] = bool(delete_deps)
        else:
            variables["deleteDependentResources"] = None

        data = self._gql(_DELETE_MUTATION, variables)
        self._check_user_errors(data, "catalogDelete")
        payload = data.get("catalogDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_CATALOG,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Context update ─────────────────────────────────────────────

    def _context_update(self, params: dict[str, Any]) -> Any:
        catalog_id = self._extract_id(
            params, key_label="catalog_id",
            extra_keys=("catalogId",),
        )
        contexts_to_add = (
            params.get("contexts_to_add")
            or params.get("contextsToAdd")
            or params.get("add")
        )
        contexts_to_remove = (
            params.get("contexts_to_remove")
            or params.get("contextsToRemove")
            or params.get("remove")
        )

        if not contexts_to_add and not contexts_to_remove:
            raise AdapterValidationError(
                self.name,
                "supply at least one of 'contexts_to_add' / "
                "'contexts_to_remove'",
            )

        add_input = (
            self._build_context(contexts_to_add, required=False)
            if contexts_to_add else None
        )
        remove_input = (
            self._build_context(contexts_to_remove, required=False)
            if contexts_to_remove else None
        )

        data = self._gql(_CONTEXT_UPDATE_MUTATION, {
            "catalogId": catalog_id,
            "contextsToAdd": add_input,
            "contextsToRemove": remove_input,
        })
        self._check_user_errors(data, "catalogContextUpdate")
        payload = data.get("catalogContextUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_CATALOG_CONTEXT,
            data={
                "catalog": self._normalise_catalog(
                    payload.get("catalog") or {},
                ),
                "added": (
                    self._summarise_context(add_input) if add_input
                    else {}
                ),
                "removed": (
                    self._summarise_context(remove_input)
                    if remove_input else {}
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(
        self,
        params: dict[str, Any],
        *,
        key_label: str,
        extra_keys: tuple[str, ...] = (),
    ) -> str:
        candidates = (key_label,) + extra_keys + ("id",)
        for k in candidates:
            v = params.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        raise AdapterValidationError(
            self.name,
            f"'{key_label}' (Shopify GID for the catalog) is required",
        )

    def _normalise_status(self, raw: Any, *, required: bool) -> str:
        if raw is None:
            if required:
                raise AdapterValidationError(
                    self.name,
                    "'status' is required (active / archived / draft)",
                )
            return ""
        if not isinstance(raw, str):
            raise AdapterValidationError(
                self.name, "'status' must be a string",
            )
        up = raw.strip().upper()
        if up not in _VALID_STATUSES:
            raise AdapterValidationError(
                self.name,
                f"'status' must be one of {sorted(_VALID_STATUSES)}",
            )
        return up

    def _build_context(
        self, raw: Any, *, required: bool,
    ) -> dict[str, Any]:
        if raw is None:
            if required:
                raise AdapterValidationError(
                    self.name,
                    "'context' is required — supply 'market_ids' or "
                    "'company_location_ids'",
                )
            return {}
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'context' must be a dict {market_ids?, "
                "company_location_ids?}",
            )

        market_ids = raw.get("market_ids") or raw.get("marketIds")
        company_location_ids = (
            raw.get("company_location_ids")
            or raw.get("companyLocationIds")
        )
        if market_ids and company_location_ids:
            raise AdapterValidationError(
                self.name,
                "'context' may set 'market_ids' OR "
                "'company_location_ids' — not both (a catalog is "
                "either market-scoped or company-location-scoped)",
            )
        if not market_ids and not company_location_ids:
            raise AdapterValidationError(
                self.name,
                "'context' must include 'market_ids' or "
                "'company_location_ids' (non-empty list of GIDs)",
            )

        if market_ids:
            cleaned = self._clean_id_list(
                market_ids, "context.market_ids",
            )
            return {"marketIds": cleaned}
        cleaned = self._clean_id_list(
            company_location_ids, "context.company_location_ids",
        )
        return {"companyLocationIds": cleaned}

    def _clean_id_list(self, raw: Any, label: str) -> list[str]:
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                f"'{label}' must be a non-empty list of GID strings",
            )
        cleaned = []
        for i, v in enumerate(raw):
            if not isinstance(v, str) or not v.strip():
                raise AdapterValidationError(
                    self.name, f"'{label}[{i}]' must be a GID string",
                )
            cleaned.append(v.strip())
        return cleaned

    @staticmethod
    def _summarise_context(ctx: dict[str, Any]) -> dict[str, Any]:
        if "marketIds" in ctx:
            return {
                "kind": "market", "count": len(ctx["marketIds"]),
            }
        if "companyLocationIds" in ctx:
            return {
                "kind": "company_location",
                "count": len(ctx["companyLocationIds"]),
            }
        return {}

    @staticmethod
    def _normalise_catalog(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        price_list = node.get("priceList") or {}
        publication = node.get("publication") or {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "status": node.get("status", "") or "",
            "type": node.get("__typename", "") or "",
            "price_list_id": (
                price_list.get("id", "")
                if isinstance(price_list, dict) else ""
            ) or "",
            "price_list_name": (
                price_list.get("name", "")
                if isinstance(price_list, dict) else ""
            ) or "",
            "price_list_currency": (
                price_list.get("currency", "")
                if isinstance(price_list, dict) else ""
            ) or "",
            "publication_id": (
                publication.get("id", "")
                if isinstance(publication, dict) else ""
            ) or "",
        }
