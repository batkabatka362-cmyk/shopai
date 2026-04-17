"""ZendeskAdapter — Zendesk customer support platform.

Zendesk is the market-leading enterprise helpdesk (160,000+
businesses). This adapter wraps the Zendesk v2 REST API for:

  * **List tickets**     — mapped to HELPDESK_LIST_CONVERSATIONS
  * **Add comment**      — mapped to HELPDESK_SEND_REPLY
  * **Search users**     — mapped to HELPDESK_SEARCH_CONTACTS
  * **Create ticket**    — mapped to HELPDESK_CREATE_TICKET

Authentication: HTTP Basic auth — username is ``{email}/token``,
password is the API token. Subdomain scopes the tenant.
Free tier: None (starts ~$19/agent/month).
Reference: https://developer.zendesk.com/api-reference/ticketing/introduction/
"""
from __future__ import annotations

import base64
from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterNotConfigured, AdapterValidationError
from ._base import HelpdeskBaseAdapter


class ZendeskAdapter(HelpdeskBaseAdapter):
    name = "zendesk"
    config_alias = "zendesk_api_token"

    priority = 80
    cost_per_call = 0.0

    @property
    def base_url(self) -> str:  # type: ignore[override]
        subdomain = get_config().get("zendesk_subdomain")
        if not subdomain:
            return ""
        return f"https://{subdomain}.zendesk.com/api/v2"

    def is_configured(self) -> bool:
        cfg = get_config()
        return bool(
            cfg.get("zendesk_subdomain")
            and cfg.get("zendesk_email")
            and cfg.get("zendesk_api_token")
        )

    def _auth_headers(self) -> dict[str, str]:
        cfg = get_config()
        email = cfg.get("zendesk_email")
        token = cfg.get("zendesk_api_token")
        if not (email and token):
            raise AdapterNotConfigured(
                self.name,
                "missing Zendesk credentials "
                "(ZENDESK_EMAIL + ZENDESK_API_TOKEN)",
            )
        userpass = f"{email}/token:{token}"
        encoded = base64.b64encode(userpass.encode()).decode()
        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── List tickets (= conversations) ─────────────────────────

    def _do_list_conversations(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        per_page = int(params.get("per_page", 25))
        page = int(params.get("page", 1))
        status = params.get("status", "")  # open, pending, solved, closed, hold

        if status:
            # Search API supports status filtering.
            url = (
                f"{self.base_url}/search.json"
                f"?query=type:ticket status:{status}"
                f"&per_page={per_page}&page={page}"
            )
        else:
            url = (
                f"{self.base_url}/tickets.json"
                f"?per_page={per_page}&page={page}"
            )

        raw = self._http_request("GET", url)

        tickets = raw.get("results") or raw.get("tickets") or []
        conversations = []
        for t in tickets:
            conversations.append({
                "id": str(t.get("id", "")),
                "title": t.get("subject", "") or "",
                "state": t.get("status", ""),
                "priority": t.get("priority", ""),
                "requester_id": t.get("requester_id"),
                "assignee_id": t.get("assignee_id"),
                "created_at": t.get("created_at"),
                "updated_at": t.get("updated_at"),
                "tags": t.get("tags", []),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "conversations": conversations,
                "count": len(conversations),
                "total": raw.get("count", len(conversations)),
                "page": page,
                "has_next": bool(raw.get("next_page")),
            },
            raw=raw,
        )

    # ── Send reply (add comment) ───────────────────────────────

    def _do_send_reply(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        ticket_id = params.get("conversation_id") or params.get("ticket_id")
        if not ticket_id:
            raise AdapterValidationError(
                self.name, "'conversation_id' (ticket_id) is required",
            )
        body_text = params.get("body") or params.get("message")
        if not body_text:
            raise AdapterValidationError(
                self.name, "'body' is required",
            )

        public = bool(params.get("public", True))
        status = params.get("status")  # optional status change

        comment: dict[str, Any] = {
            "body": body_text,
            "public": public,
        }
        ticket_payload: dict[str, Any] = {"comment": comment}
        if status:
            ticket_payload["status"] = status

        url = f"{self.base_url}/tickets/{ticket_id}.json"
        raw = self._http_request("PUT", url, body={"ticket": ticket_payload})

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "conversation_id": str(ticket_id),
                "public": public,
                "sent": True,
            },
            raw=raw,
        )

    # ── Search contacts (users) ────────────────────────────────

    def _do_search_contacts(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        query = params.get("query") or params.get("email")
        if not query:
            raise AdapterValidationError(
                self.name, "'query' or 'email' is required",
            )

        url = f"{self.base_url}/users/search.json?query={query}"
        raw = self._http_request("GET", url)

        contacts = []
        for u in raw.get("users", []):
            contacts.append({
                "id": str(u.get("id", "")),
                "email": u.get("email", "") or "",
                "name": u.get("name", "") or "",
                "role": u.get("role", ""),
                "created_at": u.get("created_at"),
                "organization_id": u.get("organization_id"),
                "phone": u.get("phone", ""),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "contacts": contacts,
                "count": len(contacts),
                "total": raw.get("count", len(contacts)),
            },
            raw=raw,
        )

    # ── Create ticket ──────────────────────────────────────────

    def _do_create_ticket(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        subject = params.get("subject") or params.get("title")
        if not subject:
            raise AdapterValidationError(
                self.name, "'subject' is required",
            )
        body_text = params.get("body") or params.get("message")
        if not body_text:
            raise AdapterValidationError(
                self.name, "'body' is required",
            )

        ticket: dict[str, Any] = {
            "subject": subject,
            "comment": {"body": body_text},
        }
        if params.get("priority"):
            ticket["priority"] = params["priority"]
        if params.get("type"):
            ticket["type"] = params["type"]
        if params.get("tags"):
            ticket["tags"] = params["tags"]

        # Requester by id or email.
        if params.get("requester_id"):
            ticket["requester_id"] = params["requester_id"]
        elif params.get("requester_email"):
            ticket["requester"] = {
                "email": params["requester_email"],
                "name": params.get("requester_name", ""),
            }

        url = f"{self.base_url}/tickets.json"
        raw = self._http_request("POST", url, body={"ticket": ticket})

        created = raw.get("ticket", {}) or {}
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "conversation_id": str(created.get("id", "")),
                "subject": subject,
                "created": True,
            },
            raw=raw,
        )
