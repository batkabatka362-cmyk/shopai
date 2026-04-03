"""CRM adapter for ShopAI — customer relationship management operations."""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class CRMAdapter(BaseToolAdapter):
    tool_name = "crm"
    tool_category = "commerce"
    version = "1.0.0"

    BASE_URL = "https://api.hubspot.com/crm/v3"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._api_key: str = ""
        self._portal_id: str = ""

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._api_key = credentials.get("api_key", "")
        self._portal_id = credentials.get("portal_id", "")

    def capabilities(self) -> list[str]:
        return [
            "sync_customers",
            "get_customer_profile",
            "create_segment",
            "list_segments",
            "add_to_list",
            "remove_from_list",
            "get_customer_events",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "sync_customers": self._sync_customers,
            "get_customer_profile": self._get_customer_profile,
            "create_segment": self._create_segment,
            "list_segments": self._list_segments,
            "add_to_list": self._add_to_list,
            "remove_from_list": self._remove_from_list,
            "get_customer_events": self._get_customer_events,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, data={}, error=f"Unknown action: {action}")
        start = time.monotonic()
        try:
            result = handler(params)
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=True,
                data=result,
                error=None,
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        healthy = bool(self._api_key)
        latency = (time.monotonic() - start) * 1000 + 65.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No CRM API key configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=10.0, burst=100, daily_quota=250000)

    # ── handlers ──────────────────────────────────────────────

    def _sync_customers(self, params: dict) -> dict:
        source = params.get("source", "shopify")
        batch_size = params.get("batch_size", 100)
        since = params.get("since")
        return {
            "endpoint": f"{self.BASE_URL}/objects/contacts/batch/upsert",
            "method": "POST",
            "source": source,
            "options": {
                "batch_size": batch_size,
                "since": since,
                "dedup_property": "email",
            },
            "sync_id": str(uuid.uuid4()),
            "synced_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "error_count": 0,
        }

    def _get_customer_profile(self, params: dict) -> dict:
        if "customer_id" not in params and "email" not in params:
            raise ValueError("customer_id or email is required")
        identifier = params.get("customer_id") or params.get("email")
        id_type = "customer_id" if "customer_id" in params else "email"
        properties = params.get("properties", [
            "email", "firstname", "lastname", "phone",
            "lifecyclestage", "hs_lead_status", "total_revenue",
            "num_associated_deals", "recent_deal_amount",
        ])
        return {
            "endpoint": f"{self.BASE_URL}/objects/contacts/{identifier}",
            "method": "GET",
            "query": {"properties": ",".join(properties), "idProperty": id_type},
            "profile": {},
            "associated_deals": [],
            "associated_tickets": [],
        }

    def _create_segment(self, params: dict) -> dict:
        if "name" not in params or "filters" not in params:
            raise ValueError("name and filters are required")
        filters = params["filters"]
        if not isinstance(filters, list):
            raise ValueError("filters must be a list of filter groups")
        return {
            "endpoint": f"{self.BASE_URL}/lists",
            "method": "POST",
            "payload": {
                "name": params["name"],
                "objectTypeId": "0-1",  # contacts
                "processingType": "DYNAMIC",
                "filterBranch": {
                    "filterBranchType": "AND",
                    "filters": filters,
                },
            },
            "segment_id": str(uuid.uuid4()),
        }

    def _list_segments(self, params: dict) -> dict:
        limit = params.get("limit", 50)
        offset = params.get("offset", 0)
        return {
            "endpoint": f"{self.BASE_URL}/lists",
            "method": "GET",
            "query": {"count": limit, "offset": offset},
            "segments": [],
            "total_count": 0,
            "has_more": False,
        }

    def _add_to_list(self, params: dict) -> dict:
        if "list_id" not in params or "contact_ids" not in params:
            raise ValueError("list_id and contact_ids are required")
        contact_ids = params["contact_ids"]
        if not isinstance(contact_ids, list):
            raise ValueError("contact_ids must be a list")
        return {
            "endpoint": f"{self.BASE_URL}/lists/{params['list_id']}/memberships/add",
            "method": "PUT",
            "payload": contact_ids,
            "list_id": params["list_id"],
            "added_count": len(contact_ids),
        }

    def _remove_from_list(self, params: dict) -> dict:
        if "list_id" not in params or "contact_ids" not in params:
            raise ValueError("list_id and contact_ids are required")
        contact_ids = params["contact_ids"]
        if not isinstance(contact_ids, list):
            raise ValueError("contact_ids must be a list")
        return {
            "endpoint": f"{self.BASE_URL}/lists/{params['list_id']}/memberships/remove",
            "method": "PUT",
            "payload": contact_ids,
            "list_id": params["list_id"],
            "removed_count": len(contact_ids),
        }

    def _get_customer_events(self, params: dict) -> dict:
        if "customer_id" not in params:
            raise ValueError("customer_id is required")
        event_type = params.get("event_type")
        limit = params.get("limit", 50)
        query: dict = {"limit": limit, "objectId": params["customer_id"]}
        if event_type:
            query["eventType"] = event_type
        return {
            "endpoint": f"{self.BASE_URL}/objects/contacts/{params['customer_id']}/events",
            "method": "GET",
            "query": query,
            "events": [],
            "total_count": 0,
        }
