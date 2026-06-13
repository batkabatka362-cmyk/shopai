"""ShopifyProductsAdapter — core product CRUD + variant pricing.

Products are the central commerce object. ShopAI's pricing,
creative, catalog, and merchandising engines all touch this
surface. The legacy ``utils/shopify_client`` exposes a thin
read-only product fetch; this adapter is the engine-grade
read/write surface.

Capabilities:

  * ``SHOPIFY_LIST_PRODUCTS``    — paginated list with filter/sort.
  * ``SHOPIFY_GET_PRODUCT``      — single product with variants/images.
  * ``SHOPIFY_CREATE_PRODUCT``   — create product (variants are added
    separately via the variants bulk path; productCreate's variant
    field is deprecated in 2024-04+).
  * ``SHOPIFY_UPDATE_PRODUCT``   — update title/description/status/
    vendor/product_type/tags.
  * ``SHOPIFY_DELETE_PRODUCT``   — delete product.
  * ``SHOPIFY_UPDATE_VARIANTS``  — bulk update variant price /
    compareAtPrice / sku via ``productVariantsBulkUpdate``. This is
    the primary surface the pricing engine drives.
  * ``SHOPIFY_TAG_PRODUCT``      — additive tag write via ``tagsAdd``.
    Unlike SHOPIFY_UPDATE_PRODUCT which REPLACES the tag list, this
    APPENDS tags non-destructively (Shopify's tagsAdd mutation is a
    merge). Used by catalog_quality_autonomy + future tag-class
    appliers that just want to attach a flag without re-reading the
    full tag list to avoid wiping.
  * ``SHOPIFY_UNTAG_PRODUCT``    — symmetric removal via ``tagsRemove``.

Friendly call shapes:

    create::

        {
          "title":        "Camping Lantern",
          "description":  "<p>Bright LED.</p>",   # HTML body
          "status":       "ACTIVE",               # or DRAFT/ARCHIVED
          "vendor":       "ShopAI Outdoors",
          "product_type": "Lighting",
          "tags":         ["camping", "outdoor"],
        }

    update::

        {"id": "gid://shopify/Product/123", "title": "...", ...}

    bulk variant update::

        {
          "product_id": "gid://shopify/Product/123",
          "variants": [
            {"id":  "gid://shopify/ProductVariant/1",
             "price": "19.99",
             "compare_at_price": "29.99",
             "sku": "LANT-RED"},
            ...
          ]
        }
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# W963-160: split into _BASE (no images) + _PRODUCT_FIELDS
# (= _BASE + images(first:1) for LIST path image-count).
# _WITH_VARIANTS uses _BASE + variants + images(first:20)
# so the GraphQL fragment-merge doesn't see two images
# selections with conflicting args.
_PRODUCT_FIELDS_BASE = """
id
title
handle
status
vendor
productType
tags
createdAt
updatedAt
description
descriptionHtml
totalInventory
priceRangeV2 {
  minVariantPrice { amount currencyCode }
  maxVariantPrice { amount currencyCode }
}
seo { title description }
variantsCount { count }
""".strip()


_PRODUCT_FIELDS = f"""
{_PRODUCT_FIELDS_BASE}
images(first: 1) {{ edges {{ node {{ id }} }} }}
""".strip()


_PRODUCT_FIELDS_WITH_VARIANTS = f"""
{_PRODUCT_FIELDS_BASE}
variants(first: 100) {{
  edges {{
    node {{
      id
      title
      sku
      price
      compareAtPrice
      inventoryQuantity
      inventoryPolicy
      barcode
      position
    }}
  }}
}}
images(first: 20) {{
  edges {{
    node {{
      id
      url
      altText
    }}
  }}
}}
""".strip()


_LIST_PRODUCTS_QUERY = f"""
query products(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: ProductSortKeys,
  $reverse: Boolean
) {{
  products(
    first: $first,
    after: $after,
    query: $query,
    sortKey: $sortKey,
    reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_PRODUCT_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_PRODUCT_QUERY = f"""
query product($id: ID!) {{
  product(id: $id) {{
    {_PRODUCT_FIELDS_WITH_VARIANTS}
  }}
}}
""".strip()


# W963-164: include variants(first: 1) so the create response
# carries the default variant id. Downstream price-set follow-up
# (dispatchers.py _create_draft_product_dispatch) needs it to
# call productVariantsBulkUpdate without an extra GET round-trip.
# This is the only place the LIST-path fragment conflicts -- the
# selection is INLINE here, not in _PRODUCT_FIELDS.
_CREATE_PRODUCT_MUTATION = f"""
mutation productCreate($input: ProductInput!) {{
  productCreate(input: $input) {{
    product {{
      {_PRODUCT_FIELDS_BASE}
      images(first: 1) {{ edges {{ node {{ id }} }} }}
      variants(first: 1) {{
        edges {{
          node {{
            id
            price
            sku
          }}
        }}
      }}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()
# Pattern F (CLAUDE.md): productCreate.userErrors is ALSO the
# typed `UserError` (no code field) as of 2026-05-15 live
# verification against ts0efe-ih. My PR #93 commit message
# claimed productCreate "still uses UserErrors with code" —
# that was wrong; live verification proved both productCreate
# AND productUpdate moved to typed UserError. The Shopify
# Mutation Catalog drift on the Product family is now full.


_UPDATE_PRODUCT_MUTATION = f"""
mutation productUpdate($input: ProductInput!) {{
  productUpdate(input: $input) {{
    product {{
      {_PRODUCT_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()
# Pattern F (CLAUDE.md): productUpdate.userErrors is the typed
# `UserError` (no code field), not the broader `UserErrors`.
# Confirmed live 2026-05-15 against ts0efe-ih dev store: a
# `code` selection here returns "Field 'code' doesn't exist on
# type 'UserError'" and rolls back the mutation. productCreate
# still uses `UserErrors` with code — per-mutation, not per-resource.


_DELETE_PRODUCT_MUTATION = """
mutation productDelete($input: ProductDeleteInput!) {
  productDelete(input: $input) {
    deletedProductId
    userErrors {
      field
      message
    }
  }
}
""".strip()


_VARIANTS_BULK_UPDATE_MUTATION = """
mutation productVariantsBulkUpdate(
  $productId: ID!,
  $variants: [ProductVariantsBulkInput!]!
) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants {
      id
      title
      sku
      price
      compareAtPrice
      inventoryQuantity
    }
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

_VALID_STATUSES = {"ACTIVE", "DRAFT", "ARCHIVED"}
_VALID_SORT_KEYS = {
    "TITLE", "PRODUCT_TYPE", "VENDOR", "INVENTORY_TOTAL",
    "UPDATED_AT", "CREATED_AT", "PUBLISHED_AT", "ID", "RELEVANCE",
}


class ShopifyProductsAdapter(ShopifyBaseAdapter):
    name = "shopify_products"
    capabilities = {
        Capability.SHOPIFY_LIST_PRODUCTS,
        Capability.SHOPIFY_GET_PRODUCT,
        Capability.SHOPIFY_CREATE_PRODUCT,
        Capability.SHOPIFY_UPDATE_PRODUCT,
        Capability.SHOPIFY_DELETE_PRODUCT,
        Capability.SHOPIFY_UPDATE_VARIANTS,
        Capability.SHOPIFY_TAG_PRODUCT,
        Capability.SHOPIFY_UNTAG_PRODUCT,
    }
    # read_products covers list/get; write_products covers
    # create/update/delete and the variant mutation surface.
    required_scopes = frozenset({"read_products", "write_products"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_PRODUCTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_PRODUCT:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_PRODUCT:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_PRODUCT:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_PRODUCT:
            return self._delete(params)
        if capability == Capability.SHOPIFY_UPDATE_VARIANTS:
            return self._update_variants(params)
        if capability == Capability.SHOPIFY_TAG_PRODUCT:
            return self._tag(params, add=True)
        if capability == Capability.SHOPIFY_UNTAG_PRODUCT:
            return self._tag(params, add=False)
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

        variables: dict[str, Any] = {"first": limit, "after": cursor}

        query_filter = params.get("query")
        if query_filter is not None:
            if not isinstance(query_filter, str):
                raise AdapterValidationError(
                    self.name, "'query' must be a string",
                )
            variables["query"] = query_filter

        sort_key = params.get("sort_key")
        if sort_key is not None:
            if not isinstance(sort_key, str) or sort_key not in _VALID_SORT_KEYS:
                raise AdapterValidationError(
                    self.name,
                    f"'sort_key' must be one of: {sorted(_VALID_SORT_KEYS)}",
                )
            variables["sortKey"] = sort_key

        reverse = params.get("reverse")
        if reverse is not None:
            variables["reverse"] = bool(reverse)

        data = self._gql(_LIST_PRODUCTS_QUERY, variables)
        envelope = data.get("products") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        products = [
            self._normalise_product(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_PRODUCTS,
            data={
                "products": products,
                "count": len(products),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        product_id = params.get("id") or params.get("product_id")
        if not isinstance(product_id, str) or not product_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the product) is required",
            )
        data = self._gql(_GET_PRODUCT_QUERY, {"id": product_id.strip()})
        node = data.get("product") or {}
        return self._success(
            Capability.SHOPIFY_GET_PRODUCT,
            data={
                "product": self._normalise_product_with_variants(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        product_input = self._build_product_input(params, for_update=False)
        data = self._gql(
            _CREATE_PRODUCT_MUTATION, {"input": product_input},
        )
        self._check_user_errors(data, "productCreate")
        payload = data.get("productCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_PRODUCT,
            data={
                "product": self._normalise_product(
                    payload.get("product") or {}
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        product_input = self._build_product_input(params, for_update=True)
        data = self._gql(
            _UPDATE_PRODUCT_MUTATION, {"input": product_input},
        )
        self._check_user_errors(data, "productUpdate")
        payload = data.get("productUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_PRODUCT,
            data={
                "product": self._normalise_product(
                    payload.get("product") or {}
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        product_id = params.get("id") or params.get("product_id")
        if not isinstance(product_id, str) or not product_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the product) is required",
            )
        data = self._gql(_DELETE_PRODUCT_MUTATION, {
            "input": {"id": product_id.strip()},
        })
        self._check_user_errors(data, "productDelete")
        payload = data.get("productDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_PRODUCT,
            data={
                "deleted_id": payload.get("deletedProductId", "") or "",
            },
        )

    # ── Variants bulk update ───────────────────────────────────────

    def _update_variants(self, params: dict[str, Any]) -> Any:
        product_id = params.get("product_id") or params.get("productId")
        if not isinstance(product_id, str) or not product_id.strip():
            raise AdapterValidationError(
                self.name,
                "'product_id' (Shopify GID for the product) is required",
            )
        raw_variants = params.get("variants")
        if not isinstance(raw_variants, list) or not raw_variants:
            raise AdapterValidationError(
                self.name,
                "'variants' must be a non-empty list",
            )
        variants_input = [
            self._build_variant_input(v, i)
            for i, v in enumerate(raw_variants)
        ]
        data = self._gql(_VARIANTS_BULK_UPDATE_MUTATION, {
            "productId": product_id.strip(),
            "variants": variants_input,
        })
        self._check_user_errors(data, "productVariantsBulkUpdate")
        payload = data.get("productVariantsBulkUpdate") or {}
        nodes = payload.get("productVariants") or []
        variants = [
            self._normalise_variant(v) for v in nodes if isinstance(v, dict)
        ]
        return self._success(
            Capability.SHOPIFY_UPDATE_VARIANTS,
            data={
                "variants": variants,
                "count": len(variants),
            },
        )

    # ── Input builders ─────────────────────────────────────────────

    def _build_product_input(
        self, params: dict[str, Any], for_update: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        if for_update:
            product_id = params.get("id") or params.get("product_id")
            if not isinstance(product_id, str) or not product_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'id' (Shopify GID for the product) is required for update",
                )
            out["id"] = product_id.strip()

        title = params.get("title")
        if title is not None:
            if not isinstance(title, str):
                raise AdapterValidationError(
                    self.name, "'title' must be a string",
                )
            if title.strip():
                out["title"] = title.strip()

        if not for_update and "title" not in out:
            raise AdapterValidationError(
                self.name, "'title' is required to create a product",
            )

        description = params.get("description") or params.get("description_html")
        if description is not None:
            if not isinstance(description, str):
                raise AdapterValidationError(
                    self.name, "'description' must be a string",
                )
            out["descriptionHtml"] = description

        status = params.get("status")
        if status is not None:
            if not isinstance(status, str) or status.upper() not in _VALID_STATUSES:
                raise AdapterValidationError(
                    self.name,
                    f"'status' must be one of: {sorted(_VALID_STATUSES)}",
                )
            out["status"] = status.upper()

        vendor = params.get("vendor")
        if vendor is not None:
            if not isinstance(vendor, str):
                raise AdapterValidationError(
                    self.name, "'vendor' must be a string",
                )
            out["vendor"] = vendor

        product_type = params.get("product_type") or params.get("productType")
        if product_type is not None:
            if not isinstance(product_type, str):
                raise AdapterValidationError(
                    self.name, "'product_type' must be a string",
                )
            out["productType"] = product_type

        tags = params.get("tags")
        if tags is not None:
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not isinstance(tags, list) or not all(
                isinstance(t, str) for t in tags
            ):
                raise AdapterValidationError(
                    self.name,
                    "'tags' must be a string (comma-separated) or list of strings",
                )
            out["tags"] = tags

        handle = params.get("handle")
        if handle is not None:
            if not isinstance(handle, str):
                raise AdapterValidationError(
                    self.name, "'handle' must be a string",
                )
            out["handle"] = handle.strip()

        # SEO fields. Shopify's ProductInput has a nested
        # ``seo: SEOInput { title, description }`` shape; the
        # friendly form accepts the flat ``seo_title`` /
        # ``seo_description`` keys (matches search_optimization
        # engine output).
        seo_title = params.get("seo_title")
        seo_description = params.get("seo_description")
        if seo_title is not None or seo_description is not None:
            seo: dict[str, Any] = {}
            if seo_title is not None:
                if not isinstance(seo_title, str):
                    raise AdapterValidationError(
                        self.name, "'seo_title' must be a string",
                    )
                seo["title"] = seo_title.strip()
            if seo_description is not None:
                if not isinstance(seo_description, str):
                    raise AdapterValidationError(
                        self.name,
                        "'seo_description' must be a string",
                    )
                seo["description"] = seo_description.strip()
            if seo:
                out["seo"] = seo

        return out

    def _build_variant_input(
        self, raw: Any, index: int,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name, f"variants[{index}] must be a dict",
            )
        variant_id = raw.get("id") or raw.get("variant_id")
        if not isinstance(variant_id, str) or not variant_id.strip():
            raise AdapterValidationError(
                self.name,
                f"variants[{index}] missing 'id' (variant GID)",
            )
        out: dict[str, Any] = {"id": variant_id.strip()}

        if "price" in raw and raw["price"] is not None:
            out["price"] = self._coerce_money(
                raw["price"], f"variants[{index}].price",
            )

        if "compare_at_price" in raw or "compareAtPrice" in raw:
            value = raw.get("compare_at_price") or raw.get("compareAtPrice")
            if value is not None:
                out["compareAtPrice"] = self._coerce_money(
                    value, f"variants[{index}].compare_at_price",
                )

        sku = raw.get("sku")
        if sku is not None:
            if not isinstance(sku, str):
                raise AdapterValidationError(
                    self.name,
                    f"variants[{index}] 'sku' must be a string",
                )
            out["sku"] = sku

        barcode = raw.get("barcode")
        if barcode is not None:
            if not isinstance(barcode, str):
                raise AdapterValidationError(
                    self.name,
                    f"variants[{index}] 'barcode' must be a string",
                )
            out["barcode"] = barcode

        # W963-166: inventory_policy controls oversell behavior.
        # CONTINUE = allow customer to order even when stock=0
        # (the right default for dropshipping stores where the
        # supplier ships on demand). DENY = block when out of
        # stock (the right default for own-inventory stores).
        # Without this set, Shopify defaults to DENY -- which
        # combined with the platform's default 0 stock on new
        # products meant every autonomously-created product
        # showed 'Sold Out' to customers regardless of price.
        ip = raw.get("inventory_policy") or raw.get(
            "inventoryPolicy",
        )
        if ip is not None:
            if not isinstance(ip, str) or (
                ip.upper() not in ("CONTINUE", "DENY")
            ):
                raise AdapterValidationError(
                    self.name,
                    f"variants[{index}] 'inventory_policy' "
                    "must be 'CONTINUE' or 'DENY'",
                )
            out["inventoryPolicy"] = ip.upper()

        return out

    def _coerce_money(self, value: Any, label: str) -> str:
        if isinstance(value, str):
            try:
                float(value)
            except ValueError as exc:
                raise AdapterValidationError(
                    self.name,
                    f"{label} must be numeric, got {value!r}",
                ) from exc
            return value
        if isinstance(value, bool):
            raise AdapterValidationError(
                self.name, f"{label} must be numeric, got bool",
            )
        if isinstance(value, (int, float)):
            return str(value)
        raise AdapterValidationError(
            self.name, f"{label} must be numeric or string-numeric",
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_product(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        price_range = node.get("priceRangeV2") or {}
        min_p = price_range.get("minVariantPrice") or {}
        max_p = price_range.get("maxVariantPrice") or {}
        # W962-8/9 bugfix: emit image_count + variant_count +
        # seo so catalog_quality / product_seo discoverers can
        # operate on LIST results instead of needing per-
        # product SHOPIFY_FETCH_PRODUCTS (catalog_quality
        # was always tagging "needs-images" because the field
        # was absent; product_seo was always proposing both
        # meta fields and CLOBBERING merchant-set SEO).
        image_edges = (
            (node.get("images") or {}).get("edges") or []
        )
        variants_count_raw = node.get("variantsCount") or {}
        seo_raw = node.get("seo") or {}
        # W963-164: emit a flat ``variants`` list when the
        # CREATE response carries variants(first: 1). The LIST
        # path doesn't fetch variants so the field stays empty
        # there. Downstream dispatchers (create_draft_product
        # price-set follow-up) read this to find the default
        # variant id without a second GET round-trip.
        variants_out: list[dict[str, Any]] = []
        variants_edges_raw = (
            node.get("variants") or {}
        ).get("edges") or []
        for edge in variants_edges_raw:
            if not isinstance(edge, dict):
                continue
            v_node = edge.get("node") or {}
            if not isinstance(v_node, dict):
                continue
            variants_out.append({
                "id": v_node.get("id", "") or "",
                "price": v_node.get("price", "") or "",
                "sku": v_node.get("sku", "") or "",
            })

        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "handle": node.get("handle", "") or "",
            "status": node.get("status", "") or "",
            "vendor": node.get("vendor", "") or "",
            "product_type": node.get("productType", "") or "",
            "tags": list(node.get("tags") or []),
            "description": node.get("description", "") or "",
            "description_html": node.get("descriptionHtml", "") or "",
            "total_inventory": int(node.get("totalInventory") or 0),
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "price_min": min_p.get("amount", "") or "",
            "price_max": max_p.get("amount", "") or "",
            "currency_code": (
                min_p.get("currencyCode", "")
                or max_p.get("currencyCode", "")
                or ""
            ),
            "image_count": len(image_edges),
            "variant_count": int(
                variants_count_raw.get("count", 0) or 0
            ),
            "variants": variants_out,
            "seo": {
                "title": seo_raw.get("title", "") or "",
                "description": seo_raw.get(
                    "description", "",
                ) or "",
            },
        }

    @classmethod
    def _normalise_product_with_variants(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        base = cls._normalise_product(node)
        if not base:
            return {}
        variant_edges = (node.get("variants") or {}).get("edges") or []
        base["variants"] = [
            cls._normalise_variant(edge.get("node") or {})
            for edge in variant_edges if isinstance(edge, dict)
        ]
        image_edges = (node.get("images") or {}).get("edges") or []
        base["images"] = [
            {
                "id": (edge.get("node") or {}).get("id", "") or "",
                "url": (edge.get("node") or {}).get("url", "") or "",
                "alt_text": (edge.get("node") or {}).get("altText", "") or "",
            }
            for edge in image_edges if isinstance(edge, dict)
        ]
        return base

    @staticmethod
    def _normalise_variant(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "sku": node.get("sku", "") or "",
            "price": node.get("price", "") or "",
            "compare_at_price": node.get("compareAtPrice", "") or "",
            "inventory_quantity": int(node.get("inventoryQuantity") or 0),
            "inventory_policy": node.get("inventoryPolicy", "") or "",
            "barcode": node.get("barcode", "") or "",
            "position": int(node.get("position") or 0),
        }

    # ── Tag / Untag (W963-159) ─────────────────────────────────────

    def _tag(self, params: dict[str, Any], add: bool) -> Any:
        """Additive tagsAdd / tagsRemove against a product.

        Shopify's ``tagsAdd`` mutation merges -- existing tags are
        preserved (unlike productUpdate which replaces). Same shape
        used by orders.py + customers.py tag paths.
        """
        product_id = (
            params.get("id") or params.get("product_id")
        )
        if not isinstance(product_id, str) or not product_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the product) is required",
            )
        raw_tags = params.get("tags")
        if isinstance(raw_tags, str):
            raw_tags = [
                t.strip() for t in raw_tags.split(",")
                if t.strip()
            ]
        if (
            not isinstance(raw_tags, list)
            or not raw_tags
            or not all(isinstance(t, str) for t in raw_tags)
        ):
            raise AdapterValidationError(
                self.name,
                "'tags' must be a non-empty list of strings or "
                "comma-separated string",
            )
        mutation = (
            _PRODUCT_TAGS_ADD_MUTATION if add
            else _PRODUCT_TAGS_REMOVE_MUTATION
        )
        mutation_name = "tagsAdd" if add else "tagsRemove"
        capability = (
            Capability.SHOPIFY_TAG_PRODUCT if add
            else Capability.SHOPIFY_UNTAG_PRODUCT
        )
        data = self._gql(mutation, {
            "id": product_id.strip(),
            "tags": raw_tags,
        })
        self._check_user_errors(data, mutation_name)
        payload = data.get(mutation_name) or {}
        node = payload.get("node") or {}
        return self._success(
            capability,
            data={
                "id": node.get("id", "") or "",
                "tags": list(node.get("tags") or []),
            },
        )


_PRODUCT_TAGS_ADD_MUTATION = """
mutation tagsAdd($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) {
    node {
      id
      ... on Product { tags }
    }
    userErrors { field message }
  }
}
"""

_PRODUCT_TAGS_REMOVE_MUTATION = """
mutation tagsRemove($id: ID!, $tags: [String!]!) {
  tagsRemove(id: $id, tags: $tags) {
    node {
      id
      ... on Product { tags }
    }
    userErrors { field message }
  }
}
"""
