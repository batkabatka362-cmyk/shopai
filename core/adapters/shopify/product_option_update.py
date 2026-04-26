"""ShopifyProductOptionUpdateAdapter — single option update.

Companion to ``product_options.py`` (productOptionsCreate /
Delete / Reorder). The bulk options adapter operates on the
SET of options on a product; this adapter wraps the single-
option update mutation that lets callers rename one axis,
reposition it, and add/rename/drop individual values within
it — all atomically with control over how variants are
regenerated.

ShopAI's catalog-evolution engine uses this:

  * **Rename a value.** Operator decides "Royal Blue" should
    just be "Blue". Engine calls update with
    optionValuesToUpdate=[{id, name="Blue"}]; existing variants
    that referenced Royal Blue get the new label without
    rebuilding the variant matrix.
  * **Add a value to an existing axis.** New SKU launches in
    "Forest Green" — engine adds {name="Forest Green"} via
    optionValuesToAdd. variantStrategy=MANAGE auto-creates
    variants for every other axis combination.
  * **Drop a discontinued value.** "Cherry Red" gets retired;
    optionValuesToDelete=[id] removes the value AND any variants
    that depended on it.

Capability:

  * ``SHOPIFY_UPDATE_PRODUCT_OPTION`` — productOptionUpdate.
    Pattern A: productId at field level. The OptionUpdateInput
    dict carries the option's id + optional renames /
    repositioning. Sibling args
    ``optionValuesToAdd``/``Update``/``Delete`` mutate the
    value set.

variantStrategy controls how Shopify reconciles existing
variants:
  * ``MANAGE`` — auto-create variants for new value
    combinations, auto-delete variants that lose a referenced
    value (the typical engine choice).
  * ``LEAVE_AS_IS`` — leave the variant matrix alone; caller
    will manage variants directly via productVariants*Bulk
    mutations.

UserError variant is ``ProductOptionUpdateUserError`` (has
``code``).
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


_UPDATE_OPTION_MUTATION = f"""
mutation productOptionUpdate(
  $productId: ID!,
  $option: OptionUpdateInput!,
  $optionValuesToAdd: [OptionValueCreateInput!],
  $optionValuesToUpdate: [OptionValueUpdateInput!],
  $optionValuesToDelete: [ID!],
  $variantStrategy: ProductOptionUpdateVariantStrategy
) {{
  productOptionUpdate(
    productId: $productId,
    option: $option,
    optionValuesToAdd: $optionValuesToAdd,
    optionValuesToUpdate: $optionValuesToUpdate,
    optionValuesToDelete: $optionValuesToDelete,
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


_VALID_VARIANT_STRATEGIES = {"LEAVE_AS_IS", "MANAGE"}


class ShopifyProductOptionUpdateAdapter(ShopifyBaseAdapter):
    name = "shopify_product_option_update"
    capabilities = {Capability.SHOPIFY_UPDATE_PRODUCT_OPTION}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPDATE_PRODUCT_OPTION:
            return self._update(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _update(self, params: dict[str, Any]) -> Any:
        product_id = (
            params.get("product_id")
            or params.get("productId")
        )
        if not isinstance(product_id, str) or not product_id.strip():
            raise AdapterValidationError(
                self.name,
                "'product_id' (Shopify GID for the product) is required",
            )

        option = self._build_option(params.get("option"))

        variables: dict[str, Any] = {
            "productId": product_id.strip(),
            "option": option,
        }

        # Optional sibling lists. Don't emit nulls for unused ones —
        # mirrors Pattern C from discount_bulk_delete (Shopify
        # treats null variables as "set" for some mutations).
        # Adapter only includes the variables actually used.
        adds_raw = (
            params.get("option_values_to_add")
            or params.get("optionValuesToAdd")
        )
        if adds_raw is not None:
            variables["optionValuesToAdd"] = self._build_value_creates(
                adds_raw,
            )

        updates_raw = (
            params.get("option_values_to_update")
            or params.get("optionValuesToUpdate")
        )
        if updates_raw is not None:
            variables["optionValuesToUpdate"] = (
                self._build_value_updates(updates_raw)
            )

        deletes_raw = (
            params.get("option_values_to_delete")
            or params.get("optionValuesToDelete")
        )
        if deletes_raw is not None:
            variables["optionValuesToDelete"] = (
                self._build_value_deletes(deletes_raw)
            )

        strategy = (
            params.get("variant_strategy")
            or params.get("variantStrategy")
        )
        if strategy is not None:
            if not isinstance(strategy, str):
                raise AdapterValidationError(
                    self.name, "'variant_strategy' must be a string",
                )
            up = strategy.strip().upper()
            if up not in _VALID_VARIANT_STRATEGIES:
                raise AdapterValidationError(
                    self.name,
                    f"'variant_strategy' must be one of "
                    f"{sorted(_VALID_VARIANT_STRATEGIES)}",
                )
            variables["variantStrategy"] = up

        # Build the GraphQL mutation dynamically so unused variables
        # aren't declared (Pattern C: even null-defaulted lists can
        # tickle "exactly one of" rejections in some Shopify
        # mutations; play it safe by mirroring only-used-vars).
        mutation = self._compose_mutation(variables)

        data = self._gql(mutation, variables)
        self._check_user_errors(data, "productOptionUpdate")
        payload = data.get("productOptionUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_PRODUCT_OPTION,
            data={
                "product": self._normalise_product(
                    payload.get("product") or {}
                ),
            },
        )

    # ── Builders ───────────────────────────────────────────────────

    def _build_option(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'option' must be a dict {id, name?, position?, ...}",
            )
        opt_id = raw.get("id") or raw.get("option_id")
        if not isinstance(opt_id, str) or not opt_id.strip():
            raise AdapterValidationError(
                self.name,
                "'option.id' (ProductOption GID) is required",
            )
        out: dict[str, Any] = {"id": opt_id.strip()}
        name = raw.get("name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise AdapterValidationError(
                    self.name, "'option.name' must be a non-empty string",
                )
            out["name"] = name.strip()
        position = raw.get("position")
        if position is not None:
            try:
                pos_int = int(position)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'option.position' must be an int",
                ) from exc
            out["position"] = pos_int
        linked = raw.get("linked_metafield") or raw.get("linkedMetafield")
        if linked is not None:
            if not isinstance(linked, dict):
                raise AdapterValidationError(
                    self.name,
                    "'option.linked_metafield' must be a dict matching "
                    "LinkedMetafieldUpdateInput",
                )
            out["linkedMetafield"] = linked
        return out

    def _build_value_creates(
        self, raw: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'option_values_to_add' must be a non-empty list",
            )
        out: list[dict[str, Any]] = []
        for i, v in enumerate(raw):
            if isinstance(v, str):
                if not v.strip():
                    raise AdapterValidationError(
                        self.name,
                        f"option_values_to_add[{i}] is blank",
                    )
                out.append({"name": v.strip()})
                continue
            if not isinstance(v, dict):
                raise AdapterValidationError(
                    self.name,
                    f"option_values_to_add[{i}] must be a string or dict",
                )
            name = v.get("name")
            if not isinstance(name, str) or not name.strip():
                raise AdapterValidationError(
                    self.name,
                    f"option_values_to_add[{i}] missing 'name'",
                )
            entry: dict[str, Any] = {"name": name.strip()}
            linked_value = (
                v.get("linked_metafield_value")
                or v.get("linkedMetafieldValue")
            )
            if linked_value is not None:
                if not isinstance(linked_value, str):
                    raise AdapterValidationError(
                        self.name,
                        f"option_values_to_add[{i}]."
                        "linked_metafield_value must be a string",
                    )
                entry["linkedMetafieldValue"] = linked_value
            out.append(entry)
        return out

    def _build_value_updates(
        self, raw: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'option_values_to_update' must be a non-empty list of "
                "{id, name?, linked_metafield_value?} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, v in enumerate(raw):
            if not isinstance(v, dict):
                raise AdapterValidationError(
                    self.name,
                    f"option_values_to_update[{i}] must be a dict",
                )
            v_id = v.get("id") or v.get("value_id")
            if not isinstance(v_id, str) or not v_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"option_values_to_update[{i}] missing 'id'",
                )
            entry: dict[str, Any] = {"id": v_id.strip()}
            name = v.get("name")
            if name is not None:
                if not isinstance(name, str) or not name.strip():
                    raise AdapterValidationError(
                        self.name,
                        f"option_values_to_update[{i}].name must be a "
                        "non-empty string",
                    )
                entry["name"] = name.strip()
            linked_value = (
                v.get("linked_metafield_value")
                or v.get("linkedMetafieldValue")
            )
            if linked_value is not None:
                if not isinstance(linked_value, str):
                    raise AdapterValidationError(
                        self.name,
                        f"option_values_to_update[{i}]."
                        "linked_metafield_value must be a string",
                    )
                entry["linkedMetafieldValue"] = linked_value
            out.append(entry)
        return out

    def _build_value_deletes(self, raw: Any) -> list[str]:
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not raw or not all(
            isinstance(v, str) for v in raw
        ):
            raise AdapterValidationError(
                self.name,
                "'option_values_to_delete' must be a non-empty list of "
                "OptionValue GID strings",
            )
        cleaned = [v.strip() for v in raw if v.strip()]
        if not cleaned:
            raise AdapterValidationError(
                self.name,
                "'option_values_to_delete' contained only blanks",
            )
        return cleaned

    @staticmethod
    def _compose_mutation(variables: dict[str, Any]) -> str:
        # Generate a productOptionUpdate query that only declares the
        # variables actually used. Mirrors discount_bulk_delete's
        # Pattern C handling — emit only the args the caller is
        # actually setting.
        decls = ["$productId: ID!", "$option: OptionUpdateInput!"]
        args = ["productId: $productId", "option: $option"]
        if "optionValuesToAdd" in variables:
            decls.append("$optionValuesToAdd: [OptionValueCreateInput!]")
            args.append("optionValuesToAdd: $optionValuesToAdd")
        if "optionValuesToUpdate" in variables:
            decls.append(
                "$optionValuesToUpdate: [OptionValueUpdateInput!]",
            )
            args.append("optionValuesToUpdate: $optionValuesToUpdate")
        if "optionValuesToDelete" in variables:
            decls.append("$optionValuesToDelete: [ID!]")
            args.append("optionValuesToDelete: $optionValuesToDelete")
        if "variantStrategy" in variables:
            decls.append(
                "$variantStrategy: ProductOptionUpdateVariantStrategy",
            )
            args.append("variantStrategy: $variantStrategy")
        return f"""
mutation productOptionUpdate({", ".join(decls)}) {{
  productOptionUpdate({", ".join(args)}) {{
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
