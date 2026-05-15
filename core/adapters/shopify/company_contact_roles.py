"""ShopifyCompanyContactRolesAdapter — B2B contact role management.

Companion to ``companies.py`` (B2B company CRUD). The contact-role
surface is how a B2B company designates who-does-what at each of
its locations: which buyer can place orders, which finance contact
gets net-30 invoice emails, which admin can manage payment
methods.

ShopAI's B2B engine reads + writes these to:

  * Onboard a new buyer onto an existing company by assigning the
    "Ordering" role at the relevant location.
  * Revoke a former employee's role when their corporate email
    bounces (compliance/security flow).
  * Audit "who has spend authority at this company location" for
    risk reporting.

Capabilities:

  * ``SHOPIFY_LIST_COMPANY_CONTACT_ROLES``    — list available roles
    on the shop (pre-defined: Ordering, Location_admin, etc.).
  * ``SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE``   — assign a role to a
    company contact at a specific location.
  * ``SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE``   — remove a previously-
    assigned role binding by GID.

Pattern A: ``companyLocationAssignRoles`` takes the location id at
field level + a list of {companyContactId, companyContactRoleId}
pairs. ``companyLocationRevokeRoles`` takes the location id +
list of role-binding GIDs.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ROLE_FIELDS = """
id
name
note
""".strip()


# Pattern B: there is no top-level Query.companyContactRoles
# connection — roles hang off a specific Company. The adapter
# takes a company_id and traverses company(id:).contactRoles.
_LIST_ROLES_QUERY = f"""
query companyContactRoles(
  $companyId: ID!,
  $first: Int!,
  $after: String
) {{
  company(id: $companyId) {{
    id
    name
    contactRoles(first: $first, after: $after) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      edges {{
        node {{
          {_ROLE_FIELDS}
        }}
      }}
    }}
  }}
}}
""".strip()


_ASSIGN_ROLE_MUTATION = """
mutation companyLocationAssignRoles(
  $companyLocationId: ID!,
  $rolesToAssign: [CompanyContactRoleAssign!]!
) {
  companyLocationAssignRoles(
    companyLocationId: $companyLocationId,
    rolesToAssign: $rolesToAssign
  ) {
    roleAssignments {
      id
      role {
        id
        name
      }
      companyContact {
        id
      }
      companyLocation {
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


_REVOKE_ROLE_MUTATION = """
mutation companyLocationRevokeRoles(
  $companyLocationId: ID!,
  $rolesToRevoke: [ID!]!
) {
  companyLocationRevokeRoles(
    companyLocationId: $companyLocationId,
    rolesToRevoke: $rolesToRevoke
  ) {
    revokedRoleAssignmentIds
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyCompanyContactRolesAdapter(ShopifyBaseAdapter):
    name = "shopify_company_contact_roles"
    capabilities = {
        Capability.SHOPIFY_LIST_COMPANY_CONTACT_ROLES,
        Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE,
        Capability.SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE,
    }
    required_scopes = frozenset({
        "read_customers", "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_COMPANY_CONTACT_ROLES:
            return self._list(params)
        if capability == Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE:
            return self._assign(params)
        if capability == Capability.SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE:
            return self._revoke(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List roles ─────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        company_id = params.get("company_id") or params.get("companyId")
        if not isinstance(company_id, str) or not company_id.strip():
            raise AdapterValidationError(
                self.name,
                "'company_id' (Shopify GID) is required — there's no "
                "top-level Query.companyContactRoles connection",
            )

        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                self.name, "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_ROLES_QUERY, {
            "companyId": company_id.strip(),
            "first": limit,
            "after": cursor,
        })
        company = data.get("company") or {}
        envelope = company.get("contactRoles") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        roles = [
            {
                "id": (edge.get("node") or {}).get("id", "") or "",
                "name": (edge.get("node") or {}).get("name", "") or "",
                "note": (edge.get("node") or {}).get("note", "") or "",
            }
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_COMPANY_CONTACT_ROLES,
            data={
                "company_id": company.get("id", "") or "",
                "company_name": company.get("name", "") or "",
                "roles": roles,
                "count": len(roles),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
                "company_found": bool(company),
            },
        )

    # ── Assign ────────────────────────────────────────────────────

    def _assign(self, params: dict[str, Any]) -> Any:
        location_id = params.get("company_location_id") or params.get(
            "companyLocationId"
        )
        if not isinstance(location_id, str) or not location_id.strip():
            raise AdapterValidationError(
                self.name,
                "'company_location_id' (Shopify GID) is required",
            )

        assignments_raw = params.get("assignments")
        if not isinstance(assignments_raw, list) or not assignments_raw:
            raise AdapterValidationError(
                self.name,
                "'assignments' must be a non-empty list of "
                "{contact_id, role_id} dicts",
            )
        assignments: list[dict[str, str]] = []
        for i, a in enumerate(assignments_raw):
            if not isinstance(a, dict):
                raise AdapterValidationError(
                    self.name, f"assignments[{i}] must be a dict",
                )
            contact_id = a.get("contact_id") or a.get("companyContactId")
            role_id = a.get("role_id") or a.get("companyContactRoleId")
            if not isinstance(contact_id, str) or not contact_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"assignments[{i}] missing 'contact_id'",
                )
            if not isinstance(role_id, str) or not role_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"assignments[{i}] missing 'role_id'",
                )
            assignments.append({
                "companyContactId": contact_id.strip(),
                "companyContactRoleId": role_id.strip(),
            })

        data = self._gql(_ASSIGN_ROLE_MUTATION, {
            "companyLocationId": location_id.strip(),
            "rolesToAssign": assignments,
        })
        self._check_user_errors(data, "companyLocationAssignRoles")
        payload = data.get("companyLocationAssignRoles") or {}
        out_assignments = []
        for assignment in (payload.get("roleAssignments") or []):
            if not isinstance(assignment, dict):
                continue
            role = assignment.get("role") or {}
            contact = assignment.get("companyContact") or {}
            location = assignment.get("companyLocation") or {}
            out_assignments.append({
                "id": assignment.get("id", "") or "",
                "role_id": (
                    role.get("id", "") if isinstance(role, dict) else ""
                ) or "",
                "role_name": (
                    role.get("name", "")
                    if isinstance(role, dict) else ""
                ) or "",
                "contact_id": (
                    contact.get("id", "")
                    if isinstance(contact, dict) else ""
                ) or "",
                "location_id": (
                    location.get("id", "")
                    if isinstance(location, dict) else ""
                ) or "",
            })
        return self._success(
            Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE,
            data={
                "assignments": out_assignments,
                "count": len(out_assignments),
            },
        )

    # ── Revoke ────────────────────────────────────────────────────

    def _revoke(self, params: dict[str, Any]) -> Any:
        location_id = params.get("company_location_id") or params.get(
            "companyLocationId"
        )
        if not isinstance(location_id, str) or not location_id.strip():
            raise AdapterValidationError(
                self.name,
                "'company_location_id' (Shopify GID) is required",
            )

        roles_raw = params.get("role_assignment_ids") or params.get(
            "rolesToRevoke"
        )
        if isinstance(roles_raw, str):
            roles_raw = [roles_raw]
        if not isinstance(roles_raw, list) or not roles_raw or not all(
            isinstance(r, str) for r in roles_raw
        ):
            raise AdapterValidationError(
                self.name,
                "'role_assignment_ids' must be a non-empty list of GIDs "
                "(or a single GID string)",
            )
        ids = [r.strip() for r in roles_raw if r.strip()]
        if not ids:
            raise AdapterValidationError(
                self.name, "'role_assignment_ids' contained only blanks",
            )

        data = self._gql(_REVOKE_ROLE_MUTATION, {
            "companyLocationId": location_id.strip(),
            "rolesToRevoke": ids,
        })
        self._check_user_errors(data, "companyLocationRevokeRoles")
        payload = data.get("companyLocationRevokeRoles") or {}
        revoked = list(payload.get("revokedRoleAssignmentIds") or [])
        return self._success(
            Capability.SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE,
            data={
                "revoked_assignment_ids": revoked,
                "count": len(revoked),
            },
        )
