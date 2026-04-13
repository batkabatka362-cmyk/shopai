"""CrispAdapter — Crisp live-chat / helpdesk platform.

Crisp is a modern customer messaging platform (live chat, inbox,
knowledge base) used by 500,000+ startups and SMBs. This adapter
wraps the Crisp REST API v1 for:

  * **List conversations** — recent chats from all website visitors
  * **Send reply**         — operator-text reply to a conversation
  * **Search contacts**    — find a visitor/people by email
  * **Create ticket**      — start a new conversation with a visitor

Authentication: HTTP Basic with ``identifier:key`` + the tier
header ``X-Crisp-Tier: plugin`` (or ``user`` / ``plugin`` /
``plan`` depending on the credentials used). Every call is scoped
by the website identifier (UUID).

Free tier: Yes (2 operators, unlimited messages).
Reference: https://docs.crisp.chat/references/rest-api/v1/
"""
from __future__ import annotations

import base64
from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterNotConfigured, AdapterValidationError
from ._base import HelpdeskBaseAdapter


class CrispAdapter(HelpdeskBaseAdapter):
    name = "crisp"
    base_url = "https://api.crisp.chat/v1"
    config_alias = "crisp_key"

    priority = 70
    cost_per_call = 0.0

    def is_configured(self) -> bool:
        cfg = get_config()
        return bool(
            cfg.get("crisp_identifier")
            and cfg.get("crisp_key")
            and cfg.get("crisp_website_id")
        )

    def _website_id(self) -> str:
        wid = get_config().get("crisp_website_id")
        if not wid:
            raise AdapterNotConfigured(
                self.name, "missing CRISP_WEBSITE_ID",
            )
        return wid

    def _auth_headers(self) -> dict[str, str]:
        cfg = get_config()
        identifier = cfg.get("crisp_identifier")
        key = cfg.get("crisp_key")
        if not (identifier and key):
            raise AdapterNotConfigured(
                self.name,
                "missing Crisp credentials "
                "(CRISP_IDENTIFIER + CRISP_KEY)",
            )
        userpass = f"{identifier}:{key}"
        encoded = base64.b64encode(userpass.encode()).decode()
        return {
            "Authorization": f"Basic {encoded}",
            "X-Crisp-Tier": "plugin",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── List conversations ─────────────────────────────────────

    def _do_list_conversations(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        wid = self._website_id()
        page = int(params.get("page", 1))
        filter_state = params.get("state", "")  # unresolved, resolved, pending

        url = f"{self.base_url}/website/{wid}/conversations/{page}"
        if filter_state:
            url += f"?filter_resolved=0" if filter_state == "unresolved" else ""

        raw = self._http_request("GET", url)

        conversations = []
        for c in raw.get("data", []):
            meta = c.get("meta", {}) or {}
            conversations.append({
                "id": c.get("session_id", ""),
                "title": meta.get("subject", "") or c.get("last_message", "")[:80],
                "state": c.get("state", ""),
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
                "unread_count": c.get("unread", {}).get("operator", 0),
                "email": meta.get("email", ""),
                "nickname": meta.get("nickname", ""),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "conversations": conversations,
                "count": len(conversations),
                "page": page,
            },
            raw=raw,
        )

    # ── Send reply ─────────────────────────────────────────────

    def _do_send_reply(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        wid = self._website_id()
        session_id = params.get("conversation_id") or params.get("session_id")
        if not session_id:
            raise AdapterValidationError(
                self.name, "'conversation_id' (session_id) is required",
            )
        content = params.get("body") or params.get("message")
        if not content:
            raise AdapterValidationError(
                self.name, "'body' is required",
            )

        from_who = params.get("from", "operator")  # operator or user
        url = (
            f"{self.base_url}/website/{wid}"
            f"/conversation/{session_id}/message"
        )
        body: dict[str, Any] = {
            "type": "text",
            "content": content,
            "from": from_who,
            "origin": "chat",
        }

        raw = self._http_request("POST", url, body=body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "conversation_id": session_id,
                "sent": True,
            },
            raw=raw,
        )

    # ── Search contacts (people) ───────────────────────────────

    def _do_search_contacts(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        wid = self._website_id()
        query = params.get("query") or params.get("email")
        if not query:
            raise AdapterValidationError(
                self.name, "'query' or 'email' is required",
            )

        url = (
            f"{self.base_url}/website/{wid}/people/profiles/1"
            f"?search_filter=%5B%7B%22model%22%3A%22people%22%2C"
            f"%22criterion%22%3A%22email%22%2C%22operator%22%3A%22eq%22%2C"
            f"%22query%22%3A%22{query}%22%7D%5D"
        )

        raw = self._http_request("GET", url)

        contacts = []
        for p in raw.get("data", []):
            contacts.append({
                "id": p.get("people_id", ""),
                "email": p.get("email", ""),
                "name": p.get("person", {}).get("nickname", ""),
                "avatar": p.get("person", {}).get("avatar", ""),
                "created_at": p.get("created_at"),
                "segments": p.get("segments", []),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "contacts": contacts,
                "count": len(contacts),
            },
            raw=raw,
        )

    # ── Create ticket (new conversation) ──────────────────────

    def _do_create_ticket(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        wid = self._website_id()
        body_text = params.get("body") or params.get("message")
        if not body_text:
            raise AdapterValidationError(
                self.name, "'body' is required",
            )

        # Step 1: create empty conversation → get session_id.
        url = f"{self.base_url}/website/{wid}/conversation"
        raw_create = self._http_request("POST", url, body={})
        session_id = (raw_create.get("data") or {}).get("session_id", "")
        if not session_id:
            return AdapterResult.success(
                adapter=self.name,
                capability=capability.value,
                data={"conversation_id": "", "created": False},
                raw=raw_create,
            )

        # Step 2: initial message.
        msg_url = (
            f"{self.base_url}/website/{wid}"
            f"/conversation/{session_id}/message"
        )
        msg_body = {
            "type": "text",
            "content": body_text,
            "from": params.get("from", "user"),
            "origin": "chat",
        }
        raw_msg = self._http_request("POST", msg_url, body=msg_body)

        # Step 3 (optional): update meta with email/nickname.
        email = params.get("email")
        nickname = params.get("nickname") or params.get("name")
        if email or nickname:
            meta_url = (
                f"{self.base_url}/website/{wid}"
                f"/conversation/{session_id}/meta"
            )
            meta_body: dict[str, Any] = {}
            if email:
                meta_body["email"] = email
            if nickname:
                meta_body["nickname"] = nickname
            if params.get("subject"):
                meta_body["subject"] = params["subject"]
            self._http_request("PATCH", meta_url, body=meta_body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "conversation_id": session_id,
                "created": True,
            },
            raw={"create": raw_create, "message": raw_msg},
        )
