"""ShopifyCompanyLocationStaffAdapter — B2B staff binding + invite.

Companions to ``companies.py`` (LIST/GET company),
``company_locations.py`` (LIST/GET/CREATE/UPDATE/DELETE locations),
``company_contacts.py`` (LIST/GET/CREATE/UPDATE/DELETE contacts),
``company_contact_roles.py`` (role assignment), and
``company_auxiliary.py`` (the rest of the surface). The remaining
B2B operations sat across two distinct concerns that didn't fit
any of the above:

  * **Staff member ↔ company location bindings.** A B2B account-manager
    staff record can be assigned to one or more company locations so
    they're auto-cc'd on draft orders, see those locations in their
    admin filters, and own the customer success relationship.
    ShopAI's B2B engine writes these bindings whenever an operator
    onboards a new account manager or rotates territory ownership.
  * **Welcome emails for new contacts.** When a B2B company contact
    is freshly created (or migrated from another platform), the
    onboarding engine sends Shopify's "your B2B account is ready"
    email so the buyer can claim their login. Distinct mutation
    from the regular ``customerSendAccountInviteEmail`` because B2B
    contacts have a different account-claim flow tied to their
    company record.

Capabilities:

  * ``SHOPIFY_ASSIGN_COMPANY_LOCATION_STAFF`` —
    companyLocationAssignStaffMembers. Pattern A: companyLocationId
    at field level + list of staffMemberIds.
  * ``SHOPIFY_REMOVE_COMPANY_LOCATION_STAFF`` —
    companyLocationRemoveStaffMembers. Takes a list of *assignment*
    GIDs (returned by the assign call), NOT staff member or
    location ids.
  * ``SHOPIFY_SEND_COMPANY_CONTACT_WELCOME_EMAIL`` —
    companyContactSendWelcomeEmail. companyContactId at field level,
    optional ``email`` EmailInput override.

UserError type for all three is ``BusinessCustomerUserError``
(HAS ``code``) — confirmed via introspection. Pattern F:
keep ``code`` in selection.

Pattern E note: gated by ``write_companies`` / ``write_customers``;
some sub-operations also require Shopify Plus
(companyContactSendWelcomeEmail surfaces the Plus requirement live as
``"The API client must be installed on a Shopify Plus store."``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ASSIGN_MUTATION = """
mutation companyLocationAssignStaffMembers(
  $companyLocationId: ID!,
  $staffMemberIds: [ID!]!
) {
  companyLocationAssignStaffMembers(
    companyLocationId: $companyLocationId,
    staffMemberIds: $staffMemberIds
  ) {
    companyLocationStaffMemberAssignments {
      id
      companyLocation {
        id
        name
      }
      staffMember {
        id
        name
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


_REMOVE_MUTATION = """
mutation companyLocationRemoveStaffMembers(
  $companyLocationStaffMemberAssignmentIds: [ID!]!
) {
  companyLocationRemoveStaffMembers(
    companyLocationStaffMemberAssignmentIds:
      $companyLocationStaffMemberAssignmentIds
  ) {
    deletedCompanyLocationStaffMemberAssignmentIds
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_WELCOME_EMAIL_MUTATION = """
mutation companyContactSendWelcomeEmail(
  $companyContactId: ID!,
  $email: EmailInput
) {
  companyContactSendWelcomeEmail(
    companyContactId: $companyContactId,
    email: $email
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


class ShopifyCompanyLocationStaffAdapter(ShopifyBaseAdapter):
    name = "shopify_company_location_staff"
    capabilities = {
        Capability.SHOPIFY_ASSIGN_COMPANY_LOCATION_STAFF,
        Capability.SHOPIFY_REMOVE_COMPANY_LOCATION_STAFF,
        Capability.SHOPIFY_SEND_COMPANY_CONTACT_WELCOME_EMAIL,
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
                Capability.SHOPIFY_ASSIGN_COMPANY_LOCATION_STAFF:
            return self._assign(params)
        if capability == \
                Capability.SHOPIFY_REMOVE_COMPANY_LOCATION_STAFF:
            return self._remove(params)
        if capability == \
                Capability.SHOPIFY_SEND_COMPANY_CONTACT_WELCOME_EMAIL:
            return self._send_welcome(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Assign ─────────────────────────────────────────────────────

    def _assign(self, params: dict[str, Any]) -> Any:
        location_id = (
            params.get("company_location_id")
            or params.get("companyLocationId")
            or params.get("location_id")
        )
        if not isinstance(location_id, str) or not location_id.strip():
            raise AdapterValidationError(
                self.name,
                "'company_location_id' (Shopify GID for the "
                "company location) is required",
            )

        staff_ids = self._clean_id_list(
            params.get("staff_member_ids")
            or params.get("staffMemberIds")
            or params.get("staff_ids"),
            "staff_member_ids",
        )

        data = self._gql(_ASSIGN_MUTATION, {
            "companyLocationId": location_id.strip(),
            "staffMemberIds": staff_ids,
        })
        self._check_user_errors(
            data, "companyLocationAssignStaffMembers",
        )
        payload = data.get("companyLocationAssignStaffMembers") or {}
        assignments = payload.get(
            "companyLocationStaffMemberAssignments",
        ) or []
        return self._success(
            Capability.SHOPIFY_ASSIGN_COMPANY_LOCATION_STAFF,
            data={
                "assignments": [
                    self._normalise_assignment(a) for a in assignments
                    if isinstance(a, dict)
                ],
                "count": len(assignments),
            },
        )

    # ── Remove ─────────────────────────────────────────────────────

    def _remove(self, params: dict[str, Any]) -> Any:
        assignment_ids = self._clean_id_list(
            params.get("assignment_ids")
            or params.get("company_location_staff_member_assignment_ids")
            or params.get("companyLocationStaffMemberAssignmentIds"),
            "assignment_ids",
        )
        data = self._gql(_REMOVE_MUTATION, {
            "companyLocationStaffMemberAssignmentIds": assignment_ids,
        })
        self._check_user_errors(
            data, "companyLocationRemoveStaffMembers",
        )
        payload = data.get("companyLocationRemoveStaffMembers") or {}
        deleted = payload.get(
            "deletedCompanyLocationStaffMemberAssignmentIds",
        ) or []
        return self._success(
            Capability.SHOPIFY_REMOVE_COMPANY_LOCATION_STAFF,
            data={
                "deleted_assignment_ids": [
                    d for d in deleted if isinstance(d, str)
                ],
                "count": len([d for d in deleted if isinstance(d, str)]),
            },
        )

    # ── Welcome email ──────────────────────────────────────────────

    def _send_welcome(self, params: dict[str, Any]) -> Any:
        contact_id = (
            params.get("company_contact_id")
            or params.get("companyContactId")
            or params.get("contact_id")
        )
        if not isinstance(contact_id, str) or not contact_id.strip():
            raise AdapterValidationError(
                self.name,
                "'company_contact_id' (Shopify GID for the company "
                "contact) is required",
            )
        email_override = self._build_email_override(params)
        variables: dict[str, Any] = {
            "companyContactId": contact_id.strip(),
        }
        variables["email"] = email_override

        data = self._gql(_WELCOME_EMAIL_MUTATION, variables)
        self._check_user_errors(
            data, "companyContactSendWelcomeEmail",
        )
        payload = data.get("companyContactSendWelcomeEmail") or {}
        contact = payload.get("companyContact") or {}
        return self._success(
            Capability.SHOPIFY_SEND_COMPANY_CONTACT_WELCOME_EMAIL,
            data={
                "company_contact": self._normalise_contact(contact),
                "email_override_address": (
                    email_override.get("to", "")
                    if email_override else ""
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _clean_id_list(self, raw: Any, label: str) -> list[str]:
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                f"'{label}' must be a non-empty list of GID strings",
            )
        cleaned = []
        for i, v in enumerate(raw):
            if not isinstance(v, str) or not v.strip():
                raise AdapterValidationError(
                    self.name,
                    f"'{label}[{i}]' must be a non-empty GID string",
                )
            cleaned.append(v.strip())
        return cleaned

    def _build_email_override(
        self, params: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw = params.get("email")
        if raw is None or raw == "":
            return None
        if isinstance(raw, str):
            address = raw.strip()
            if not address:
                return None
            return {"to": address}
        if isinstance(raw, dict):
            address = (
                raw.get("to")
                or raw.get("emailAddress")
                or raw.get("email_address")
                or raw.get("email")
            )
            if not isinstance(address, str) or not address.strip():
                raise AdapterValidationError(
                    self.name,
                    "'email' dict must include 'to' (the override "
                    "address)",
                )
            out: dict[str, Any] = {"to": address.strip()}
            for snake, camel in (
                ("subject", "subject"),
                ("from", "from"),
                ("from_address", "from"),
                ("body", "body"),
                ("custom_message", "customMessage"),
            ):
                v = raw.get(snake)
                if isinstance(v, str) and v.strip():
                    out[camel] = v.strip()
            bcc = raw.get("bcc")
            if isinstance(bcc, list):
                cleaned = [
                    b.strip() for b in bcc
                    if isinstance(b, str) and b.strip()
                ]
                if cleaned:
                    out["bcc"] = cleaned
            return out
        raise AdapterValidationError(
            self.name,
            "'email' must be a string (address) or {to, ...} dict",
        )

    @staticmethod
    def _normalise_assignment(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        location = node.get("companyLocation") or {}
        staff = node.get("staffMember") or {}
        return {
            "assignment_id": node.get("id", "") or "",
            "company_location_id": (
                location.get("id", "")
                if isinstance(location, dict) else ""
            ) or "",
            "company_location_name": (
                location.get("name", "")
                if isinstance(location, dict) else ""
            ) or "",
            "staff_member_id": (
                staff.get("id", "")
                if isinstance(staff, dict) else ""
            ) or "",
            "staff_member_name": (
                staff.get("name", "")
                if isinstance(staff, dict) else ""
            ) or "",
            "staff_member_email": (
                staff.get("email", "")
                if isinstance(staff, dict) else ""
            ) or "",
        }

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
