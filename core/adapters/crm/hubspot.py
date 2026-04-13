"""HubSpotAdapter — HubSpot CRM.

HubSpot is a leading CRM used by 200,000+ companies. This adapter
wraps the CRM v3 REST API for:

  * **Search contacts**  — filter by email / property
  * **Upsert contact**   — create-or-update by email
  * **List deals**       — recent / open deals
  * **Create deal**      — new opportunity (optionally linked to contact)

Authentication: private app access token (Bearer).
Free tier: Yes (CRM free forever).
Reference: https://developers.hubspot.com/docs/api/crm/contacts
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ..errors import AdapterValidationError
from ._base import CrmBaseAdapter


class HubSpotAdapter(CrmBaseAdapter):
    name = "hubspot"
    base_url = "https://api.hubapi.com"
    config_alias = "hubspot"

    priority = 90
    cost_per_call = 0.0

    # ── Search contacts ────────────────────────────────────────

    def _do_search_contacts(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        query = params.get("query") or params.get("email")
        if not query:
            raise AdapterValidationError(
                self.name, "'query' or 'email' is required",
            )

        prop = params.get("property", "email")
        operator = params.get("operator", "EQ")
        limit = int(params.get("limit", 20))

        url = f"{self.base_url}/crm/v3/objects/contacts/search"
        body = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": prop,
                    "operator": operator,
                    "value": query,
                }],
            }],
            "properties": params.get("properties", [
                "email", "firstname", "lastname", "phone", "company",
                "lifecyclestage", "createdate",
            ]),
            "limit": limit,
        }

        raw = self._http_request("POST", url, body=body)

        contacts = []
        for c in raw.get("results", []):
            props = c.get("properties", {}) or {}
            contacts.append({
                "id": c.get("id", ""),
                "email": props.get("email", ""),
                "first_name": props.get("firstname", ""),
                "last_name": props.get("lastname", ""),
                "phone": props.get("phone", ""),
                "company": props.get("company", ""),
                "lifecycle_stage": props.get("lifecyclestage", ""),
                "created_at": props.get("createdate", ""),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "contacts": contacts,
                "count": len(contacts),
                "total": raw.get("total", len(contacts)),
            },
            raw=raw,
        )

    # ── Upsert contact ─────────────────────────────────────────

    def _do_upsert_contact(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        email = params.get("email")
        if not email:
            raise AdapterValidationError(
                self.name, "'email' is required",
            )

        properties: dict[str, Any] = {"email": email}
        # Accept both snake_case (our convention) and HubSpot native keys.
        mapping = {
            "first_name": "firstname",
            "last_name": "lastname",
            "phone": "phone",
            "company": "company",
            "lifecycle_stage": "lifecyclestage",
        }
        for src, dst in mapping.items():
            if src in params:
                properties[dst] = params[src]
        # Extra raw properties pass through unchanged.
        for k, v in (params.get("properties") or {}).items():
            properties[k] = v

        # HubSpot idempotent upsert by email uses PATCH with the
        # idProperty query param.
        url = (
            f"{self.base_url}/crm/v3/objects/contacts/{email}"
            f"?idProperty=email"
        )
        body = {"properties": properties}

        raw = self._http_request("PATCH", url, body=body)

        contact_id = raw.get("id", "")
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "contact_id": contact_id,
                "email": email,
                "upserted": True,
            },
            raw=raw,
        )

    # ── List deals ─────────────────────────────────────────────

    def _do_list_deals(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        limit = int(params.get("limit", 20))
        after = params.get("after")

        url = (
            f"{self.base_url}/crm/v3/objects/deals"
            f"?limit={limit}"
            f"&properties=dealname,amount,dealstage,closedate,pipeline"
        )
        if after:
            url += f"&after={after}"

        raw = self._http_request("GET", url)

        deals = []
        for d in raw.get("results", []):
            props = d.get("properties", {}) or {}
            deals.append({
                "id": d.get("id", ""),
                "name": props.get("dealname", ""),
                "amount": props.get("amount", ""),
                "stage": props.get("dealstage", ""),
                "close_date": props.get("closedate", ""),
                "pipeline": props.get("pipeline", ""),
            })

        paging = (raw.get("paging") or {}).get("next") or {}
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "deals": deals,
                "count": len(deals),
                "next_cursor": paging.get("after", ""),
            },
            raw=raw,
        )

    # ── Create deal ────────────────────────────────────────────

    def _do_create_deal(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        name = params.get("name") or params.get("dealname")
        if not name:
            raise AdapterValidationError(
                self.name, "'name' is required",
            )

        properties: dict[str, Any] = {"dealname": name}
        if "amount" in params:
            properties["amount"] = str(params["amount"])
        if "stage" in params:
            properties["dealstage"] = params["stage"]
        if "pipeline" in params:
            properties["pipeline"] = params["pipeline"]
        if "close_date" in params:
            properties["closedate"] = params["close_date"]
        for k, v in (params.get("properties") or {}).items():
            properties[k] = v

        url = f"{self.base_url}/crm/v3/objects/deals"
        body: dict[str, Any] = {"properties": properties}

        # Optional contact association.
        contact_id = params.get("contact_id")
        if contact_id:
            body["associations"] = [{
                "to": {"id": str(contact_id)},
                "types": [{
                    "associationCategory": "HUBSPOT_DEFINED",
                    "associationTypeId": 3,  # deal→contact primary
                }],
            }]

        raw = self._http_request("POST", url, body=body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "deal_id": raw.get("id", ""),
                "name": name,
                "created": True,
            },
            raw=raw,
        )
