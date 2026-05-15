"""ShopifyCompanyContactAssignmentAdapter — B2B contact bindings.

Companion to ``company_contacts.py`` (CRUD on contacts themselves)
and ``company_location_staff.py`` (Phase 25.2 — staff↔location
assignments). The remaining B2B contact-binding surface — linking
existing customer records to companies, promoting/demoting the
main contact, and unlinking contacts — sat across these mutations
nobody had wrapped:

  * ``companyAssignCustomerAsContact`` — link an existing CUSTOMER
    record as a company CONTACT. Used when an operator already has
    the customer in the storefront and wants to add them to a B2B
    company without re-entering identity data.
  * ``companyAssignMainContact`` — promote a contact to "main"
    (the primary buyer for the company; gets cc'd on draft orders,
    receives compliance emails).
  * ``companyRevokeMainContact`` — demote the main contact (the
    company has no main contact until another is promoted).
  * ``companyContactRemoveFromCompany`` — unlink a contact from
    its company without deleting the underlying customer record.

ShopAI's B2B engine writes these whenever:
  * A new buyer in an existing company emails support → link their
    storefront customer record as a company contact.
  * The main buyer rotates → promote new + revoke old.
  * A contact leaves the company → remove them but keep their
    storefront customer record intact.

Capabilities:

  * ``SHOPIFY_COMPANY_ASSIGN_CUSTOMER_AS_CONTACT`` —
    companyAssignCustomerAsContact. companyId + customerId.
  * ``SHOPIFY_COMPANY_ASSIGN_MAIN_CONTACT`` —
    companyAssignMainContact. companyId + companyContactId.
  * ``SHOPIFY_COMPANY_REVOKE_MAIN_CONTACT`` —
    companyRevokeMainContact. companyId only.
  * ``SHOPIFY_COMPANY_REMOVE_CONTACT`` —
    companyContactRemoveFromCompany. companyContactId only.

Pattern A — every id at field level (no input wrappers).
Pattern F — all four mutations use BusinessCustomerUserError
(HAS code).

Pattern E note: gated by ``write_companies`` /
``write_customers``; some flows additionally require Shopify Plus
(B2B-related mutations follow that pattern; see Phase 25.2 notes).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ASSIGN_CUSTOMER_MUTATION = """
mutation companyAssignCustomerAsContact(
  $companyId: ID!,
  $customerId: ID!
) {
  companyAssignCustomerAsContact(
    companyId: $companyId, customerId: $customerId
  ) {
    companyContact {
      id
      title
      isMainContact
      locale
      createdAt
      updatedAt
      customer {
        id
        email
        displayName
      }
      company {
        id
        name
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


_ASSIGN_MAIN_MUTATION = """
mutation companyAssignMainContact(
  $companyId: ID!,
  $companyContactId: ID!
) {
  companyAssignMainContact(
    companyId: $companyId,
    companyContactId: $companyContactId
  ) {
    company {
      id
      name
      mainContact {
        id
        title
        customer {
          id
          email
          displayName
        }
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


_REVOKE_MAIN_MUTATION = """
mutation companyRevokeMainContact($companyId: ID!) {
  companyRevokeMainContact(companyId: $companyId) {
    company {
      id
      name
      mainContact {
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


_REMOVE_CONTACT_MUTATION = """
mutation companyContactRemoveFromCompany(
  $companyContactId: ID!
) {
  companyContactRemoveFromCompany(
    companyContactId: $companyContactId
  ) {
    removedCompanyContactId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifyCompanyContactAssignmentAdapter(ShopifyBaseAdapter):
    name = "shopify_company_contact_assignment"
    capabilities = {
        Capability.SHOPIFY_COMPANY_ASSIGN_CUSTOMER_AS_CONTACT,
        Capability.SHOPIFY_COMPANY_ASSIGN_MAIN_CONTACT,
        Capability.SHOPIFY_COMPANY_REVOKE_MAIN_CONTACT,
        Capability.SHOPIFY_COMPANY_REMOVE_CONTACT,
    }
    required_scopes = frozenset({
        "read_customers", "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_COMPANY_ASSIGN_CUSTOMER_AS_CONTACT:
            return self._assign_customer(params)
        if capability == \
                Capability.SHOPIFY_COMPANY_ASSIGN_MAIN_CONTACT:
            return self._assign_main(params)
        if capability == \
                Capability.SHOPIFY_COMPANY_REVOKE_MAIN_CONTACT:
            return self._revoke_main(params)
        if capability == Capability.SHOPIFY_COMPANY_REMOVE_CONTACT:
            return self._remove_contact(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Assign customer as contact ─────────────────────────────────

    def _assign_customer(self, params: dict[str, Any]) -> Any:
        company_id = self._extract_id(
            params, ("company_id", "companyId"), "company_id",
            "Shopify Company GID",
        )
        customer_id = self._extract_id(
            params, ("customer_id", "customerId"), "customer_id",
            "Shopify Customer GID",
        )
        data = self._gql(_ASSIGN_CUSTOMER_MUTATION, {
            "companyId": company_id,
            "customerId": customer_id,
        })
        self._check_user_errors(
            data, "companyAssignCustomerAsContact",
        )
        payload = data.get(
            "companyAssignCustomerAsContact",
        ) or {}
        return self._success(
            Capability.SHOPIFY_COMPANY_ASSIGN_CUSTOMER_AS_CONTACT,
            data={
                "company_contact": self._normalise_contact(
                    payload.get("companyContact") or {},
                ),
            },
        )

    # ── Assign main contact ────────────────────────────────────────

    def _assign_main(self, params: dict[str, Any]) -> Any:
        company_id = self._extract_id(
            params, ("company_id", "companyId"), "company_id",
            "Shopify Company GID",
        )
        contact_id = self._extract_id(
            params,
            ("company_contact_id", "companyContactId", "contact_id"),
            "company_contact_id",
            "Shopify CompanyContact GID",
        )
        data = self._gql(_ASSIGN_MAIN_MUTATION, {
            "companyId": company_id,
            "companyContactId": contact_id,
        })
        self._check_user_errors(data, "companyAssignMainContact")
        payload = data.get("companyAssignMainContact") or {}
        company = payload.get("company") or {}
        main_contact = (
            company.get("mainContact") or {}
            if isinstance(company, dict) else {}
        )
        return self._success(
            Capability.SHOPIFY_COMPANY_ASSIGN_MAIN_CONTACT,
            data={
                "company_id": (
                    company.get("id", "")
                    if isinstance(company, dict) else ""
                ) or "",
                "company_name": (
                    company.get("name", "")
                    if isinstance(company, dict) else ""
                ) or "",
                "main_contact_id": (
                    main_contact.get("id", "")
                    if isinstance(main_contact, dict) else ""
                ) or "",
                "main_contact_title": (
                    main_contact.get("title", "")
                    if isinstance(main_contact, dict) else ""
                ) or "",
                "main_contact_customer_email": (
                    (main_contact.get("customer") or {}).get(
                        "email", "",
                    )
                    if isinstance(main_contact, dict) else ""
                ) or "",
            },
        )

    # ── Revoke main contact ────────────────────────────────────────

    def _revoke_main(self, params: dict[str, Any]) -> Any:
        company_id = self._extract_id(
            params, ("company_id", "companyId"), "company_id",
            "Shopify Company GID",
        )
        data = self._gql(_REVOKE_MAIN_MUTATION, {
            "companyId": company_id,
        })
        self._check_user_errors(data, "companyRevokeMainContact")
        payload = data.get("companyRevokeMainContact") or {}
        company = payload.get("company") or {}
        main_contact = (
            company.get("mainContact")
            if isinstance(company, dict) else None
        )
        return self._success(
            Capability.SHOPIFY_COMPANY_REVOKE_MAIN_CONTACT,
            data={
                "company_id": (
                    company.get("id", "")
                    if isinstance(company, dict) else ""
                ) or company_id,
                "company_name": (
                    company.get("name", "")
                    if isinstance(company, dict) else ""
                ) or "",
                "still_has_main_contact": bool(main_contact),
            },
        )

    # ── Remove contact ─────────────────────────────────────────────

    def _remove_contact(self, params: dict[str, Any]) -> Any:
        contact_id = self._extract_id(
            params,
            ("company_contact_id", "companyContactId", "contact_id"),
            "company_contact_id",
            "Shopify CompanyContact GID",
        )
        data = self._gql(_REMOVE_CONTACT_MUTATION, {
            "companyContactId": contact_id,
        })
        self._check_user_errors(
            data, "companyContactRemoveFromCompany",
        )
        payload = data.get(
            "companyContactRemoveFromCompany",
        ) or {}
        return self._success(
            Capability.SHOPIFY_COMPANY_REMOVE_CONTACT,
            data={
                "removed_contact_id": (
                    payload.get("removedCompanyContactId", "")
                    or contact_id
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(
        self,
        params: dict[str, Any],
        keys: tuple[str, ...],
        label: str,
        gid_kind: str,
    ) -> str:
        for k in keys:
            v = params.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        raise AdapterValidationError(
            self.name,
            f"'{label}' ({gid_kind}) is required",
        )

    @staticmethod
    def _normalise_contact(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        customer = node.get("customer") or {}
        company = node.get("company") or {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "is_main_contact": bool(node.get("isMainContact", False)),
            "locale": node.get("locale", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "customer_id": (
                customer.get("id", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "customer_email": (
                customer.get("email", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "customer_display_name": (
                customer.get("displayName", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "company_id": (
                company.get("id", "")
                if isinstance(company, dict) else ""
            ) or "",
            "company_name": (
                company.get("name", "")
                if isinstance(company, dict) else ""
            ) or "",
        }
