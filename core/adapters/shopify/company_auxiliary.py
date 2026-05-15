"""ShopifyCompanyAuxiliaryAdapter — small B2B write surfaces.

Three small mutations that don't deserve their own adapter but
fill real gaps in the B2B write surface:

  * **Welcome-email send.** companyContactCreate doesn't fire
    Shopify's onboarding email on its own — engines that mint
    contacts via API need this follow-up call to push the
    welcome the way an admin-UI invite would.
  * **Address delete.** A B2B company can have multiple
    standalone addresses (separate from per-location addresses).
    Cleanup needs companyAddressDelete; companies.py /
    company_locations.py don't expose it.
  * **Tax settings update.** Per-location tax exemptions /
    registration ID — the data the B2B engine needs when a
    buyer's tax status changes (new resale certificate, new
    state registration). Without this, every change requires an
    operator clicking through admin.

Capabilities:

  * ``SHOPIFY_SEND_COMPANY_CONTACT_WELCOME`` — companyContactSendWelcomeEmail.
    Pattern A: companyContactId at field level; optional email
    overrides go in EmailInput.
  * ``SHOPIFY_DELETE_COMPANY_ADDRESS``       — companyAddressDelete.
    Pattern A: addressId at field level.
  * ``SHOPIFY_UPDATE_COMPANY_LOCATION_TAX_SETTINGS`` —
    companyLocationTaxSettingsUpdate. Pattern A: companyLocationId
    at field level; tax fields supplied as separate args.

UserError variant for all three is BusinessCustomerUserError
(has ``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_SEND_WELCOME_MUTATION = """
mutation companyContactSendWelcomeEmail(
  $companyContactId: ID!,
  $email: EmailInput
) {
  companyContactSendWelcomeEmail(
    companyContactId: $companyContactId, email: $email
  ) {
    companyContact {
      id
      customer {
        id
        email
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


_DELETE_ADDRESS_MUTATION = """
mutation companyAddressDelete($addressId: ID!) {
  companyAddressDelete(addressId: $addressId) {
    deletedAddressId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_UPDATE_TAX_SETTINGS_MUTATION = """
mutation companyLocationTaxSettingsUpdate(
  $companyLocationId: ID!,
  $taxRegistrationId: String,
  $taxExempt: Boolean,
  $exemptionsToAssign: [TaxExemption!],
  $exemptionsToRemove: [TaxExemption!]
) {
  companyLocationTaxSettingsUpdate(
    companyLocationId: $companyLocationId,
    taxRegistrationId: $taxRegistrationId,
    taxExempt: $taxExempt,
    exemptionsToAssign: $exemptionsToAssign,
    exemptionsToRemove: $exemptionsToRemove
  ) {
    companyLocation {
      id
      name
      taxSettings {
        taxRegistrationId
        taxExempt
        taxExemptions
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


class ShopifyCompanyAuxiliaryAdapter(ShopifyBaseAdapter):
    name = "shopify_company_auxiliary"
    capabilities = {
        Capability.SHOPIFY_SEND_COMPANY_CONTACT_WELCOME,
        Capability.SHOPIFY_DELETE_COMPANY_ADDRESS,
        Capability.SHOPIFY_UPDATE_COMPANY_LOCATION_TAX_SETTINGS,
    }
    required_scopes = frozenset({
        "read_customers", "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_SEND_COMPANY_CONTACT_WELCOME:
            return self._send_welcome(params)
        if capability == Capability.SHOPIFY_DELETE_COMPANY_ADDRESS:
            return self._delete_address(params)
        if capability == \
                Capability.SHOPIFY_UPDATE_COMPANY_LOCATION_TAX_SETTINGS:
            return self._update_tax_settings(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Welcome email ──────────────────────────────────────────────

    def _send_welcome(self, params: dict[str, Any]) -> Any:
        contact_id = (
            params.get("contact_id")
            or params.get("companyContactId")
            or params.get("id")
        )
        if not isinstance(contact_id, str) or not contact_id.strip():
            raise AdapterValidationError(
                self.name,
                "'contact_id' (Shopify GID for the company contact) "
                "is required",
            )

        email_input: dict[str, Any] | None = None
        email_raw = params.get("email")
        if isinstance(email_raw, dict):
            email_input = self._build_email_input(email_raw)

        variables: dict[str, Any] = {
            "companyContactId": contact_id.strip(),
            "email": email_input,
        }
        data = self._gql(_SEND_WELCOME_MUTATION, variables)
        self._check_user_errors(data, "companyContactSendWelcomeEmail")
        payload = data.get("companyContactSendWelcomeEmail") or {}
        contact = payload.get("companyContact") or {}
        customer = (
            contact.get("customer")
            if isinstance(contact, dict) else None
        ) or {}
        return self._success(
            Capability.SHOPIFY_SEND_COMPANY_CONTACT_WELCOME,
            data={
                "contact_id": (
                    contact.get("id", "")
                    if isinstance(contact, dict) else ""
                ) or "",
                "customer_email": (
                    customer.get("email", "")
                    if isinstance(customer, dict) else ""
                ) or "",
            },
        )

    # ── Delete address ─────────────────────────────────────────────

    def _delete_address(self, params: dict[str, Any]) -> Any:
        address_id = (
            params.get("address_id")
            or params.get("addressId")
            or params.get("id")
        )
        if not isinstance(address_id, str) or not address_id.strip():
            raise AdapterValidationError(
                self.name,
                "'address_id' (Shopify GID for the company address) "
                "is required",
            )
        data = self._gql(_DELETE_ADDRESS_MUTATION, {
            "addressId": address_id.strip(),
        })
        self._check_user_errors(data, "companyAddressDelete")
        payload = data.get("companyAddressDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_COMPANY_ADDRESS,
            data={
                "deleted_id": (
                    payload.get("deletedAddressId", "") or ""
                ),
            },
        )

    # ── Tax settings update ────────────────────────────────────────

    def _update_tax_settings(self, params: dict[str, Any]) -> Any:
        location_id = (
            params.get("company_location_id")
            or params.get("companyLocationId")
            or params.get("location_id")
            or params.get("id")
        )
        if not isinstance(location_id, str) or not location_id.strip():
            raise AdapterValidationError(
                self.name,
                "'company_location_id' (Shopify GID) is required",
            )

        variables: dict[str, Any] = {
            "companyLocationId": location_id.strip(),
            "taxRegistrationId": None,
            "taxExempt": None,
            "exemptionsToAssign": None,
            "exemptionsToRemove": None,
        }

        any_change = False

        tax_reg = (
            params.get("tax_registration_id")
            or params.get("taxRegistrationId")
        )
        if tax_reg is not None:
            if not isinstance(tax_reg, str):
                raise AdapterValidationError(
                    self.name,
                    "'tax_registration_id' must be a string",
                )
            variables["taxRegistrationId"] = tax_reg.strip()
            any_change = True

        if "tax_exempt" in params or "taxExempt" in params:
            raw = params.get("tax_exempt")
            if raw is None:
                raw = params.get("taxExempt")
            variables["taxExempt"] = bool(raw)
            any_change = True

        for friendly, camel in (
            ("exemptions_to_assign", "exemptionsToAssign"),
            ("exemptions_to_remove", "exemptionsToRemove"),
        ):
            raw = params.get(friendly) or params.get(camel)
            if raw is None:
                continue
            if not isinstance(raw, list):
                raise AdapterValidationError(
                    self.name,
                    f"'{friendly}' must be a list of TaxExemption "
                    "enum values (e.g. 'CA_RESELLER_EXEMPTION')",
                )
            cleaned: list[str] = []
            for i, e in enumerate(raw):
                if not isinstance(e, str) or not e.strip():
                    raise AdapterValidationError(
                        self.name,
                        f"{friendly}[{i}] must be a non-empty string",
                    )
                cleaned.append(e.strip().upper())
            variables[camel] = cleaned
            any_change = True

        if not any_change:
            raise AdapterValidationError(
                self.name,
                "no changes — pass at least one of "
                "'tax_registration_id', 'tax_exempt', "
                "'exemptions_to_assign', 'exemptions_to_remove'",
            )

        data = self._gql(_UPDATE_TAX_SETTINGS_MUTATION, variables)
        self._check_user_errors(data, "companyLocationTaxSettingsUpdate")
        payload = data.get("companyLocationTaxSettingsUpdate") or {}
        location = payload.get("companyLocation") or {}
        tax_settings = (
            location.get("taxSettings")
            if isinstance(location, dict) else None
        ) or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_COMPANY_LOCATION_TAX_SETTINGS,
            data={
                "company_location_id": (
                    location.get("id", "")
                    if isinstance(location, dict) else ""
                ) or "",
                "company_location_name": (
                    location.get("name", "")
                    if isinstance(location, dict) else ""
                ) or "",
                "tax_registration_id": (
                    tax_settings.get("taxRegistrationId", "")
                    if isinstance(tax_settings, dict) else ""
                ) or "",
                "tax_exempt": bool(
                    tax_settings.get("taxExempt", False)
                    if isinstance(tax_settings, dict) else False
                ),
                "tax_exemptions": list(
                    tax_settings.get("taxExemptions") or []
                    if isinstance(tax_settings, dict) else []
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _build_email_input(self, raw: dict[str, Any]) -> dict[str, Any]:
        # EmailInput accepts subject / to / from / body / bcc / customMessage.
        # All fields optional — if the caller passes nothing, omit the
        # whole dict so Shopify uses defaults.
        out: dict[str, Any] = {}
        for friendly, camel in (
            ("subject", "subject"),
            ("to", "to"),
            ("from_", "from"),
            ("from", "from"),
            ("body", "body"),
            ("custom_message", "customMessage"),
            ("customMessage", "customMessage"),
        ):
            if friendly in raw and raw[friendly] is not None:
                v = raw[friendly]
                if not isinstance(v, str):
                    raise AdapterValidationError(
                        self.name,
                        f"'email.{friendly}' must be a string",
                    )
                out[camel] = v

        bcc = raw.get("bcc")
        if bcc is not None:
            if isinstance(bcc, str):
                bcc = [bcc]
            if not isinstance(bcc, list) or not all(
                isinstance(b, str) for b in bcc
            ):
                raise AdapterValidationError(
                    self.name,
                    "'email.bcc' must be a list of strings",
                )
            out["bcc"] = [b.strip() for b in bcc if b.strip()]
        return out
