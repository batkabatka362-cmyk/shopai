"""ShopifyCompanyContactsAdapter — B2B company contact CRUD.

Companion to ``companies.py`` (B2B company root),
``company_locations.py`` (per-location addresses), and
``company_contact_roles.py`` (role-binding management). The
existing roles adapter handles the "what role is this contact
playing" question; this adapter handles the contacts themselves
— the people behind each B2B account.

ShopAI's B2B engine uses these to:

  * **Onboard a new buyer.** When a salesperson closes a deal,
    the integration engine creates the company first (via
    ``companies.py``) then loops this adapter to add each
    authorised buyer. Roles are assigned in a follow-up call.
  * **Patch a contact's title or locale.** When AP changes the
    "preferred billing language" for an EU subsidiary, update
    the contact's locale; when a buyer's job title changes,
    patch ``title`` rather than re-creating the record.
  * **Offboard.** Two flavours:
    - ``DELETE`` removes the contact entirely (the underlying
      Customer record stays, but the company association and
      contact metadata are gone).
    - ``REMOVE`` only severs the company association — the
      contact survives so they can be re-attached to a different
      company without re-onboarding.

Capabilities:

  * ``SHOPIFY_CREATE_COMPANY_CONTACT`` — companyContactCreate.
    Pattern A: companyId at field level.
  * ``SHOPIFY_UPDATE_COMPANY_CONTACT`` — companyContactUpdate.
    Pattern A: companyContactId at field level.
  * ``SHOPIFY_DELETE_COMPANY_CONTACT`` — companyContactDelete.
    Removes the contact entirely.
  * ``SHOPIFY_REMOVE_COMPANY_CONTACT`` — companyContactRemoveFromCompany.
    Detaches the contact from the company without deleting it.

Pattern D handled: ``CompanyContact`` does NOT carry firstName /
lastName / email / phone directly — they live on the nested
``customer: Customer``. Friendly-shape input still uses the
flat keys (the GraphQL input applies them to the customer); the
response normaliser pulls them back through ``customer.*``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CONTACT_FIELDS = """
id
title
locale
isMainContact
createdAt
updatedAt
lifetimeDuration
company {
  id
  name
}
customer {
  id
  email
  firstName
  lastName
  phone
}
""".strip()


_CREATE_CONTACT_MUTATION = f"""
mutation companyContactCreate(
  $companyId: ID!,
  $input: CompanyContactInput!
) {{
  companyContactCreate(companyId: $companyId, input: $input) {{
    companyContact {{
      {_CONTACT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_CONTACT_MUTATION = f"""
mutation companyContactUpdate(
  $companyContactId: ID!,
  $input: CompanyContactInput!
) {{
  companyContactUpdate(
    companyContactId: $companyContactId, input: $input
  ) {{
    companyContact {{
      {_CONTACT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_CONTACT_MUTATION = """
mutation companyContactDelete($companyContactId: ID!) {
  companyContactDelete(companyContactId: $companyContactId) {
    deletedCompanyContactId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_REMOVE_CONTACT_MUTATION = """
mutation companyContactRemoveFromCompany($companyContactId: ID!) {
  companyContactRemoveFromCompany(companyContactId: $companyContactId) {
    removedCompanyContactId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_INPUT_ALIASES = {
    "first_name": "firstName",
    "firstName": "firstName",
    "last_name": "lastName",
    "lastName": "lastName",
    "email": "email",
    "phone": "phone",
    "title": "title",
    "locale": "locale",
}


class ShopifyCompanyContactsAdapter(ShopifyBaseAdapter):
    name = "shopify_company_contacts"
    capabilities = {
        Capability.SHOPIFY_CREATE_COMPANY_CONTACT,
        Capability.SHOPIFY_UPDATE_COMPANY_CONTACT,
        Capability.SHOPIFY_DELETE_COMPANY_CONTACT,
        Capability.SHOPIFY_REMOVE_COMPANY_CONTACT,
    }
    required_scopes = frozenset({
        "read_customers", "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_COMPANY_CONTACT:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_COMPANY_CONTACT:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_COMPANY_CONTACT:
            return self._delete(params)
        if capability == Capability.SHOPIFY_REMOVE_COMPANY_CONTACT:
            return self._remove(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        company_id = params.get("company_id") or params.get("companyId")
        if not isinstance(company_id, str) or not company_id.strip():
            raise AdapterValidationError(
                self.name,
                "'company_id' (Shopify GID) is required — Pattern A: "
                "companyId at field level, NOT inside input",
            )
        contact_input = self._build_input(params, require_email=True)
        data = self._gql(_CREATE_CONTACT_MUTATION, {
            "companyId": company_id.strip(),
            "input": contact_input,
        })
        self._check_user_errors(data, "companyContactCreate")
        payload = data.get("companyContactCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_COMPANY_CONTACT,
            data={
                "contact": self._normalise_contact(
                    payload.get("companyContact") or {}
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        contact_id = self._extract_contact_id(params)
        contact_input = self._build_input(params, require_email=False)
        if not contact_input:
            raise AdapterValidationError(
                self.name,
                "no patchable fields supplied — pass at least one of "
                f"{sorted(set(_INPUT_ALIASES.values()))}",
            )
        data = self._gql(_UPDATE_CONTACT_MUTATION, {
            "companyContactId": contact_id,
            "input": contact_input,
        })
        self._check_user_errors(data, "companyContactUpdate")
        payload = data.get("companyContactUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_COMPANY_CONTACT,
            data={
                "contact": self._normalise_contact(
                    payload.get("companyContact") or {}
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        contact_id = self._extract_contact_id(params)
        data = self._gql(_DELETE_CONTACT_MUTATION, {
            "companyContactId": contact_id,
        })
        self._check_user_errors(data, "companyContactDelete")
        payload = data.get("companyContactDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_COMPANY_CONTACT,
            data={
                "deleted_id": (
                    payload.get("deletedCompanyContactId", "") or ""
                ),
            },
        )

    # ── Remove from company ────────────────────────────────────────

    def _remove(self, params: dict[str, Any]) -> Any:
        contact_id = self._extract_contact_id(params)
        data = self._gql(_REMOVE_CONTACT_MUTATION, {
            "companyContactId": contact_id,
        })
        self._check_user_errors(data, "companyContactRemoveFromCompany")
        payload = data.get("companyContactRemoveFromCompany") or {}
        return self._success(
            Capability.SHOPIFY_REMOVE_COMPANY_CONTACT,
            data={
                "removed_id": (
                    payload.get("removedCompanyContactId", "") or ""
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_contact_id(self, params: dict[str, Any]) -> str:
        contact_id = (
            params.get("id")
            or params.get("contact_id")
            or params.get("companyContactId")
        )
        if not isinstance(contact_id, str) or not contact_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the company contact) is required",
            )
        return contact_id.strip()

    def _build_input(
        self, params: dict[str, Any], *, require_email: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for snake, camel in _INPUT_ALIASES.items():
            if snake in params:
                v = params[snake]
                if v is None:
                    continue
                if not isinstance(v, str):
                    raise AdapterValidationError(
                        self.name, f"'{snake}' must be a string",
                    )
                v = v.strip()
                if v:
                    out[camel] = v
        if require_email and "email" not in out:
            raise AdapterValidationError(
                self.name, "'email' is required for create",
            )
        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_contact(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        company = node.get("company") or {}
        customer = node.get("customer") or {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "locale": node.get("locale", "") or "",
            "is_main_contact": bool(node.get("isMainContact", False)),
            "lifetime_duration": node.get("lifetimeDuration", "") or "",
            "company_id": (
                company.get("id", "")
                if isinstance(company, dict) else ""
            ) or "",
            "company_name": (
                company.get("name", "")
                if isinstance(company, dict) else ""
            ) or "",
            "customer_id": (
                customer.get("id", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "email": (
                customer.get("email", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "first_name": (
                customer.get("firstName", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "last_name": (
                customer.get("lastName", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "phone": (
                customer.get("phone", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
