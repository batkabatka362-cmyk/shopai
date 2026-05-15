"""ShopifyCustomerAddressesAdapter — customer shipping addresses CRUD.

ShopAI's order-routing + fraud engines need to mutate customer
addresses, not just read them. Concrete drivers:

  * **Address fix-ups from cart-recovery flows.** When the recovery
    email gets a "wrong street" reply, the integration engine
    patches the address before re-attempting checkout — beats
    asking the buyer to re-type it.
  * **Onboard imported customers with addresses in one shot.**
    CRM imports (HubSpot, Klaviyo) carry addresses; the import
    engine creates the customer first, then loops this adapter
    to attach each address.
  * **Retire stale ship-tos.** When a buyer moves and their old
    address starts collecting failed delivery attempts, the
    fraud engine deletes it to stop the noise.

Capabilities:

  * ``SHOPIFY_CREATE_CUSTOMER_ADDRESS`` — customerAddressCreate.
  * ``SHOPIFY_UPDATE_CUSTOMER_ADDRESS`` — customerAddressUpdate.
  * ``SHOPIFY_DELETE_CUSTOMER_ADDRESS`` — customerAddressDelete.

Pattern A applied: customerId + addressId both live at GraphQL
field level, NOT inside the address dict. Delete takes BOTH a
customerId AND an addressId in the 2026 schema (older API
versions accepted just the address GID).

Pattern D handled: ``MailingAddressInput`` uses ``countryCode``
(CountryCode enum) and ``provinceCode`` (string) instead of the
free-form ``country`` / ``province`` fields older REST adapters
expose. Adapter rejects bare ``country`` to fail-fast at the
boundary.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ADDRESS_FIELDS = """
id
firstName
lastName
company
address1
address2
city
provinceCode
zip
countryCodeV2
phone
""".strip()


_CREATE_ADDRESS_MUTATION = f"""
mutation customerAddressCreate(
  $customerId: ID!,
  $address: MailingAddressInput!,
  $setAsDefault: Boolean
) {{
  customerAddressCreate(
    customerId: $customerId,
    address: $address,
    setAsDefault: $setAsDefault
  ) {{
    address {{
      {_ADDRESS_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_UPDATE_ADDRESS_MUTATION = f"""
mutation customerAddressUpdate(
  $customerId: ID!,
  $addressId: ID!,
  $address: MailingAddressInput!,
  $setAsDefault: Boolean
) {{
  customerAddressUpdate(
    customerId: $customerId,
    addressId: $addressId,
    address: $address,
    setAsDefault: $setAsDefault
  ) {{
    address {{
      {_ADDRESS_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DELETE_ADDRESS_MUTATION = """
mutation customerAddressDelete(
  $customerId: ID!,
  $addressId: ID!
) {
  customerAddressDelete(
    customerId: $customerId,
    addressId: $addressId
  ) {
    deletedAddressId
    userErrors {
      field
      message
    }
  }
}
""".strip()


# MailingAddressInput's accepted scalar field aliases.
_ADDRESS_ALIASES = {
    "address1": "address1",
    "address2": "address2",
    "city": "city",
    "company": "company",
    "country_code": "countryCode",
    "countryCode": "countryCode",
    "first_name": "firstName",
    "firstName": "firstName",
    "last_name": "lastName",
    "lastName": "lastName",
    "phone": "phone",
    "province_code": "provinceCode",
    "provinceCode": "provinceCode",
    "zip": "zip",
}


class ShopifyCustomerAddressesAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_addresses"
    capabilities = {
        Capability.SHOPIFY_CREATE_CUSTOMER_ADDRESS,
        Capability.SHOPIFY_UPDATE_CUSTOMER_ADDRESS,
        Capability.SHOPIFY_DELETE_CUSTOMER_ADDRESS,
    }
    required_scopes = frozenset({
        "read_customers", "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_CUSTOMER_ADDRESS:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_CUSTOMER_ADDRESS:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_CUSTOMER_ADDRESS:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        customer_id = self._extract_customer_id(params)
        address = params.get("address")
        if not isinstance(address, dict):
            raise AdapterValidationError(
                self.name, "'address' (dict) is required",
            )
        address_input = self._build_address_input(address)
        set_as_default = params.get("set_as_default")
        if set_as_default is None:
            set_as_default = params.get("setAsDefault")

        variables: dict[str, Any] = {
            "customerId": customer_id,
            "address": address_input,
        }
        if set_as_default is not None:
            variables["setAsDefault"] = bool(set_as_default)

        data = self._gql(_CREATE_ADDRESS_MUTATION, variables)
        self._check_user_errors(data, "customerAddressCreate")
        payload = data.get("customerAddressCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_CUSTOMER_ADDRESS,
            data={
                "address": self._normalise_address(
                    payload.get("address") or {}
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        customer_id = self._extract_customer_id(params)
        address_id = params.get("address_id") or params.get("addressId")
        if not isinstance(address_id, str) or not address_id.strip():
            raise AdapterValidationError(
                self.name,
                "'address_id' (Shopify GID for the address) is required",
            )
        address = params.get("address")
        if not isinstance(address, dict):
            raise AdapterValidationError(
                self.name, "'address' (dict) is required",
            )
        address_input = self._build_address_input(address)
        set_as_default = params.get("set_as_default")
        if set_as_default is None:
            set_as_default = params.get("setAsDefault")

        variables: dict[str, Any] = {
            "customerId": customer_id,
            "addressId": address_id.strip(),
            "address": address_input,
        }
        if set_as_default is not None:
            variables["setAsDefault"] = bool(set_as_default)

        data = self._gql(_UPDATE_ADDRESS_MUTATION, variables)
        self._check_user_errors(data, "customerAddressUpdate")
        payload = data.get("customerAddressUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_CUSTOMER_ADDRESS,
            data={
                "address": self._normalise_address(
                    payload.get("address") or {}
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        customer_id = self._extract_customer_id(params)
        address_id = (
            params.get("address_id")
            or params.get("addressId")
            or params.get("id")
        )
        if not isinstance(address_id, str) or not address_id.strip():
            raise AdapterValidationError(
                self.name,
                "'address_id' (Shopify GID for the address) is required",
            )

        data = self._gql(_DELETE_ADDRESS_MUTATION, {
            "customerId": customer_id,
            "addressId": address_id.strip(),
        })
        self._check_user_errors(data, "customerAddressDelete")
        payload = data.get("customerAddressDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_CUSTOMER_ADDRESS,
            data={
                "deleted_id": (
                    payload.get("deletedAddressId", "") or ""
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_customer_id(self, params: dict[str, Any]) -> str:
        customer_id = params.get("customer_id") or params.get("customerId")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AdapterValidationError(
                self.name,
                "'customer_id' (Shopify GID) is required — Pattern A: "
                "customerId at field level, NOT inside address",
            )
        return customer_id.strip()

    def _build_address_input(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        # Refuse free-form 'country' / 'province' so the caller learns
        # to use the *Code variants up front (Pattern D — the
        # MailingAddressInput in 2026 only accepts countryCode +
        # provinceCode).
        if "country" in raw:
            raise AdapterValidationError(
                self.name,
                "use 'country_code' (ISO 2-letter, e.g. 'US') instead "
                "of 'country' — MailingAddressInput requires the enum",
            )
        if "province" in raw:
            raise AdapterValidationError(
                self.name,
                "use 'province_code' (e.g. 'CA' for California) "
                "instead of 'province'",
            )

        out: dict[str, Any] = {}
        for snake, camel in _ADDRESS_ALIASES.items():
            if snake in raw:
                v = raw[snake]
                if v is None:
                    continue
                if not isinstance(v, str):
                    raise AdapterValidationError(
                        self.name,
                        f"'{snake}' must be a string",
                    )
                v = v.strip()
                if not v:
                    continue
                # countryCode is an enum — uppercase it to be safe.
                if camel == "countryCode":
                    v = v.upper()
                out[camel] = v

        if not out:
            raise AdapterValidationError(
                self.name,
                "'address' had no recognised fields — accepted: "
                f"{sorted(set(_ADDRESS_ALIASES.values()))}",
            )
        return out

    @staticmethod
    def _normalise_address(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        return {
            "id": node.get("id", "") or "",
            "first_name": node.get("firstName", "") or "",
            "last_name": node.get("lastName", "") or "",
            "company": node.get("company", "") or "",
            "address1": node.get("address1", "") or "",
            "address2": node.get("address2", "") or "",
            "city": node.get("city", "") or "",
            "province_code": node.get("provinceCode", "") or "",
            "zip": node.get("zip", "") or "",
            "country_code": node.get("countryCodeV2", "") or "",
            "phone": node.get("phone", "") or "",
        }
