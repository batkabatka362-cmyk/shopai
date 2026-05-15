"""ShopifyProductOptionsAdapter — variant option set management.

Companion to ``products.py`` (CRUD on the product itself) and
``product_media.py`` (variant media wiring). Product options
are the per-product configuration of variant axes (Color, Size,
Material, …); each option has a name + a list of allowed
values. The variants ARE the cartesian product of those values.

ShopAI's catalog + creative engines lean on this:

  * **Add a new axis post-launch.** Product launched with just
    a Size option; later the merchant adds Color. Engine calls
    optionsCreate with name='Color' + values=['Red','Blue',...]
    and Shopify regenerates the variant matrix.
  * **Drop a deprecated axis.** Pricing engine retires Material
    after consolidating to a single fabric. optionsDelete
    collapses the variant set.
  * **Storefront reorder.** Hero option goes to position 0;
    optionsReorder updates the order without touching values.

Capabilities:

  * ``SHOPIFY_CREATE_PRODUCT_OPTIONS``  — productOptionsCreate.
    Pattern A: productId at field level; options is a list of
    {name, position?, values: [{name}, ...]} dicts.
  * ``SHOPIFY_DELETE_PRODUCT_OPTIONS``  — productOptionsDelete.
    Pattern A: productId + options (list of option GIDs to
    drop).
  * ``SHOPIFY_REORDER_PRODUCT_OPTIONS`` — productOptionsReorder.
    Pattern A: productId + options (list of {id, name?, values?}
    dicts whose order indicates the new positioning).

variantStrategy on Create:
  * ``CREATE`` (default) — Shopify regenerates variants from the
    new option's values × existing variants.
  * ``LEAVE_AS_IS`` — keep current variants; only ADD the option
    structure.

strategy on Delete:
  * ``DEFAULT`` — drop the option and any variants that were
    discriminated by it.
  * ``POSITION`` — collapse position-based discrimination.
  * ``NON_DESTRUCTIVE`` — refuse if any variants would be lost.

UserError variants: ProductOptions*UserError (all have code).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_PRODUCT_FIELDS = """
id
title
handle
options {
  id
  name
  position
  values
}
""".strip()


_CREATE_OPTIONS_MUTATION = f"""
mutation productOptionsCreate(
  $productId: ID!,
  $options: [OptionCreateInput!]!,
  $variantStrategy: ProductOptionCreateVariantStrategy
) {{
  productOptionsCreate(
    productId: $productId,
    options: $options,
    variantStrategy: $variantStrategy
  ) {{
    product {{
      {_PRODUCT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_OPTIONS_MUTATION = f"""
mutation productOptionsDelete(
  $productId: ID!,
  $options: [ID!]!,
  $strategy: ProductOptionDeleteStrategy
) {{
  productOptionsDelete(
    productId: $productId,
    options: $options,
    strategy: $strategy
  ) {{
    deletedOptionsIds
    product {{
      {_PRODUCT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_REORDER_OPTIONS_MUTATION = f"""
mutation productOptionsReorder(
  $productId: ID!,
  $options: [OptionReorderInput!]!
) {{
  productOptionsReorder(
    productId: $productId,
    options: $options
  ) {{
    product {{
      {_PRODUCT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_VALID_CREATE_STRATEGIES = {"CREATE", "LEAVE_AS_IS"}
_VALID_DELETE_STRATEGIES = {"DEFAULT", "POSITION", "NON_DESTRUCTIVE"}


class ShopifyProductOptionsAdapter(ShopifyBaseAdapter):
    name = "shopify_product_options"
    capabilities = {
        Capability.SHOPIFY_CREATE_PRODUCT_OPTIONS,
        Capability.SHOPIFY_DELETE_PRODUCT_OPTIONS,
        Capability.SHOPIFY_REORDER_PRODUCT_OPTIONS,
    }
    required_scopes = frozenset({"read_products", "write_products"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_PRODUCT_OPTIONS:
            return self._create(params)
        if capability == Capability.SHOPIFY_DELETE_PRODUCT_OPTIONS:
            return self._delete(params)
        if capability == Capability.SHOPIFY_REORDER_PRODUCT_OPTIONS:
            return self._reorder(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        product_id = self._extract_product_id(params)
        options = self._build_create_options(params.get("options"))

        variables: dict[str, Any] = {
            "productId": product_id,
            "options": options,
        }
        strategy = (
            params.get("variant_strategy") or params.get("variantStrategy")
        )
        if strategy is not None:
            if not isinstance(strategy, str):
                raise AdapterValidationError(
                    self.name, "'variant_strategy' must be a string",
                )
            up = strategy.strip().upper()
            if up not in _VALID_CREATE_STRATEGIES:
                raise AdapterValidationError(
                    self.name,
                    f"'variant_strategy' must be one of "
                    f"{sorted(_VALID_CREATE_STRATEGIES)}",
                )
            variables["variantStrategy"] = up

        data = self._gql(_CREATE_OPTIONS_MUTATION, variables)
        self._check_user_errors(data, "productOptionsCreate")
        payload = data.get("productOptionsCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_PRODUCT_OPTIONS,
            data={
                "product": self._normalise_product(
                    payload.get("product") or {}
                ),
                "added_count": len(options),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        product_id = self._extract_product_id(params)
        option_ids = self._extract_option_ids(params)

        variables: dict[str, Any] = {
            "productId": product_id,
            "options": option_ids,
        }
        strategy = params.get("strategy")
        if strategy is not None:
            if not isinstance(strategy, str):
                raise AdapterValidationError(
                    self.name, "'strategy' must be a string",
                )
            up = strategy.strip().upper()
            if up not in _VALID_DELETE_STRATEGIES:
                raise AdapterValidationError(
                    self.name,
                    f"'strategy' must be one of "
                    f"{sorted(_VALID_DELETE_STRATEGIES)}",
                )
            variables["strategy"] = up

        data = self._gql(_DELETE_OPTIONS_MUTATION, variables)
        self._check_user_errors(data, "productOptionsDelete")
        payload = data.get("productOptionsDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_PRODUCT_OPTIONS,
            data={
                "product": self._normalise_product(
                    payload.get("product") or {}
                ),
                "deleted_option_ids": list(
                    payload.get("deletedOptionsIds") or []
                ),
                "deleted_count": len(
                    payload.get("deletedOptionsIds") or []
                ),
            },
        )

    # ── Reorder ────────────────────────────────────────────────────

    def _reorder(self, params: dict[str, Any]) -> Any:
        product_id = self._extract_product_id(params)
        options = self._build_reorder_options(params.get("options"))
        data = self._gql(_REORDER_OPTIONS_MUTATION, {
            "productId": product_id, "options": options,
        })
        self._check_user_errors(data, "productOptionsReorder")
        payload = data.get("productOptionsReorder") or {}
        return self._success(
            Capability.SHOPIFY_REORDER_PRODUCT_OPTIONS,
            data={
                "product": self._normalise_product(
                    payload.get("product") or {}
                ),
                "reordered_count": len(options),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_product_id(self, params: dict[str, Any]) -> str:
        product_id = (
            params.get("product_id")
            or params.get("productId")
            or params.get("id")
        )
        if not isinstance(product_id, str) or not product_id.strip():
            raise AdapterValidationError(
                self.name,
                "'product_id' (Shopify GID for the product) is required",
            )
        return product_id.strip()

    def _extract_option_ids(self, params: dict[str, Any]) -> list[str]:
        raw = params.get("options") or params.get("option_ids")
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'options' must be a non-empty list of option GIDs "
                "(or a single GID string) to delete",
            )
        if not all(isinstance(o, str) for o in raw):
            raise AdapterValidationError(
                self.name,
                "'options' must contain only option GID strings",
            )
        ids = [o.strip() for o in raw if o.strip()]
        if not ids:
            raise AdapterValidationError(
                self.name, "'options' contained only blanks",
            )
        return ids

    def _build_create_options(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'options' must be a non-empty list of "
                "{name, values:[{name}, ...]} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, opt in enumerate(raw):
            if not isinstance(opt, dict):
                raise AdapterValidationError(
                    self.name, f"options[{i}] must be a dict",
                )
            name = opt.get("name")
            if not isinstance(name, str) or not name.strip():
                raise AdapterValidationError(
                    self.name,
                    f"options[{i}] missing 'name' (e.g. 'Color')",
                )
            entry: dict[str, Any] = {"name": name.strip()}

            position = opt.get("position")
            if position is not None:
                try:
                    pos_int = int(position)
                except (TypeError, ValueError) as exc:
                    raise AdapterValidationError(
                        self.name,
                        f"options[{i}].position must be an int",
                    ) from exc
                entry["position"] = pos_int

            values_raw = opt.get("values")
            if values_raw is not None:
                entry["values"] = self._build_values(
                    values_raw, label=f"options[{i}].values",
                )

            out.append(entry)
        return out

    def _build_reorder_options(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'options' must be a non-empty list whose order "
                "indicates the new option positioning",
            )
        out: list[dict[str, Any]] = []
        for i, opt in enumerate(raw):
            if isinstance(opt, str):
                # Bare GID — adapter wraps it as {id}.
                opt = {"id": opt}
            if not isinstance(opt, dict):
                raise AdapterValidationError(
                    self.name, f"options[{i}] must be a dict or GID string",
                )
            opt_id = opt.get("id")
            name = opt.get("name")
            # Either id or name (but not nothing).
            if not (
                (isinstance(opt_id, str) and opt_id.strip())
                or (isinstance(name, str) and name.strip())
            ):
                raise AdapterValidationError(
                    self.name,
                    f"options[{i}] must have either 'id' or 'name'",
                )
            entry: dict[str, Any] = {}
            if isinstance(opt_id, str) and opt_id.strip():
                entry["id"] = opt_id.strip()
            if isinstance(name, str) and name.strip():
                entry["name"] = name.strip()
            out.append(entry)
        return out

    def _build_values(
        self, raw: Any, *, label: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                f"'{label}' must be a non-empty list of values",
            )
        out: list[dict[str, Any]] = []
        for i, v in enumerate(raw):
            # Two friendly forms:
            #   "Red" — bare string, adapter wraps as {name: "Red"}
            #   {"name": "Red", "linked_metafield_value": "..."}
            if isinstance(v, str):
                if not v.strip():
                    raise AdapterValidationError(
                        self.name, f"{label}[{i}] is blank",
                    )
                out.append({"name": v.strip()})
                continue
            if not isinstance(v, dict):
                raise AdapterValidationError(
                    self.name,
                    f"{label}[{i}] must be a string or "
                    "{name, ...} dict",
                )
            name = v.get("name")
            if not isinstance(name, str) or not name.strip():
                raise AdapterValidationError(
                    self.name,
                    f"{label}[{i}] missing 'name' (e.g. 'Red')",
                )
            entry: dict[str, Any] = {"name": name.strip()}
            linked = (
                v.get("linked_metafield_value")
                or v.get("linkedMetafieldValue")
            )
            if linked is not None:
                if not isinstance(linked, str):
                    raise AdapterValidationError(
                        self.name,
                        f"{label}[{i}].linked_metafield_value must be "
                        "a string",
                    )
                entry["linkedMetafieldValue"] = linked
            out.append(entry)
        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_product(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        options_raw = node.get("options") or []
        options: list[dict[str, Any]] = []
        if isinstance(options_raw, list):
            for o in options_raw:
                if not isinstance(o, dict):
                    continue
                try:
                    pos = int(o.get("position") or 0)
                except (TypeError, ValueError):
                    pos = 0
                vals_raw = o.get("values") or []
                vals = [v for v in vals_raw if isinstance(v, str)]
                options.append({
                    "id": o.get("id", "") or "",
                    "name": o.get("name", "") or "",
                    "position": pos,
                    "values": vals,
                })
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "handle": node.get("handle", "") or "",
            "options": options,
        }
