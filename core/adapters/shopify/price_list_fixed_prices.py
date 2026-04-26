"""ShopifyPriceListFixedPricesAdapter — B2B per-variant price overrides.

Companion to ``price_lists.py`` (LIST/GET/CREATE/UPDATE/DELETE
on the price list itself). Each price list is the umbrella; the
per-variant fixed-price overrides — the actual numbers a B2B
buyer in that price list pays for SKU X — live behind separate
mutations:

  * **Tier launch.** B2B engine creates a "Wholesale Tier 2"
    price list, then loops this adapter to add the SKU-by-SKU
    overrides (10% off MAP for tier 2 buyers).
  * **Quarterly repricing.** Pricing engine recalculates the
    discount table; ``priceListFixedPricesUpdate`` adds the new
    set in one call AND deletes the variants that fell out
    of the catalogue — atomic swap.
  * **SKU retirement.** When a variant is sunset, drop it from
    every active price list with ``priceListFixedPricesDelete``.

Capabilities:

  * ``SHOPIFY_ADD_PRICE_LIST_PRICES``    — priceListFixedPricesAdd.
    Pattern A: priceListId at field level; prices is a list of
    {variantId, price{amount, currencyCode}, compareAtPrice?}.
  * ``SHOPIFY_DELETE_PRICE_LIST_PRICES`` — priceListFixedPricesDelete.
    Pattern A: priceListId + variantIds at field level.
  * ``SHOPIFY_UPDATE_PRICE_LIST_PRICES`` — priceListFixedPricesUpdate.
    Pattern A: priceListId at field level; pricesToAdd +
    variantIdsToDelete arrays do an atomic swap.

Pattern G: per-adapter MoneyInput shaping (amount + currency_code
→ {amount, currencyCode}) inline rather than reaching for a
shared util — same convention as discount + gift-card adapters.

UserError variant is ``PriceListPriceUserError`` (has ``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ADD_PRICES_MUTATION = """
mutation priceListFixedPricesAdd(
  $priceListId: ID!,
  $prices: [PriceListPriceInput!]!
) {
  priceListFixedPricesAdd(
    priceListId: $priceListId,
    prices: $prices
  ) {
    prices {
      compareAtPrice {
        amount
        currencyCode
      }
      price {
        amount
        currencyCode
      }
      variant {
        id
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DELETE_PRICES_MUTATION = """
mutation priceListFixedPricesDelete(
  $priceListId: ID!,
  $variantIds: [ID!]!
) {
  priceListFixedPricesDelete(
    priceListId: $priceListId,
    variantIds: $variantIds
  ) {
    deletedFixedPriceVariantIds
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_UPDATE_PRICES_MUTATION = """
mutation priceListFixedPricesUpdate(
  $priceListId: ID!,
  $pricesToAdd: [PriceListPriceInput!]!,
  $variantIdsToDelete: [ID!]!
) {
  priceListFixedPricesUpdate(
    priceListId: $priceListId,
    pricesToAdd: $pricesToAdd,
    variantIdsToDelete: $variantIdsToDelete
  ) {
    priceList {
      id
      name
    }
    pricesAdded {
      variant {
        id
      }
      price {
        amount
        currencyCode
      }
    }
    deletedFixedPriceVariantIds
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifyPriceListFixedPricesAdapter(ShopifyBaseAdapter):
    name = "shopify_price_list_fixed_prices"
    capabilities = {
        Capability.SHOPIFY_ADD_PRICE_LIST_PRICES,
        Capability.SHOPIFY_DELETE_PRICE_LIST_PRICES,
        Capability.SHOPIFY_UPDATE_PRICE_LIST_PRICES,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_ADD_PRICE_LIST_PRICES:
            return self._add(params)
        if capability == Capability.SHOPIFY_DELETE_PRICE_LIST_PRICES:
            return self._delete(params)
        if capability == Capability.SHOPIFY_UPDATE_PRICE_LIST_PRICES:
            return self._update(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Add ────────────────────────────────────────────────────────

    def _add(self, params: dict[str, Any]) -> Any:
        price_list_id = self._extract_price_list_id(params)
        prices = self._build_prices(
            params.get("prices"), label="prices",
        )
        data = self._gql(_ADD_PRICES_MUTATION, {
            "priceListId": price_list_id, "prices": prices,
        })
        self._check_user_errors(data, "priceListFixedPricesAdd")
        payload = data.get("priceListFixedPricesAdd") or {}
        return self._success(
            Capability.SHOPIFY_ADD_PRICE_LIST_PRICES,
            data={
                "prices": [
                    self._normalise_price(p)
                    for p in (payload.get("prices") or [])
                    if isinstance(p, dict)
                ],
                "added_count": len(prices),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        price_list_id = self._extract_price_list_id(params)
        variant_ids = self._extract_variant_ids(params)
        data = self._gql(_DELETE_PRICES_MUTATION, {
            "priceListId": price_list_id, "variantIds": variant_ids,
        })
        self._check_user_errors(data, "priceListFixedPricesDelete")
        payload = data.get("priceListFixedPricesDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_PRICE_LIST_PRICES,
            data={
                "deleted_variant_ids": list(
                    payload.get("deletedFixedPriceVariantIds") or []
                ),
                "deleted_count": len(
                    payload.get("deletedFixedPriceVariantIds") or []
                ),
            },
        )

    # ── Update (atomic add + delete) ───────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        price_list_id = self._extract_price_list_id(params)
        prices_to_add_raw = (
            params.get("prices_to_add")
            or params.get("pricesToAdd")
            or []
        )
        if not isinstance(prices_to_add_raw, list):
            raise AdapterValidationError(
                self.name,
                "'prices_to_add' must be a list (may be empty)",
            )
        prices_to_add = (
            self._build_prices(prices_to_add_raw, label="prices_to_add")
            if prices_to_add_raw else []
        )

        variant_ids_to_delete_raw = (
            params.get("variant_ids_to_delete")
            or params.get("variantIdsToDelete")
            or []
        )
        if isinstance(variant_ids_to_delete_raw, str):
            variant_ids_to_delete_raw = [variant_ids_to_delete_raw]
        if not isinstance(variant_ids_to_delete_raw, list):
            raise AdapterValidationError(
                self.name,
                "'variant_ids_to_delete' must be a list of GIDs "
                "(may be empty)",
            )
        if not all(
            isinstance(v, str) for v in variant_ids_to_delete_raw
        ):
            raise AdapterValidationError(
                self.name,
                "'variant_ids_to_delete' must contain only GID strings",
            )
        variant_ids_to_delete = [
            v.strip() for v in variant_ids_to_delete_raw if v.strip()
        ]

        if not prices_to_add and not variant_ids_to_delete:
            raise AdapterValidationError(
                self.name,
                "no changes — pass at least one of 'prices_to_add' "
                "or 'variant_ids_to_delete'",
            )

        data = self._gql(_UPDATE_PRICES_MUTATION, {
            "priceListId": price_list_id,
            "pricesToAdd": prices_to_add,
            "variantIdsToDelete": variant_ids_to_delete,
        })
        self._check_user_errors(data, "priceListFixedPricesUpdate")
        payload = data.get("priceListFixedPricesUpdate") or {}
        price_list = payload.get("priceList") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_PRICE_LIST_PRICES,
            data={
                "price_list_id": (
                    price_list.get("id", "")
                    if isinstance(price_list, dict) else ""
                ) or "",
                "price_list_name": (
                    price_list.get("name", "")
                    if isinstance(price_list, dict) else ""
                ) or "",
                "prices_added": [
                    self._normalise_price(p)
                    for p in (payload.get("pricesAdded") or [])
                    if isinstance(p, dict)
                ],
                "deleted_variant_ids": list(
                    payload.get("deletedFixedPriceVariantIds") or []
                ),
                "added_count": len(prices_to_add),
                "deleted_count": len(variant_ids_to_delete),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_price_list_id(self, params: dict[str, Any]) -> str:
        pid = (
            params.get("price_list_id")
            or params.get("priceListId")
            or params.get("id")
        )
        if not isinstance(pid, str) or not pid.strip():
            raise AdapterValidationError(
                self.name,
                "'price_list_id' (Shopify GID for the price list) "
                "is required",
            )
        return pid.strip()

    def _extract_variant_ids(
        self, params: dict[str, Any],
    ) -> list[str]:
        raw = (
            params.get("variant_ids")
            or params.get("variantIds")
        )
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'variant_ids' must be a non-empty list of variant GIDs",
            )
        if not all(isinstance(v, str) for v in raw):
            raise AdapterValidationError(
                self.name,
                "'variant_ids' must contain only GID strings",
            )
        ids = [v.strip() for v in raw if v.strip()]
        if not ids:
            raise AdapterValidationError(
                self.name, "'variant_ids' contained only blanks",
            )
        return ids

    def _build_prices(
        self, raw: Any, *, label: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                f"'{label}' must be a non-empty list of "
                "{variant_id, amount, currency_code} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, p in enumerate(raw):
            if not isinstance(p, dict):
                raise AdapterValidationError(
                    self.name, f"{label}[{i}] must be a dict",
                )
            variant_id = p.get("variant_id") or p.get("variantId")
            if not isinstance(variant_id, str) or not variant_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"{label}[{i}] missing 'variant_id'",
                )
            price_money = self._build_money(
                p, "price", required=True, label=f"{label}[{i}].price",
            )
            entry: dict[str, Any] = {
                "variantId": variant_id.strip(),
                "price": price_money,
            }
            compare_money = self._build_money(
                p, "compare_at_price", required=False,
                label=f"{label}[{i}].compare_at_price",
            )
            if compare_money is not None:
                entry["compareAtPrice"] = compare_money
            out.append(entry)
        return out

    def _build_money(
        self,
        source: dict[str, Any],
        prefix: str,
        *,
        required: bool,
        label: str,
    ) -> dict[str, Any] | None:
        # Two friendly forms:
        # 1) flat keys: amount + currency_code (or matching {prefix}_*)
        # 2) nested dict: source[prefix] = {amount, currency_code}
        camel_prefix = (
            "".join(
                word.capitalize() if i else word
                for i, word in enumerate(prefix.split("_"))
            )
        )
        nested = source.get(prefix) or source.get(camel_prefix)
        if isinstance(nested, dict):
            amount = nested.get("amount")
            currency = (
                nested.get("currency_code")
                or nested.get("currencyCode")
                or nested.get("currency")
            )
        else:
            # Flat form: only valid for the primary 'price' field.
            if prefix == "price":
                amount = source.get("amount")
                currency = (
                    source.get("currency_code")
                    or source.get("currencyCode")
                    or source.get("currency")
                )
            else:
                amount = None
                currency = None

        if amount is None and currency is None:
            if required:
                raise AdapterValidationError(
                    self.name,
                    f"'{label}' is required (e.g. {{amount: 19.99, "
                    "currency_code: 'USD'}})",
                )
            return None

        if amount is None or currency is None:
            raise AdapterValidationError(
                self.name,
                f"'{label}' must have both 'amount' and 'currency_code'",
            )
        try:
            amount_decimal = float(amount)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                f"'{label}.amount' must be numeric",
            ) from exc
        if amount_decimal < 0:
            raise AdapterValidationError(
                self.name,
                f"'{label}.amount' must be >= 0",
            )
        if not isinstance(currency, str) or not currency.strip():
            raise AdapterValidationError(
                self.name,
                f"'{label}.currency_code' must be a non-empty string",
            )
        return {
            "amount": f"{amount_decimal:.2f}",
            "currencyCode": currency.strip().upper(),
        }

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_money(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {"amount": 0.0, "currency_code": ""}
        try:
            amount = float(node.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        return {
            "amount": amount,
            "currency_code": node.get("currencyCode", "") or "",
        }

    @classmethod
    def _normalise_price(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        variant = node.get("variant") or {}
        return {
            "variant_id": (
                variant.get("id", "")
                if isinstance(variant, dict) else ""
            ) or "",
            "price": cls._normalise_money(node.get("price")),
            "compare_at_price": cls._normalise_money(
                node.get("compareAtPrice")
            ),
        }
