"""GorgiasAdapter -- Gorgias Helpdesk API.

API docs: https://developers.gorgias.com/reference

Auth: HTTP Basic with `<gorgias_username>:<api_key>`
base64-encoded.

Per-store creds via W963-117 helper:
  SHOPAI_STORE_<SID>_GORGIAS_API_KEY (per-store)
  GORGIAS_API_KEY (fleet)
  GORGIAS_USERNAME / SHOPAI_STORE_<SID>_GORGIAS_USERNAME
  GORGIAS_SUBDOMAIN / SHOPAI_STORE_<SID>_GORGIAS_SUBDOMAIN

For multi-store empires each store has its own Gorgias
subdomain (e.g. acme.gorgias.com), so the URL is built
from the per-store config rather than hardcoded.

Status normalisation:
  Gorgias 'open' / 'waiting' -> open / pending
  Gorgias 'closed' / 'resolved' -> closed / resolved
"""
from __future__ import annotations

import base64
from typing import Any

from ..config import get_config
from .._per_store_credentials import (
    resolve_per_store as _resolve_per_store,
)
from ..errors import AdapterNotConfigured
from ._base import (
    TICKET_CLOSED,
    TICKET_OPEN,
    TICKET_PENDING,
    TICKET_RESOLVED,
    TICKET_SPAM,
    HelpdeskBaseAdapter,
)


# Gorgias 'status' -> normalised
_GORGIAS_STATUS_MAP = {
    "open": TICKET_OPEN,
    "waiting": TICKET_PENDING,
    "snoozed": TICKET_PENDING,
    "closed": TICKET_CLOSED,
    "resolved": TICKET_RESOLVED,
    "spam": TICKET_SPAM,
}


class GorgiasAdapter(HelpdeskBaseAdapter):
    """Gorgias helpdesk integration."""

    name = "gorgias"
    config_alias = "gorgias_api_key"
    cost_per_call = 0.0

    # base_url is derived per-call from the per-store
    # subdomain config; default to empty so the base
    # class's is_configured check still works.
    @property
    def base_url(self) -> str:  # type: ignore[override]
        sub = (
            _resolve_per_store("gorgias_subdomain")
            or get_config().get("gorgias_subdomain")
            or ""
        )
        if not sub:
            return ""
        return f"https://{sub}.gorgias.com"

    # ── Auth (Basic) ──────────────────────────────────────────

    def _gorgias_user(self) -> str:
        u = (
            _resolve_per_store("gorgias_username")
            or get_config().get("gorgias_username")
            or ""
        )
        if not u:
            raise AdapterNotConfigured(
                self.name,
                "missing GORGIAS_USERNAME (set in env "
                "or per-store override)",
            )
        return u

    def _auth_headers(self) -> dict[str, str]:
        token = base64.b64encode(
            f"{self._gorgias_user()}:{self._api_key()}"
            .encode("utf-8"),
        ).decode("ascii")
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def is_configured(self) -> bool:
        # Need both api_key + username + subdomain.
        if not self.base_url:
            return False
        if not (
            _resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias)
        ):
            return False
        if not (
            _resolve_per_store("gorgias_username")
            or get_config().get("gorgias_username")
        ):
            return False
        return True

    # ── Paths ─────────────────────────────────────────────────

    def _list_path(
        self, *, limit: int, status_filter: str,
    ) -> str:
        limit_clamped = max(1, min(limit, 100))
        qs = f"limit={limit_clamped}"
        if status_filter:
            qs += f"&status={status_filter}"
        return f"/api/tickets?{qs}"

    def _get_path(self, *, ticket_id: str) -> str:
        return f"/api/tickets/{ticket_id}"

    def _reply_path(self, *, ticket_id: str) -> str:
        return f"/api/tickets/{ticket_id}/messages"

    def _update_tags_path(
        self, *, ticket_id: str,
    ) -> str:
        return f"/api/tickets/{ticket_id}"

    def _create_ticket_path(self) -> str:
        return "/api/tickets"

    # ── Payload + response shapes ─────────────────────────────

    def _parse_list_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        data = raw.get("data") or []
        tickets: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            tickets.append(self._normalise_ticket(row))
        return {
            "count": len(tickets),
            "tickets": tickets,
        }

    def _parse_get_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        return self._normalise_ticket(raw)

    def _build_reply_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        body = kwargs["body"]
        channel = kwargs.get("channel", "email")
        return {
            "body_text": body,
            "body_html": body,
            "channel": channel,
            "from_agent": True,
            "via": "api",
        }

    def _build_update_tags_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        # Gorgias represents tags as list of {name}
        # objects on the ticket PUT
        return {
            "tags": [
                {"name": str(t)}
                for t in kwargs["tags"]
            ],
        }

    def _build_create_ticket_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        subject = kwargs["subject"]
        body = kwargs["body"]
        email = kwargs["customer_email"]
        tags = kwargs.get("tags") or []
        return {
            "subject": subject,
            "channel": "email",
            "via": "api",
            "from_agent": False,
            "customer": {"email": email},
            "messages": [{
                "body_text": body,
                "body_html": body,
                "channel": "email",
            }],
            "tags": [
                {"name": str(t)} for t in tags
            ],
        }

    def _parse_create_ticket_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ticket_id": raw.get("id", ""),
            "created": True,
        }

    # ── Helpers ───────────────────────────────────────────────

    def _normalise_ticket(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        customer = raw.get("customer") or {}
        if not isinstance(customer, dict):
            customer = {}
        tags = []
        for t in raw.get("tags") or []:
            if isinstance(t, dict):
                name = t.get("name")
                if name:
                    tags.append(str(name))
            elif isinstance(t, str):
                tags.append(t)
        return {
            "id": str(raw.get("id", "")),
            "subject": raw.get("subject", ""),
            "status": _GORGIAS_STATUS_MAP.get(
                raw.get("status", ""), "unknown",
            ),
            "channel": raw.get("channel", ""),
            "customer": {
                "email": customer.get("email", ""),
                "name": customer.get(
                    "firstname",
                    "",
                ) + " " + customer.get(
                    "lastname", "",
                ),
            },
            "tags": tags,
            "last_message_at": raw.get(
                "last_message_datetime", "",
            ),
            "created_at": raw.get("created_datetime", ""),
        }
