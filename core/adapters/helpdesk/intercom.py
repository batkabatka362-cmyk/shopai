"""IntercomAdapter — Intercom customer messaging platform.

Intercom is a customer messaging platform used by 25,000+ businesses
for live chat, help desk, and proactive support. This adapter wraps
the Intercom REST API v2.11 for:

  * **List conversations** — fetch open/recent customer conversations
  * **Send reply**         — reply to an existing conversation
  * **Search contacts**    — find customers by email/name
  * **Create ticket**      — start a new conversation on behalf of a user

Authentication: Bearer token (access token from Intercom developer hub).
Free tier: None (starts at $39/seat/month).
Reference: https://developers.intercom.com/docs/references/rest-api/api.intercom.io/
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ..errors import AdapterValidationError
from ._base import HelpdeskBaseAdapter


class IntercomAdapter(HelpdeskBaseAdapter):
    name = "intercom"
    base_url = "https://api.intercom.io"
    config_alias = "intercom"

    priority = 90
    cost_per_call = 0.0  # API itself is free; seat cost is separate

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Intercom-Version": "2.11",
        }

    # ── List conversations ────────────────────────────────────

    def _do_list_conversations(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        page = int(params.get("page", 1))
        per_page = int(params.get("per_page", 20))
        status = params.get("status", "open")  # open, closed, snoozed

        url = (
            f"{self.base_url}/conversations"
            f"?per_page={per_page}&page={page}"
        )

        raw = self._http_request("GET", url)

        conversations = []
        for conv in raw.get("conversations", []):
            source = conv.get("source", {})
            stats = conv.get("statistics", {})
            conversations.append({
                "id": conv.get("id", ""),
                "title": source.get("subject", "") or source.get("body", "")[:80],
                "state": conv.get("state", ""),
                "created_at": conv.get("created_at"),
                "updated_at": conv.get("updated_at"),
                "waiting_since": conv.get("waiting_since"),
                "first_response_time": stats.get("first_contact_reply_at"),
                "assignee_type": (conv.get("assignee", {}) or {}).get("type", ""),
            })

        total = raw.get("total_count", len(conversations))
        pages_data = raw.get("pages", {})

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "conversations": conversations,
                "count": len(conversations),
                "total": total,
                "page": page,
                "has_next": bool(pages_data.get("next")),
            },
            raw=raw,
        )

    # ── Send reply ────────────────────────────────────────────

    def _do_send_reply(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        conversation_id = params.get("conversation_id")
        if not conversation_id:
            raise AdapterValidationError(
                self.name, "'conversation_id' is required",
            )
        body_text = params.get("body") or params.get("message")
        if not body_text:
            raise AdapterValidationError(
                self.name, "'body' is required",
            )

        message_type = params.get("message_type", "comment")
        admin_id = params.get("admin_id")

        url = f"{self.base_url}/conversations/{conversation_id}/reply"
        body: dict[str, Any] = {
            "message_type": message_type,
            "type": "admin",
            "body": body_text,
        }
        if admin_id:
            body["admin_id"] = admin_id

        raw = self._http_request("POST", url, body=body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "conversation_id": conversation_id,
                "message_type": message_type,
                "sent": True,
            },
            raw=raw,
        )

    # ── Search contacts ───────────────────────────────────────

    def _do_search_contacts(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        query = params.get("query") or params.get("email")
        if not query:
            raise AdapterValidationError(
                self.name, "'query' or 'email' is required for contact search",
            )

        # Intercom search API uses a structured query format
        field = params.get("field", "email")
        operator = params.get("operator", "=")

        url = f"{self.base_url}/contacts/search"
        body = {
            "query": {
                "field": field,
                "operator": operator,
                "value": query,
            },
        }

        raw = self._http_request("POST", url, body=body)

        contacts = []
        for c in raw.get("data", []):
            contacts.append({
                "id": c.get("id", ""),
                "external_id": c.get("external_id", ""),
                "email": c.get("email", ""),
                "name": c.get("name", ""),
                "role": c.get("role", ""),
                "created_at": c.get("created_at"),
                "last_seen_at": c.get("last_seen_at"),
                "custom_attributes": c.get("custom_attributes", {}),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "contacts": contacts,
                "count": len(contacts),
                "total": raw.get("total_count", len(contacts)),
            },
            raw=raw,
        )

    # ── Create ticket ─────────────────────────────────────────

    def _do_create_ticket(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        body_text = params.get("body") or params.get("message")
        if not body_text:
            raise AdapterValidationError(
                self.name, "'body' is required to create a ticket",
            )

        # Need either a contact_id or from dict
        contact_id = params.get("contact_id") or params.get("from_id")
        if not contact_id:
            raise AdapterValidationError(
                self.name, "'contact_id' is required",
            )

        url = f"{self.base_url}/conversations"
        req_body: dict[str, Any] = {
            "from": {
                "type": "user",
                "id": contact_id,
            },
            "body": body_text,
        }
        if params.get("subject"):
            req_body["subject"] = params["subject"]

        raw = self._http_request("POST", url, body=req_body)

        conversation_id = raw.get("id", "")

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "conversation_id": conversation_id,
                "contact_id": contact_id,
                "created": True,
            },
            raw=raw,
        )
