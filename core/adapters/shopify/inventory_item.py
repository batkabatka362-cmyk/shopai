"""ShopifyInventoryItemAdapter — InventoryItem write surface.

The existing ``inventory.py`` queries InventoryItems and flips
inventoryLevels; ``inventory_activation.py`` activates / deactivates
items at locations; ``inventory_adjust.py`` and
``inventory_shipments.py`` move quantities. The InventoryItem
RECORD itself — cost, country of origin, harmonized customs code,
weight measurement, requires-shipping flag, sku — sat outside all
of them.

ShopAI's pricing + fulfillment + tax engines need this surface:

  * **Cost** — the unit cost feeds margin math; pricing engine
    pushes a refreshed cost when a supplier renegotiates.
  * **Country of origin + HS code** — required for international
    fulfillment customs paperwork. Tax + shipping engines write
    these when a product is added to a market that requires them.
  * **Weight** — feeds shipping rate calculation. Updated when the
    physical-product sourcing engine changes vendors.
  * **Requires shipping / tracked** — toggles for digital goods
    or pre-orders.
  * **SKU** — backfilled when a product is migrated from another
    PIM system.

Capability:

  * ``SHOPIFY_UPDATE_INVENTORY_ITEM`` — inventoryItemUpdate.
    Pattern A: id at field level + InventoryItemInput.

Friendly call shape::

    {"id":                       "gid://shopify/InventoryItem/123",
     "sku":                      "SKU-123-NEW",
     "cost":                     "12.50",
     "tracked":                  True,
     "country_code_of_origin":   "US",      # auto-uppercased
     "province_code_of_origin":  "CA",
     "harmonized_system_code":   "1234.56",
     "country_harmonized_system_codes": [
       {"country_code": "DE", "harmonized_system_code": "1234.56.78"},
     ],
     "weight": {"value": 1.2, "unit": "kg"},  # kg/g/lb/oz
     "requires_shipping":        True}

UserError variant: bare ``UserError`` — no ``code`` field
(probed live: GraphQL rejects ``code`` selection on this mutation,
keeps it on most others). Pattern F applies — drop ``code``.

Pattern E note: gated by ``write_inventory`` scope.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_INVENTORY_ITEM_FIELDS = """
id
sku
tracked
requiresShipping
countryCodeOfOrigin
provinceCodeOfOrigin
harmonizedSystemCode
unitCost {
  amount
  currencyCode
}
measurement {
  id
  weight {
    value
    unit
  }
}
duplicateSkuCount
updatedAt
""".strip()


_UPDATE_MUTATION = f"""
mutation inventoryItemUpdate(
  $id: ID!,
  $input: InventoryItemInput!
) {{
  inventoryItemUpdate(id: $id, input: $input) {{
    inventoryItem {{
      {_INVENTORY_ITEM_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_VALID_WEIGHT_UNITS = {"GRAMS", "KILOGRAMS", "OUNCES", "POUNDS"}
_WEIGHT_UNIT_ALIASES = {
    "G": "GRAMS",
    "KG": "KILOGRAMS",
    "OZ": "OUNCES",
    "LB": "POUNDS",
    "LBS": "POUNDS",
}


class ShopifyInventoryItemAdapter(ShopifyBaseAdapter):
    name = "shopify_inventory_item"
    capabilities = {
        Capability.SHOPIFY_UPDATE_INVENTORY_ITEM,
    }
    required_scopes = frozenset({"read_inventory", "write_inventory"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPDATE_INVENTORY_ITEM:
            return self._update(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _update(self, params: dict[str, Any]) -> Any:
        item_id = (
            params.get("id")
            or params.get("inventory_item_id")
            or params.get("inventoryItemId")
        )
        if not isinstance(item_id, str) or not item_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the inventory item) "
                "is required",
            )

        body = self._build_input(params)
        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of: sku, cost, tracked, "
                "country_code_of_origin, province_code_of_origin, "
                "harmonized_system_code, country_harmonized_system_codes, "
                "weight, requires_shipping",
            )

        data = self._gql(_UPDATE_MUTATION, {
            "id": item_id.strip(), "input": body,
        })
        self._check_user_errors(data, "inventoryItemUpdate")
        payload = data.get("inventoryItemUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_INVENTORY_ITEM,
            data={
                "inventory_item": self._normalise(
                    payload.get("inventoryItem") or {},
                ),
            },
        )

    # ── Builders ──────────────────────────────────────────────────

    def _build_input(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        sku = params.get("sku")
        if isinstance(sku, str):
            out["sku"] = sku.strip()

        if "cost" in params and params["cost"] is not None:
            try:
                out["cost"] = float(params["cost"])
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'cost' must be numeric",
                ) from exc

        if "tracked" in params and params["tracked"] is not None:
            out["tracked"] = bool(params["tracked"])

        if "requires_shipping" in params:
            if params["requires_shipping"] is not None:
                out["requiresShipping"] = bool(params["requires_shipping"])
        elif "requiresShipping" in params:
            if params["requiresShipping"] is not None:
                out["requiresShipping"] = bool(params["requiresShipping"])

        country_code = (
            params.get("country_code_of_origin")
            or params.get("countryCodeOfOrigin")
        )
        if country_code is not None:
            if not isinstance(country_code, str):
                raise AdapterValidationError(
                    self.name,
                    "'country_code_of_origin' must be an ISO 3166-1 "
                    "alpha-2 code string",
                )
            out["countryCodeOfOrigin"] = country_code.strip().upper()

        province_code = (
            params.get("province_code_of_origin")
            or params.get("provinceCodeOfOrigin")
        )
        if province_code is not None:
            if not isinstance(province_code, str):
                raise AdapterValidationError(
                    self.name,
                    "'province_code_of_origin' must be a string",
                )
            out["provinceCodeOfOrigin"] = province_code.strip().upper()

        hs_code = (
            params.get("harmonized_system_code")
            or params.get("harmonizedSystemCode")
        )
        if hs_code is not None:
            if not isinstance(hs_code, str):
                raise AdapterValidationError(
                    self.name,
                    "'harmonized_system_code' must be a string",
                )
            out["harmonizedSystemCode"] = hs_code.strip()

        country_hs = (
            params.get("country_harmonized_system_codes")
            or params.get("countryHarmonizedSystemCodes")
        )
        if country_hs is not None:
            out["countryHarmonizedSystemCodes"] = self._build_country_hs(
                country_hs,
            )

        weight = params.get("weight")
        if weight is not None:
            out["measurement"] = {"weight": self._build_weight(weight)}

        return out

    def _build_country_hs(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            raise AdapterValidationError(
                self.name,
                "'country_harmonized_system_codes' must be a list",
            )
        out: list[dict[str, Any]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise AdapterValidationError(
                    self.name,
                    f"country_harmonized_system_codes[{i}] must be a dict",
                )
            cc = (
                item.get("country_code")
                or item.get("countryCode")
            )
            hs = (
                item.get("harmonized_system_code")
                or item.get("harmonizedSystemCode")
            )
            if not isinstance(cc, str) or not cc.strip():
                raise AdapterValidationError(
                    self.name,
                    f"country_harmonized_system_codes[{i}].country_code "
                    "is required (ISO 3166-1 alpha-2)",
                )
            if not isinstance(hs, str) or not hs.strip():
                raise AdapterValidationError(
                    self.name,
                    f"country_harmonized_system_codes[{i}]."
                    "harmonized_system_code is required",
                )
            out.append({
                "countryCode": cc.strip().upper(),
                "harmonizedSystemCode": hs.strip(),
            })
        return out

    def _build_weight(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'weight' must be a dict {value, unit}",
            )
        value = raw.get("value")
        unit = raw.get("unit")
        if value is None:
            raise AdapterValidationError(
                self.name, "'weight.value' is required",
            )
        try:
            value_float = float(value)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, "'weight.value' must be numeric",
            ) from exc
        if not isinstance(unit, str) or not unit.strip():
            raise AdapterValidationError(
                self.name,
                "'weight.unit' is required (kg / g / lb / oz)",
            )
        unit_norm = unit.strip().upper()
        unit_norm = _WEIGHT_UNIT_ALIASES.get(unit_norm, unit_norm)
        if unit_norm not in _VALID_WEIGHT_UNITS:
            raise AdapterValidationError(
                self.name,
                f"'weight.unit' must be one of "
                f"{sorted(_VALID_WEIGHT_UNITS)} (or aliases "
                f"{sorted(_WEIGHT_UNIT_ALIASES)})",
            )
        return {"value": value_float, "unit": unit_norm}

    # ── Normalisation ─────────────────────────────────────────────

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        unit_cost = node.get("unitCost") or {}
        try:
            cost_amount = float(unit_cost.get("amount", 0) or 0)
        except (TypeError, ValueError):
            cost_amount = 0.0
        measurement = node.get("measurement") or {}
        weight = (
            measurement.get("weight") or {}
            if isinstance(measurement, dict) else {}
        )
        try:
            weight_value = float(weight.get("value", 0) or 0)
        except (TypeError, ValueError):
            weight_value = 0.0
        return {
            "id": node.get("id", "") or "",
            "sku": node.get("sku", "") or "",
            "tracked": bool(node.get("tracked", False)),
            "requires_shipping": bool(
                node.get("requiresShipping", False),
            ),
            "country_code_of_origin": (
                node.get("countryCodeOfOrigin", "") or ""
            ),
            "province_code_of_origin": (
                node.get("provinceCodeOfOrigin", "") or ""
            ),
            "harmonized_system_code": (
                node.get("harmonizedSystemCode", "") or ""
            ),
            "unit_cost": {
                "amount": cost_amount,
                "currency_code": unit_cost.get("currencyCode", "") or "",
            },
            "measurement_id": (
                measurement.get("id", "")
                if isinstance(measurement, dict) else ""
            ) or "",
            "weight": {
                "value": weight_value,
                "unit": weight.get("unit", "") or "",
            },
            "duplicate_sku_count": int(
                node.get("duplicateSkuCount", 0) or 0,
            ),
            "updated_at": node.get("updatedAt", "") or "",
        }
