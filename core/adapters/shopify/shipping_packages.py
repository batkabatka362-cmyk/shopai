"""ShopifyShippingPackagesAdapter — custom shipping-package CRUD.

A "shipping package" in Shopify is the merchant's catalog of box /
envelope / soft-pack templates that carrier-rate calculations use to
estimate shipping cost. Without writes, an operator can't:

  * Add a new package size when sourcing moves to a vendor with
    different cartons.
  * Update the default-flag (the one box used for first-pass rate
    quotes) as the catalog mix shifts.
  * Retire packages that are no longer stocked.

ShopAI's fulfillment engine writes these whenever the
sourcing pipeline emits a "we now stock 12x12x4" event.

Capabilities:

  * ``SHOPIFY_UPDATE_SHIPPING_PACKAGE``       — shippingPackageUpdate.
    Pattern A: id at field level + ``CustomShippingPackageInput``
    body. Note the type is ``Custom`` shipping package — Shopify
    doesn't expose mutations for the system / carrier-defined
    presets, only the merchant's custom additions.
  * ``SHOPIFY_DELETE_SHIPPING_PACKAGE``       — shippingPackageDelete.
    Returns deletedId.
  * ``SHOPIFY_MAKE_DEFAULT_SHIPPING_PACKAGE`` — shippingPackageMakeDefault.
    Promotes the named package to the shop's default; the previous
    default is auto-demoted by Shopify.

Friendly call shape::

    {"id":      "gid://shopify/DeliveryCustomShippingPackage/123",
     "name":    "12x12x4 reinforced",
     "type":    "box",         # box / flat_rate / envelope / soft_pack
     "default": False,
     "weight":  {"value": 0.3, "unit": "kg"},
     "dimensions": {
       "length": 12, "width": 12, "height": 4, "unit": "in",
     }}

Pattern F: all three mutations use the bare ``UserError`` type
(no ``code`` — confirmed live; Shopify rejects ``code`` selection).
Drop ``code``.

Pattern E note: gated by ``write_shipping`` / ``write_shipping_rates``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_UPDATE_MUTATION = """
mutation shippingPackageUpdate(
  $id: ID!,
  $shippingPackage: CustomShippingPackageInput!
) {
  shippingPackageUpdate(
    id: $id,
    shippingPackage: $shippingPackage
  ) {
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DELETE_MUTATION = """
mutation shippingPackageDelete($id: ID!) {
  shippingPackageDelete(id: $id) {
    deletedId
    userErrors {
      field
      message
    }
  }
}
""".strip()


_MAKE_DEFAULT_MUTATION = """
mutation shippingPackageMakeDefault($id: ID!) {
  shippingPackageMakeDefault(id: $id) {
    userErrors {
      field
      message
    }
  }
}
""".strip()


_VALID_PACKAGE_TYPES = {"BOX", "FLAT_RATE", "ENVELOPE", "SOFT_PACK"}
_VALID_WEIGHT_UNITS = {"GRAMS", "KILOGRAMS", "OUNCES", "POUNDS"}
_WEIGHT_UNIT_ALIASES = {
    "G": "GRAMS",
    "KG": "KILOGRAMS",
    "OZ": "OUNCES",
    "LB": "POUNDS",
    "LBS": "POUNDS",
}
_VALID_LENGTH_UNITS = {
    "MILLIMETERS", "CENTIMETERS", "METERS",
    "INCHES", "FEET", "YARDS",
}
_LENGTH_UNIT_ALIASES = {
    "MM": "MILLIMETERS",
    "CM": "CENTIMETERS",
    "M": "METERS",
    "IN": "INCHES",
    "INCH": "INCHES",
    "FT": "FEET",
    "FOOT": "FEET",
    "YD": "YARDS",
    "YARD": "YARDS",
}


class ShopifyShippingPackagesAdapter(ShopifyBaseAdapter):
    name = "shopify_shipping_packages"
    capabilities = {
        Capability.SHOPIFY_UPDATE_SHIPPING_PACKAGE,
        Capability.SHOPIFY_DELETE_SHIPPING_PACKAGE,
        Capability.SHOPIFY_MAKE_DEFAULT_SHIPPING_PACKAGE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPDATE_SHIPPING_PACKAGE:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_SHIPPING_PACKAGE:
            return self._delete(params)
        if capability == \
                Capability.SHOPIFY_MAKE_DEFAULT_SHIPPING_PACKAGE:
            return self._make_default(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        package_id = self._extract_id(params)
        body = self._build_input(params)
        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of: name, type, default, "
                "weight, dimensions",
            )
        data = self._gql(_UPDATE_MUTATION, {
            "id": package_id, "shippingPackage": body,
        })
        self._check_user_errors(data, "shippingPackageUpdate")
        return self._success(
            Capability.SHOPIFY_UPDATE_SHIPPING_PACKAGE,
            data={"id": package_id},
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        package_id = self._extract_id(params)
        data = self._gql(_DELETE_MUTATION, {"id": package_id})
        self._check_user_errors(data, "shippingPackageDelete")
        payload = data.get("shippingPackageDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_SHIPPING_PACKAGE,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Make default ───────────────────────────────────────────────

    def _make_default(self, params: dict[str, Any]) -> Any:
        package_id = self._extract_id(params)
        data = self._gql(_MAKE_DEFAULT_MUTATION, {"id": package_id})
        self._check_user_errors(data, "shippingPackageMakeDefault")
        return self._success(
            Capability.SHOPIFY_MAKE_DEFAULT_SHIPPING_PACKAGE,
            data={"id": package_id, "default": True},
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        package_id = (
            params.get("id")
            or params.get("package_id")
            or params.get("shipping_package_id")
            or params.get("shippingPackageId")
        )
        if not isinstance(package_id, str) or not package_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the custom shipping package) "
                "is required",
            )
        return package_id.strip()

    def _build_input(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        name = params.get("name")
        if isinstance(name, str) and name.strip():
            out["name"] = name.strip()

        type_raw = params.get("type") or params.get("package_type")
        if type_raw is not None:
            if not isinstance(type_raw, str):
                raise AdapterValidationError(
                    self.name, "'type' must be a string",
                )
            up = type_raw.strip().upper()
            if up not in _VALID_PACKAGE_TYPES:
                raise AdapterValidationError(
                    self.name,
                    f"'type' must be one of "
                    f"{sorted(_VALID_PACKAGE_TYPES)}",
                )
            out["type"] = up

        if "default" in params and params["default"] is not None:
            out["default"] = bool(params["default"])

        weight = params.get("weight")
        if weight is not None:
            out["weight"] = self._build_weight(weight)

        dimensions = params.get("dimensions")
        if dimensions is not None:
            out["dimensions"] = self._build_dimensions(dimensions)

        return out

    def _build_weight(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'weight' must be a dict {value, unit}",
            )
        value = raw.get("value")
        unit = raw.get("unit")
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
                f"{sorted(_VALID_WEIGHT_UNITS)}",
            )
        return {"value": value_float, "unit": unit_norm}

    def _build_dimensions(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'dimensions' must be a dict "
                "{length, width, height, unit}",
            )
        out: dict[str, Any] = {}
        for key in ("length", "width", "height"):
            v = raw.get(key)
            if v is None:
                raise AdapterValidationError(
                    self.name,
                    f"'dimensions.{key}' is required",
                )
            try:
                out[key] = float(v)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"'dimensions.{key}' must be numeric",
                ) from exc
        unit = raw.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            raise AdapterValidationError(
                self.name,
                "'dimensions.unit' is required (in / cm / mm / m / "
                "ft / yd)",
            )
        unit_norm = unit.strip().upper()
        unit_norm = _LENGTH_UNIT_ALIASES.get(unit_norm, unit_norm)
        if unit_norm not in _VALID_LENGTH_UNITS:
            raise AdapterValidationError(
                self.name,
                f"'dimensions.unit' must be one of "
                f"{sorted(_VALID_LENGTH_UNITS)}",
            )
        out["unit"] = unit_norm
        return out
